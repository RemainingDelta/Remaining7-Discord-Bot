import asyncio
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import aiohttp
import cv2
import discord
import numpy as np
from discord.ext import commands

from database.mongo import (
    acquire_scam_detection_lock,
    add_hacked_user,
    add_scam_image,
    ensure_scam_lock_ttl_index,
    get_scam_images,
    remove_scam_image,
    rename_scam_image,
)
from features.config import MODERATOR_LOGS_CHANNEL_ID

# pHash: max Hamming distance (out of 64 bits) to count as a match.
# 0 = identical, <=5 = same image different compression, <=10 = minor resize/edit.
PHASH_MATCH_THRESHOLD = 10

# ORB: catches cropped/rotated variants. False positives only delete one message
# now (no auto hacked-protocol), so threshold can be lower.
ORB_MATCH_THRESHOLD = 15
_ORB_DISTANCE_CUTOFF = 20

# How far back to scan other channels for the same image after detection.
_PURGE_LOOKBACK_MINUTES = 30

_ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# MongoDB documents cap at 16MB — reject blacklist additions above this.
_MAX_BLACKLIST_IMAGE_BYTES = 15 * 1024 * 1024


def _compute_phash(img_gray: np.ndarray) -> int:
    small = cv2.resize(img_gray, (32, 32), interpolation=cv2.INTER_AREA).astype(
        np.float32
    )
    dct = cv2.dct(small)
    dct_low = dct[:8, :8].flatten()
    mean = dct_low.mean()
    bits = (dct_low > mean).astype(np.uint8)
    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def _phash_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


def _compute_features(image_bytes: bytes) -> tuple:
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, None
    phash = _compute_phash(img)
    orb = cv2.ORB_create()
    _, desc = orb.detectAndCompute(img, None)
    return phash, desc


def _sync_check_image(
    image_bytes: bytes,
    md5_set: set,
    phash_index: list,
    orb_index: list,
) -> tuple[bool, str | None]:
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

    md5 = hashlib.md5(image_bytes).hexdigest()
    if md5 in md5_set:
        return True, "MD5"

    if img is None:
        return False, None

    query_phash = _compute_phash(img)
    for filename, ref_phash in phash_index:
        dist = _phash_distance(query_phash, ref_phash)
        if dist <= PHASH_MATCH_THRESHOLD:
            return True, f"pHash ({filename}, dist={dist})"

    orb = cv2.ORB_create()
    _, query_desc = orb.detectAndCompute(img, None)
    if query_desc is not None and len(query_desc) > 0 and orb_index:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        for filename, ref_desc in orb_index:
            if ref_desc is None or len(ref_desc) == 0:
                continue
            matches = bf.match(query_desc, ref_desc)
            good = [m for m in matches if m.distance < _ORB_DISTANCE_CUTOFF]
            if len(good) >= ORB_MATCH_THRESHOLD:
                return True, f"ORB ({filename}, {len(good)} keypoints)"

    return False, None


def _sync_check_image_verbose(
    image_bytes: bytes,
    md5_set: set,
    phash_index: list,
    orb_index: list,
) -> tuple[bool, str | None, list[str]]:
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    details = []

    md5 = hashlib.md5(image_bytes).hexdigest()
    if md5 in md5_set:
        return True, "MD5", [f"MD5 exact match: `{md5[:8]}`"]

    if img is None:
        return False, None, ["Could not decode image"]

    query_phash = _compute_phash(img)
    phash_results = []
    for filename, ref_phash in phash_index:
        dist = _phash_distance(query_phash, ref_phash)
        phash_results.append((dist, filename))
        if dist <= PHASH_MATCH_THRESHOLD:
            return (
                True,
                f"pHash ({filename})",
                [
                    f"pHash match: `{filename}` distance **{dist}**/64 (threshold {PHASH_MATCH_THRESHOLD})"
                ],
            )
    if phash_results:
        best_dist, best_file = min(phash_results)
        details.append(
            f"pHash closest: `{best_file}` distance **{best_dist}**/64 (threshold {PHASH_MATCH_THRESHOLD})"
        )
    else:
        details.append("pHash: no entries in blacklist")

    orb = cv2.ORB_create()
    _, query_desc = orb.detectAndCompute(img, None)
    if query_desc is not None and len(query_desc) > 0 and orb_index:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        best_count, best_orb_file = 0, None
        for filename, ref_desc in orb_index:
            if ref_desc is None or len(ref_desc) == 0:
                continue
            matches = bf.match(query_desc, ref_desc)
            good = [m for m in matches if m.distance < _ORB_DISTANCE_CUTOFF]
            if len(good) > best_count:
                best_count, best_orb_file = len(good), filename
        if best_orb_file:
            details.append(
                f"ORB closest: `{best_orb_file}` **{best_count}** keypoints (threshold {ORB_MATCH_THRESHOLD})"
            )

    return False, None, details


