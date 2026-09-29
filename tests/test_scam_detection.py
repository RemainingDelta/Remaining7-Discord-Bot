"""Tests for features/scam_detection.py (issue #513).

The host's dependency scanner reads a literal `import cv2` and installs the
desktop opencv-python package, which needs X11 (libxcb.so.1) that a headless
container does not have. It overwrites the headless build's files, so the
import fails and the whole cog stops loading. Deleting the package from the
host's panel does not stick — it is re-added on the next deploy.
"""

import ast
import pathlib

import pytest

FEATURES = pathlib.Path(__file__).resolve().parent.parent / "features"


def _python_files():
    return sorted(FEATURES.rglob("*.py"))


def test_no_module_imports_cv2_literally():
    """A literal `import cv2` re-triggers the host's wrong-package guess (#513).

    Tidying `cv2 = import_module("cv2")` back into `import cv2` looks harmless
    and breaks scam detection on the next deploy, with the failure invisible in
    the host's logs. Import cv2 by name instead.
    """
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] == "cv2" for alias in node.names):
                    offenders.append(f"{path.name}:{node.lineno} import cv2")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] == "cv2":
                    offenders.append(f"{path.name}:{node.lineno} from cv2 import ...")

    assert offenders == [], (
        "cv2 must be imported by name, not with a literal import statement: "
        + ", ".join(offenders)
    )


def test_scam_detection_still_exposes_cv2_at_module_level():
    """The 11 call sites use a module-level `cv2`, so the binding must survive."""
    pytest.importorskip("cv2")
    import features.scam_detection as scam_detection

    assert scam_detection.cv2.__name__ == "cv2"
    assert callable(scam_detection.cv2.ORB_create)


# --- Management commands as slash / message commands (#568) ---

from datetime import timedelta  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import discord  # noqa: E402
from discord import app_commands  # noqa: E402

from features.scam_detection import ScamDetection  # noqa: E402
from features.security import Security  # noqa: E402


@pytest.fixture
async def scam_cog():
    bot = MagicMock()
    security = MagicMock()
    security.has_security_permission = AsyncMock(return_value=True)
    bot.cogs = {"Security": security}
    # Loop.__get__ hands each instance its own copy, so patch the class method.
    with patch("discord.ext.tasks.Loop.start"):
        cog = ScamDetection(bot)
    cog._reload_index = AsyncMock()
    cog._download = AsyncMock(return_value=b"image-bytes")
    yield cog
    cog._executor.shutdown(wait=False)


@pytest.fixture
def db():
    with (
        patch("features.scam_detection.add_scam_image", new=AsyncMock()) as add,
        patch(
            "features.scam_detection.remove_scam_image", new=AsyncMock(return_value=0)
        ) as remove,
        patch(
            "features.scam_detection.rename_scam_image",
            new=AsyncMock(return_value=False),
        ) as rename,
        patch(
            "features.scam_detection.get_scam_images", new=AsyncMock(return_value=[])
        ) as get,
    ):
        yield MagicMock(add=add, remove=remove, rename=rename, get=get)


def deny(cog):
    cog.bot.cogs["Security"].has_security_permission.return_value = False


def make_image(filename="scam.png", size=1024):
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.size = size
    att.url = f"https://cdn.example/{filename}"
    return att


def make_target(*attachments):
    msg = MagicMock(spec=discord.Message)
    msg.attachments = list(attachments)
    return msg


def responses(interaction):
    """Every (args, kwargs) the command sent back to the invoker."""
    calls = list(interaction.response.send_message.call_args_list)
    calls += list(interaction.followup.send.call_args_list)
    return calls


def response_text(interaction):
    parts = []
    for call in responses(interaction):
        if call.args:
            parts.append(str(call.args[0]))
        if call.kwargs.get("content"):
            parts.append(call.kwargs["content"])
        embed = call.kwargs.get("embed")
        if embed is not None:
            parts.append(f"{embed.title}\n{embed.description}")
    return "\n".join(parts)


def all_ephemeral(interaction):
    calls = responses(interaction)
    return bool(calls) and all(c.kwargs.get("ephemeral") for c in calls)


# permissions


