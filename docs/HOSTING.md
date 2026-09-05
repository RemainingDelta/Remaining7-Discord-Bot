# Hosting

This document records where the bot is hosted, the current plan and resource usage, and the history behind the hosting decisions so the reasoning isn't lost or re-litigated later.

---

## Current Host — RamNaym Cloud

The bot runs 24/7 on **RamNaym Cloud** (Nano plan, the lowest paid tier), deployed via GitHub zip download.

| | |
|---|---|
| **Host** | RamNaym Cloud |
| **Plan** | Nano (lowest paid tier) |
| **Plan specs** | 0.10 CPU · 256 MB RAM · 2 GB disk |
| **Cost** | 4 EUR/year (≈ $4.55 USD as of now; paid $4.75) |

### Current usage

Refresh these figures if the plan changes or load moves materially — they exist for capacity planning.

| Resource | Usage |
|---|---|
| vCPU load | 0.5% |
| Memory | 126.6 / 256.0 MB |
| Project storage | 2.1 MB / 2.00 GB |

At current load the Nano plan has comfortable headroom (memory is the tightest resource at roughly 50% used).

---

## Hosting History

### Previous host — Pella

The bot was previously hosted on **Pella** (Nano plan):

| | |
|---|---|
| **Host** | Pella |
| **Plan** | Nano |
| **Plan specs** | 0.1 CPU · 256 MB RAM |
| **Cost** | $3/year |

### Why we switched

Pella suffered repeated outages, and communication around those incidents was poor — there was little transparency from Pella when things went down. The last straw was the server stopping unannounced **during a live tournament**, which required a manual restart while an event was in progress.

We moved to **RamNaym Cloud** for reliability, and it has been consistent since the switch.

### Cost trade-off

RamNaym's Nano plan (4 EUR/year, ≈ $4.55 USD as of now; paid $4.75) is roughly 1.5x the cost of Pella's ($3/year). The price difference was considered worth it given the reliability gain during live events, and it remains a very low overall cost.

---

## Maintenance Notes

- If the plan (host, tier, specs, or price) changes, update both this file and the **Hosting** section of the [`README`](../README.md).
- Refresh the **Current usage** figures periodically for capacity planning, especially if memory usage starts approaching the 256 MB ceiling.
- **The console logs are not a reliable record.** Lines beginning with `⚠️` or `❌` do not appear in the retrievable output — confirmed across three separate deploys, where the `✅` and `🚀` lines either side of them came through and the warning lines did not. Anything that must be seen goes to `BOT_LOGS_CHANNEL_ID` in Discord; the console is a secondary copy only. Startup failures, command errors, listener errors and background task failures all report there as embeds, colour-coded by severity: 🔴 Critical (something stopped running), 🟠 Error (one interaction failed), 🟡 Warning (a permission or config problem rather than a bug). This is why #503 and #513 both went undiagnosed for days.
- **The dependency panel is not just `requirements.txt`.** A scanner reads the source and adds packages it infers, which is how the desktop `opencv-python` kept reappearing in #513 despite never being in the manifest. Entries deleted by hand come back on the next deploy. Check the panel against `requirements.txt` when a dependency behaves unexpectedly.