def _is_allowed_image(filename: str) -> bool:
    return filename.lower().endswith(_ALLOWED_EXTENSIONS)


class ScamAlertView(discord.ui.View):
    """Sent to mod-log when a scam image is detected. Mods confirm or dismiss."""

    def __init__(self, target: discord.Member | discord.User, bot: commands.Bot):
        super().__init__(timeout=None)
        self.target = target
        self.bot = bot
        self._acted = False

    def _security_cog(self):
        return self.bot.cogs.get("Security")

    async def _has_permission(self, interaction: discord.Interaction) -> bool:
        security = self._security_cog()
        if security:
            return await security.has_security_permission(interaction)
        return False

    @discord.ui.button(
        label="Confirm Hacked", style=discord.ButtonStyle.danger, emoji="🚨"
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission denied.", ephemeral=True
            )
            return

        if self._acted:
            await interaction.response.send_message(
                "Already acted on this alert.", ephemeral=True
            )
            return
        self._acted = True
        await interaction.response.defer()

        guild = interaction.guild
        target = self.target

        # Attempt to get Member (for timeout + role guard)
        if isinstance(target, discord.User):
            try:
                target = await guild.fetch_member(target.id)
            except Exception:
                pass

        # Role guard
        if isinstance(target, discord.Member):
            if target.top_role >= guild.me.top_role:
                await interaction.followup.send(
                    "❌ Cannot act — user has equal or higher role than the bot.",
                    ephemeral=True,
                )
                self._acted = False
                return

        # Upgrade timeout from 10 minutes to 7 days
        timeout_status = "⚠️ User not in server — timeout skipped"
        if isinstance(target, discord.Member):
            try:
                await target.timeout(
                    timedelta(days=7), reason="Security: Confirmed Scam Account"
                )
                timeout_status = "✅ Upgraded to 7-day timeout"
            except Exception as e:
                timeout_status = f"⚠️ Timeout failed: {e}"

        # DB flag
        await add_hacked_user(str(target.id))

        # DM the user
        try:
            dm_embed = discord.Embed(
                title="🚨 Account Flagged as Compromised",
                description=(
                    "Your account has been flagged as **hacked** on the **Remaining 7** server.\n\n"
                    "You have been **timed out for 1 week** as a security measure.\n\n"
                    "If you recover your account, please message <@408419700729708545> to be untimed out."
                ),
                color=discord.Color.dark_red(),
            )
            await target.send(embed=dm_embed)
        except Exception:
            pass

        # Update the alert embed and disable buttons
        confirmed_embed = discord.Embed(
            title="🚨 Scam Detection — Confirmed",
            description=(
                f"**User:** {target.mention} (`{target.id}`)\n"
                f"**Confirmed by:** {interaction.user.mention}\n"
                f"**Timeout:** {timeout_status}\n"
                f"User flagged in database and DMed."
            ),
            color=discord.Color.dark_red(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(embed=confirmed_embed, view=self)

    @discord.ui.button(
        label="False Positive", style=discord.ButtonStyle.secondary, emoji="✅"
    )
    async def dismiss(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission denied.", ephemeral=True
            )
            return

        if self._acted:
            await interaction.response.send_message(
                "Already acted on this alert.", ephemeral=True
            )
            return
        self._acted = True

        # Remove the 10-minute precautionary timeout
        timeout_removed = False
        guild = interaction.guild
        target = self.target
        if isinstance(target, discord.User):
            try:
                target = await guild.fetch_member(target.id)
            except Exception:
                pass
        if isinstance(target, discord.Member):
            try:
                await target.timeout(
                    None, reason="Security: Scam alert dismissed as false positive"
                )
                timeout_removed = True
            except Exception:
                pass

        timeout_note = (
            "✅ 10-minute timeout removed."
            if timeout_removed
            else "⚠️ Could not remove timeout (user may have left)."
        )

        embed = discord.Embed(
            title="✅ Scam Alert — Dismissed",
            description=(
                f"**User:** {self.target.mention} (`{self.target.id}`)\n"
                f"**Dismissed by:** {interaction.user.mention}\n"
                f"**Timeout:** {timeout_note}\n"
                "Marked as false positive. No action taken."
            ),
            color=discord.Color.green(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class ScamDetection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._md5_set: set = set()
        self._phash_index: list = []
        self._orb_index: list = []
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="scam_det"
        )
        # Tracks (author_id, filename, size) while a detection is in progress
        # so concurrent on_message events for the same image don't send duplicate alerts.
        self._processing: set = set()

    async def cog_load(self):
        # Shared HTTP session for all image downloads (detection, purge, commands).
        self._session = aiohttp.ClientSession()
        # TTL index so detection locks auto-expire; without it re-posts of the
        # same image by the same user would stay locked out forever.
        try:
            await ensure_scam_lock_ttl_index()
        except Exception as e:
            print(f"⚠️ Scam Detection: could not create lock TTL index: {e}")
        await self._reload_index()

    async def cog_unload(self):
        self._executor.shutdown(wait=False)
        await self._session.close()

    async def _download(self, url: str) -> bytes:
        async with self._session.get(url) as resp:
            return await resp.read()

    async def _reload_index(self):
        docs = await get_scam_images()
        loop = asyncio.get_running_loop()

        futures = [
            loop.run_in_executor(self._executor, _compute_features, bytes(doc["data"]))
            for doc in docs
        ]
        results = await asyncio.gather(*futures)

        md5_set = set()
        phash_index = []
        orb_index = []
        for doc, (phash, desc) in zip(docs, results):
            md5_set.add(doc["md5"])
            if phash is not None:
                phash_index.append((doc["filename"], phash))
            if desc is not None and len(desc) > 0:
                orb_index.append((doc["filename"], desc))

        self._md5_set = md5_set
        self._phash_index = phash_index
        self._orb_index = orb_index

    async def _purge_scam_instances(
        self,
        guild: discord.Guild,
        author_id: int,
        image_md5: str,
        image_size: int,
        skip_message_id: int,
    ) -> tuple[int, list[str]]:
        """Delete all other instances of the same image (by MD5) across channels."""
        deleted = 0
        channels_hit = []
        cutoff = discord.utils.utcnow() - timedelta(minutes=_PURGE_LOOKBACK_MINUTES)

        all_channels = list(guild.text_channels) + list(guild.threads)
        for channel in all_channels:
            perms = channel.permissions_for(guild.me)
            if not perms.read_message_history:
                continue
            try:
                # newest-first so busy channels don't hide the most recent posts
                # behind the 200-message limit
                async for msg in channel.history(
                    after=cutoff, oldest_first=False, limit=200
                ):
                    if msg.author.id != author_id or msg.id == skip_message_id:
                        continue
                    for att in msg.attachments:
                        if not _is_allowed_image(att.filename):
                            continue
                        if att.size != image_size:
                            continue
                        try:
                            data = await self._download(att.url)
                            if hashlib.md5(data).hexdigest() == image_md5:
                                await msg.delete()
                                deleted += 1
                                channels_hit.append(channel.mention)
                        except Exception:
                            pass
            except Exception:
                pass
            await asyncio.sleep(0.1)

        return deleted, channels_hit

    def _security_cog(self):
        return self.bot.cogs.get("Security")

    async def _has_permission(self, ctx: commands.Context) -> bool:
        security = self._security_cog()
        if security:
            return await security.has_security_permission(ctx)
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Skip scam management commands (!scam-add / !scam-test with an image
        # attached) — otherwise the bot would delete the mod's own command
        # message and time them out.
        if message.content.startswith("!scam"):
            return

        age = (discord.utils.utcnow() - message.created_at).total_seconds()
        if age > 10:
            return

        for attachment in message.attachments:
            if not _is_allowed_image(attachment.filename):
                continue

            dedup_key = (message.author.id, attachment.filename, attachment.size)
            if dedup_key in self._processing:
                return
            self._processing.add(dedup_key)

            try:
                image_bytes = await self._download(attachment.url)
            except Exception:
                self._processing.discard(dedup_key)
                continue

            md5_set = set(self._md5_set)
            phash_index = list(self._phash_index)
            orb_index = list(self._orb_index)
            loop = asyncio.get_running_loop()

            try:
                matched, method = await loop.run_in_executor(
                    self._executor,
                    _sync_check_image,
                    image_bytes,
                    md5_set,
                    phash_index,
                    orb_index,
                )
            except Exception:
                self._processing.discard(dedup_key)
                continue

            if not matched:
                self._processing.discard(dedup_key)
                continue

            image_md5 = hashlib.md5(image_bytes).hexdigest()

            # Atomic DB lock — prevents duplicate alerts across concurrent handlers
            # and multiple bot instances. Skip if another handler claimed this first.
            claimed = await acquire_scam_detection_lock(message.author.id, image_md5)
            if not claimed:
                # Another handler owns the alert/timeout, but this copy of the
                # image still needs to go.
                try:
                    await message.delete()
                except Exception:
                    pass
                self._processing.discard(dedup_key)
                break

            # Delete the flagged message
            try:
                await message.delete()
            except Exception:
                pass

            # Delete other instances of the same image across channels
            other_deleted, channels_hit = await self._purge_scam_instances(
                message.guild,
                message.author.id,
                image_md5,
                attachment.size,
                message.id,
            )

            # Apply 10-minute precautionary timeout
            timeout_status = "⚠️ Could not timeout (missing permissions or user left)"
            target = message.author
            if isinstance(target, discord.Member):
                try:
                    await target.timeout(
                        timedelta(minutes=10),
                        reason="Security: Suspected scam image — pending mod review",
                    )
                    timeout_status = "✅ Timed out for 10 minutes (pending review)"
                except Exception:
                    pass

            # Build mod alert
            total_deleted = 1 + other_deleted
            channels_str = f"{message.channel.mention}" + (
                f", {', '.join(channels_hit)}" if channels_hit else ""
            )

            alert_embed = discord.Embed(
                title="🚨 Suspected Scam Image Detected",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Detected in:** {message.channel.mention}\n"
                    f"**Method:** {method}\n"
                    f"**Messages deleted:** {total_deleted} across {channels_str}\n"
                    f"**Auto-timeout:** {timeout_status}"
                ),
                color=discord.Color.orange(),
            )
            alert_embed.set_footer(
                text="Confirm to upgrade to 7-day timeout + DB flag + DM. Dismiss to remove the timeout."
            )

            # Re-upload the image so it persists in mod-log after original deletion
            file = discord.File(io.BytesIO(image_bytes), filename=attachment.filename)
            alert_embed.set_image(url=f"attachment://{attachment.filename}")

            mod_log = self.bot.get_channel(MODERATOR_LOGS_CHANNEL_ID)
            if mod_log:
                view = ScamAlertView(target=message.author, bot=self.bot)
                await mod_log.send(embed=alert_embed, file=file, view=view)

            # Keep the key alive for 60 seconds so rapid re-posts of the same
            # image by the same user don't send duplicate alerts.
            asyncio.get_running_loop().call_later(
                60, self._processing.discard, dedup_key
            )
            break

    # --- MANAGEMENT COMMANDS ---

    @commands.command(name="scam-add")
    async def scam_add(self, ctx: commands.Context):
        if not await self._has_permission(ctx):
            return

        target_msg = None
        if ctx.message.reference:
            try:
                target_msg = await ctx.channel.fetch_message(
                    ctx.message.reference.message_id
                )
            except Exception:
                pass

        attachments = []
        if target_msg:
            attachments = [
                a for a in target_msg.attachments if _is_allowed_image(a.filename)
            ]
        if not attachments:
            attachments = [
                a for a in ctx.message.attachments if _is_allowed_image(a.filename)
            ]

        if not attachments:
            await ctx.send(
                "❌ Reply to a message containing an image, or attach an image directly."
            )
            return

        added = []
        for attachment in attachments:
            if attachment.size > _MAX_BLACKLIST_IMAGE_BYTES:
                await ctx.send(
                    f"❌ `{attachment.filename}` is too large to store ({attachment.size // (1024 * 1024)}MB, max 15MB)."
                )
                continue

            try:
                image_bytes = await self._download(attachment.url)
            except Exception as e:
                await ctx.send(f"❌ Failed to download `{attachment.filename}`: {e}")
                continue

            md5 = hashlib.md5(image_bytes).hexdigest()
            await add_scam_image(attachment.filename, image_bytes, md5)
            added.append(attachment.filename)

        if added:
            await self._reload_index()
            filenames = ", ".join(f"`{f}`" for f in added)
            await ctx.send(
                f"✅ Added {filenames} to the scam blacklist. Index hot-reloaded ({len(self._md5_set)} images)."
            )

    @commands.command(name="scam-remove")
    async def scam_remove(self, ctx: commands.Context, *md5_prefixes: str):
        if not await self._has_permission(ctx):
            return

        if not md5_prefixes:
            await ctx.send(
                "❌ Usage: `!scam-remove <md5_prefix> [md5_prefix ...]` — use `!scam-list` to see valid prefixes."
            )
            return

        removed = []
        not_found = []
        for prefix in md5_prefixes:
            deleted = await remove_scam_image(prefix)
            if deleted:
                removed.append(f"`{prefix}` ({deleted})")
            else:
                not_found.append(f"`{prefix}`")

        if removed:
            await self._reload_index()

        lines = []
        if removed:
            lines.append(
                f"✅ Removed: {', '.join(removed)}. Index hot-reloaded ({len(self._md5_set)} images)."
            )
        if not_found:
            lines.append(
                f"❌ No entry found for: {', '.join(not_found)}. Use `!scam-list` to see valid prefixes."
            )
        await ctx.send("\n".join(lines))

    @commands.command(name="scam-list")
    async def scam_list(self, ctx: commands.Context):
        if not await self._has_permission(ctx):
            return

        docs = await get_scam_images(include_data=False)
        if not docs:
            await ctx.send("✅ Scam blacklist is empty.")
            return

        listing = "\n".join(
            f"• `{doc['filename']}` — `{doc['md5'][:8]}`" for doc in docs
        )
        embed = discord.Embed(
            title=f"🚨 Scam Image Blacklist — {len(docs)} image(s)",
            description=listing,
            color=discord.Color.dark_red(),
        )
        await ctx.send(embed=embed)

    @commands.command(name="scam-rename")
    async def scam_rename(
        self, ctx: commands.Context, md5_prefix: str, *, new_name: str
    ):
        if not await self._has_permission(ctx):
            return

        found = await rename_scam_image(md5_prefix, new_name)
        if found:
            await self._reload_index()
            await ctx.send(
                f"✅ Renamed `{md5_prefix}` → `{new_name}`. Index hot-reloaded."
            )
        else:
            await ctx.send(f"❌ No entry found with MD5 prefix `{md5_prefix}`.")

    @commands.command(name="scam-test")
    async def scam_test(self, ctx: commands.Context):
        if not await self._has_permission(ctx):
            return

        target_msg = None
        if ctx.message.reference:
            try:
                target_msg = await ctx.channel.fetch_message(
                    ctx.message.reference.message_id
                )
            except Exception:
                pass

        attachments = []
        if target_msg:
            attachments = [
                a for a in target_msg.attachments if _is_allowed_image(a.filename)
            ]
        if not attachments:
            attachments = [
                a for a in ctx.message.attachments if _is_allowed_image(a.filename)
            ]

        if not attachments:
            await ctx.send(
                "❌ Reply to a message containing an image, or attach an image directly."
            )
            return

        status_msg = await ctx.send("⏳ Running detection dry-run...")
        results = []

        for attachment in attachments:
            try:
                image_bytes = await self._download(attachment.url)
            except Exception as e:
                results.append(f"`{attachment.filename}`: ❌ Download failed — {e}")
                continue

            md5_set = set(self._md5_set)
            phash_index = list(self._phash_index)
            orb_index = list(self._orb_index)
            loop = asyncio.get_running_loop()

            try:
                matched, method, details = await loop.run_in_executor(
                    self._executor,
                    _sync_check_image_verbose,
                    image_bytes,
                    md5_set,
                    phash_index,
                    orb_index,
                )
            except Exception as e:
                results.append(f"`{attachment.filename}`: ❌ Detection error — {e}")
                continue

            status = f"🚨 **MATCH** via {method}" if matched else "✅ No match"
            detail_str = "\n  ".join(details)
            results.append(f"`{attachment.filename}`: {status}\n  {detail_str}")

        embed = discord.Embed(
            title="🔍 Scam Detection — Dry Run",
            description="\n\n".join(results),
            color=discord.Color.orange(),
        )
        embed.set_footer(
            text=f"pHash threshold: {PHASH_MATCH_THRESHOLD}/64 | ORB threshold: {ORB_MATCH_THRESHOLD} keypoints"
        )
        await status_msg.edit(content=None, embed=embed)


async def setup(bot):
    await bot.add_cog(ScamDetection(bot))