async def test_every_scam_command_denies_non_moderators(scam_cog, db, mock_interaction):
    deny(scam_cog)
    image = make_image()

    await scam_cog.scam_add_message(mock_interaction, make_target(image))
    await scam_cog.scam_add.callback(scam_cog, mock_interaction, image)
    await scam_cog.scam_test.callback(scam_cog, mock_interaction, image)
    await scam_cog.scam_remove.callback(scam_cog, mock_interaction, "abcd1234")
    await scam_cog.scam_rename.callback(scam_cog, mock_interaction, "abcd", "x")
    await scam_cog.scam_list.callback(scam_cog, mock_interaction)

    assert all_ephemeral(mock_interaction)
    assert len(responses(mock_interaction)) == 6
    db.add.assert_not_awaited()
    db.remove.assert_not_awaited()
    db.rename.assert_not_awaited()
    scam_cog._download.assert_not_awaited()


# "Add to Scam Blacklist" message command: dry-run preview, then Add / Cancel


def verbose_result(matched=False):
    if matched:
        return (True, "MD5", ["MD5 exact match: `abcd1234`"])
    return (False, None, ["pHash closest: `x.png` distance **30**/64"])


def make_button_interaction(user_id=987654321):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


async def preview(scam_cog, interaction, target, matched=False):
    """Run the message command and return the preview's Add/Cancel view."""
    with patch(
        "features.scam_detection._sync_check_image_verbose",
        return_value=verbose_result(matched),
    ):
        await scam_cog.scam_add_message(interaction, target)
    return interaction.followup.send.call_args.kwargs["view"]


async def press_add(view):
    interaction = make_button_interaction()
    await view.add.callback(interaction)
    return interaction


def edited_text(interaction):
    return str(interaction.edit_original_response.call_args.kwargs.get("content"))


async def test_add_message_preview_shows_results_and_stores_nothing(
    scam_cog, db, mock_interaction
):
    target = make_target(make_image("a.png"), make_image("b.jpg"))

    view = await preview(scam_cog, mock_interaction, target, matched=True)

    db.add.assert_not_awaited()
    scam_cog._reload_index.assert_not_awaited()
    text = response_text(mock_interaction)
    assert "a.png" in text and "b.jpg" in text
    assert "MATCH" in text
    labels = [c.label for c in view.children if isinstance(c, discord.ui.Button)]
    assert labels == ["Add", "Cancel"]
    assert all_ephemeral(mock_interaction)


async def test_add_message_stores_each_allowed_image_and_reloads(
    scam_cog, db, mock_interaction
):
    target = make_target(make_image("a.png"), make_image("b.jpg"))

    await press_add(await preview(scam_cog, mock_interaction, target))

    stored = [c.args[0] for c in db.add.call_args_list]
    assert stored == ["a.png", "b.jpg"]
    scam_cog._reload_index.assert_awaited_once()


async def test_cancel_stores_nothing(scam_cog, db, mock_interaction):
    view = await preview(scam_cog, mock_interaction, make_target(make_image()))
    interaction = make_button_interaction()

    await view.cancel.callback(interaction)

    db.add.assert_not_awaited()
    scam_cog._reload_index.assert_not_awaited()


async def test_only_the_invoker_can_press_add_or_cancel(scam_cog, db, mock_interaction):
    view = await preview(scam_cog, mock_interaction, make_target(make_image()))

    assert await view.interaction_check(make_button_interaction()) is True
    other = make_button_interaction(user_id=1)
    assert await view.interaction_check(other) is False
    assert other.response.send_message.call_args.kwargs["ephemeral"]


async def test_add_message_skips_non_image_attachments(scam_cog, db, mock_interaction):
    target = make_target(make_image("notes.txt"), make_image("a.png"))

    await press_add(await preview(scam_cog, mock_interaction, target))

    assert [c.args[0] for c in db.add.call_args_list] == ["a.png"]


async def test_add_message_without_images_errors(scam_cog, db, mock_interaction):
    await scam_cog.scam_add_message(
        mock_interaction, make_target(make_image("notes.txt"))
    )

    assert all_ephemeral(mock_interaction)
    db.add.assert_not_awaited()
    scam_cog._reload_index.assert_not_awaited()


async def test_add_message_rejects_oversized_image_but_keeps_others(
    scam_cog, db, mock_interaction
):
    big = make_image("big.png", size=16 * 1024 * 1024)
    target = make_target(big, make_image("ok.png"))

    added = await press_add(await preview(scam_cog, mock_interaction, target))

    assert [c.args[0] for c in db.add.call_args_list] == ["ok.png"]
    assert "big.png" in edited_text(added)


async def test_add_message_accepts_image_at_exact_size_limit(
    scam_cog, db, mock_interaction
):
    edge = make_image("edge.png", size=15 * 1024 * 1024)

    await press_add(await preview(scam_cog, mock_interaction, make_target(edge)))

    assert [c.args[0] for c in db.add.call_args_list] == ["edge.png"]


# /scam-add


async def test_scam_add_slash_stores_uploaded_image(scam_cog, db, mock_interaction):
    await scam_cog.scam_add.callback(scam_cog, mock_interaction, make_image("u.png"))

    assert [c.args[0] for c in db.add.call_args_list] == ["u.png"]
    scam_cog._reload_index.assert_awaited_once()


async def test_scam_add_slash_rejects_non_image(scam_cog, db, mock_interaction):
    await scam_cog.scam_add.callback(scam_cog, mock_interaction, make_image("doc.pdf"))

    assert all_ephemeral(mock_interaction)
    db.add.assert_not_awaited()


# /scam-remove, /scam-rename, /scam-list


async def test_scam_remove_reports_removed_and_unknown_prefixes(
    scam_cog, db, mock_interaction
):
    db.remove.side_effect = lambda prefix: 1 if prefix == "aaaa" else 0

    await scam_cog.scam_remove.callback(scam_cog, mock_interaction, "aaaa zzzz")

    assert [c.args[0] for c in db.remove.call_args_list] == ["aaaa", "zzzz"]
    text = response_text(mock_interaction)
    assert "aaaa" in text and "zzzz" in text
    scam_cog._reload_index.assert_awaited_once()


async def test_scam_remove_with_only_unknown_prefixes_does_not_reload(
    scam_cog, db, mock_interaction
):
    await scam_cog.scam_remove.callback(scam_cog, mock_interaction, "zzzz")

    scam_cog._reload_index.assert_not_awaited()


async def test_scam_rename_unknown_prefix_reports_not_found(
    scam_cog, db, mock_interaction
):
    await scam_cog.scam_rename.callback(scam_cog, mock_interaction, "zzzz", "name")

    assert "No entry found" in response_text(mock_interaction)
    scam_cog._reload_index.assert_not_awaited()


async def test_scam_rename_known_prefix_renames_and_reloads(
    scam_cog, db, mock_interaction
):
    db.rename.return_value = True

    await scam_cog.scam_rename.callback(
        scam_cog, mock_interaction, "aaaa", "Nitro scam"
    )

    db.rename.assert_awaited_once_with("aaaa", "Nitro scam")
    scam_cog._reload_index.assert_awaited_once()


async def test_scam_list_shows_entries(scam_cog, db, mock_interaction):
    db.get.return_value = [{"filename": "nitro.png", "md5": "abcdef1234567890"}]

    await scam_cog.scam_list.callback(scam_cog, mock_interaction)

    text = response_text(mock_interaction)
    assert "nitro.png" in text and "abcdef12" in text


# /scam-test


async def test_scam_test_reports_match_for_blacklisted_image(
    scam_cog, db, mock_interaction
):
    with patch(
        "features.scam_detection._sync_check_image_verbose",
        return_value=(True, "MD5", ["MD5 exact match"]),
    ):
        await scam_cog.scam_test.callback(scam_cog, mock_interaction, make_image())

    assert "MATCH" in response_text(mock_interaction)
    db.add.assert_not_awaited()


async def test_scam_test_reports_no_match_for_clean_image(
    scam_cog, db, mock_interaction
):
    with patch(
        "features.scam_detection._sync_check_image_verbose",
        return_value=(False, None, ["pHash: no entries in blacklist"]),
    ):
        await scam_cog.scam_test.callback(scam_cog, mock_interaction, make_image())

    assert "No match" in response_text(mock_interaction)


# the scanner no longer exempts "!scam..." messages


async def test_scanner_checks_images_in_messages_starting_with_scam(
    scam_cog, guild_message
):
    message = guild_message(channel_id=1)
    message.content = "!scam-add look at this"
    message.created_at = discord.utils.utcnow() - timedelta(seconds=1)
    message.attachments = [make_image("nitro.png")]
    scam_cog._download.side_effect = RuntimeError("stop after download")

    await scam_cog.on_message(message)

    scam_cog._download.assert_awaited_once_with("https://cdn.example/nitro.png")


# registration


def test_no_scam_prefix_commands_are_registered(scam_cog):
    names = {c.name for c in scam_cog.get_commands()}
    assert not {n for n in names if n.startswith("scam")}


def test_scam_slash_commands_are_registered(scam_cog):
    names = {c.name for c in scam_cog.get_app_commands()}
    assert {
        "scam-add",
        "scam-test",
        "scam-remove",
        "scam-rename",
        "scam-list",
    } <= names


async def test_cog_load_registers_add_to_blacklist_message_command(scam_cog):
    with (
        patch("features.scam_detection.aiohttp.ClientSession"),
        patch("features.scam_detection.ensure_scam_lock_ttl_index", new=AsyncMock()),
    ):
        await scam_cog.cog_load()

    menu = scam_cog.bot.tree.add_command.call_args.args[0]
    assert isinstance(menu, app_commands.ContextMenu)
    assert menu.name == "Add to Scam Blacklist"
    assert menu.type is discord.AppCommandType.message


async def test_cog_unload_removes_add_to_blacklist_message_command(scam_cog):
    scam_cog._session = MagicMock()
    scam_cog._session.close = AsyncMock()
    with patch("discord.ext.tasks.Loop.cancel"):
        await scam_cog.cog_unload()

    scam_cog.bot.tree.remove_command.assert_called_once_with(
        "Add to Scam Blacklist", type=discord.AppCommandType.message
    )


def test_hacked_prefix_command_is_removed_and_slash_kept():
    security = Security(MagicMock())
    assert "hacked" not in {c.name for c in security.get_commands()}
    assert "hacked" in {c.name for c in security.get_app_commands()}


# --- "Flag as Hacked" message command (replaces replying with !hacked) ---


def make_security(allowed=True):
    bot = MagicMock()
    bot.tree = MagicMock()
    security = Security(bot)
    security.has_security_permission = AsyncMock(return_value=allowed)
    security._execute_hacked_action = AsyncMock(
        return_value=discord.Embed(title="done")
    )
    security._send_security_logs = AsyncMock()
    return security


def make_flag_target(author):
    msg = MagicMock(spec=discord.Message)
    msg.author = author
    return msg


def flag_interaction():
    interaction = make_button_interaction()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.fetch_member = AsyncMock()
    return interaction


async def test_flag_as_hacked_denies_non_moderators():
    security = make_security(allowed=False)
    interaction = flag_interaction()

    await security.flag_hacked_message(
        interaction, make_flag_target(MagicMock(spec=discord.Member))
    )

    security._execute_hacked_action.assert_not_awaited()
    assert interaction.response.send_message.call_args.kwargs["ephemeral"]


async def test_flag_as_hacked_targets_the_message_author():
    security = make_security()
    interaction = flag_interaction()
    author = MagicMock(spec=discord.Member)

    await security.flag_hacked_message(interaction, make_flag_target(author))

    security._execute_hacked_action.assert_awaited_once_with(
        interaction.guild, author, interaction.user
    )
    security._send_security_logs.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs["embed"].title == "done"


async def test_flag_as_hacked_resolves_a_user_object_to_a_member():
    security = make_security()
    interaction = flag_interaction()
    member = MagicMock(spec=discord.Member)
    interaction.guild.fetch_member.return_value = member
    user = MagicMock(spec=discord.User)
    user.id = 42

    await security.flag_hacked_message(interaction, make_flag_target(user))

    interaction.guild.fetch_member.assert_awaited_once_with(42)
    assert security._execute_hacked_action.await_args.args[1] is member


async def test_flag_as_hacked_still_works_on_a_user_who_left():
    """#298: the account is often gone by the time a mod acts."""
    security = make_security()
    interaction = flag_interaction()
    interaction.guild.fetch_member.side_effect = discord.NotFound(
        MagicMock(status=404), "gone"
    )
    user = MagicMock(spec=discord.User)
    user.id = 42

    await security.flag_hacked_message(interaction, make_flag_target(user))

    assert security._execute_hacked_action.await_args.args[1] is user
    security._send_security_logs.assert_awaited_once()


async def test_cog_load_registers_flag_as_hacked_message_command():
    security = make_security()

    await security.cog_load()

    menu = security.bot.tree.add_command.call_args.args[0]
    assert isinstance(menu, app_commands.ContextMenu)
    assert menu.name == "Flag as Hacked"
    assert menu.type is discord.AppCommandType.message
    assert menu.default_permissions is not None, "hidden from regular members"


async def test_cog_unload_removes_flag_as_hacked_message_command():
    security = make_security()

    await security.cog_unload()

    security.bot.tree.remove_command.assert_called_once_with(
        "Flag as Hacked", type=discord.AppCommandType.message
    )
