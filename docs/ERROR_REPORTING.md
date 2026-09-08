# Error Reporting

## Overview
The bot reports its own failures to a Discord channel instead of relying on console output. The host drops every stdout line beginning with a warning or cross emoji, so a failing cog or a dead background task was previously invisible — that is how #503 and #513 both went undiagnosed for days.

Two paths feed the same channel, `BOT_LOGS_CHANNEL_ID`:

- a **startup report**, once per process, summarising the boot
- **runtime error reports**, one per unhandled exception, rate limited

Both render through `build_error_embed()` so the two cannot drift apart.

---

## Startup report

`report_startup_to_discord()` posts the version, how many features loaded, how many commands synced, and every failure with its exception. Full tracebacks are attached as `startup_failures.txt` so Discord's 2000-character limit cannot truncate the useful line.

Coverage includes the two startup steps that previously failed silently the same way a cog did: `setup_tourney_commands` (which registers 19 of the 72 commands) and `repost_privacy_policy`.

`on_ready` re-fires on every gateway reconnect, so the report is guarded to once per process by `_STARTUP_REPORTED`. A send that never succeeded leaves the flag unset, so a later reconnect retries.

---

## Runtime error reports

Three global handlers replace discord.py's log-only defaults:

| Handler | Covers |
|---|---|
| `on_error` | Unhandled exception inside any listener |
| `on_command_error` | Unhandled prefix command error |
| `on_app_command_error` (`bot.tree.error`) | Unhandled slash command error |

Background tasks are covered separately. `attach_task_error_reporting()` walks every loaded cog and attaches a handler to each `tasks.Loop` it finds, so all 19 are covered without editing each cog. A `tasks.Loop` that raises stops looping and only logs, which means a dead scheduler is otherwise completely silent.

Command errors report the wrapped original rather than the `CommandInvokeError` wrapper, which carries nothing useful (`_unwrap()`).

### What is deliberately not reported

User mistakes are not bugs and must not page anyone:

- `CommandNotFound` — an unknown command
- `CheckFailure` — a failed permission check, on both prefix and slash commands
- `UserInputError` — bad arguments

---

## Severity

Derived from what failed rather than passed in, so every call site classifies the same way (`classify_severity()`).

| Severity | Meaning |
|---|---|
| 🔴 Critical | Something is no longer running — a feature that failed to load, or a task that stopped |
| 🟠 Error | One interaction failed and the bot is otherwise healthy |
| 🟡 Warning | A permission or configuration problem, not a code bug — `Forbidden` and `NotFound` |
| 🟢 Info | Informational |

Warning is separated out because a missing permission and a defect are different jobs to fix, and a `Forbidden` is not a defect.

---

## Plain-English explanations

`explain_error()` maps an exception to a sentence someone who does not read code can act on — `ImportError: libxcb.so.1` says nothing on its own.

`_EXPLANATIONS` is an ordered `isinstance` table, **most specific first**: `Forbidden` and `NotFound` both subclass `HTTPException`, so the generic entry has to come last or it would swallow them. Anything unmatched gets an honest "see the attached traceback" rather than a guess.

---

## Rate limiting

Two axes, because a channel nobody reads is the failure mode this feature exists to prevent:

| Limit | Value | Why |
|---|---|---|
| Dedup window | 300s per fingerprint | A task failing every minute would otherwise post 1,440 messages a day |
| Burst cap | 5 posts per 60s | Caps an unrelated flood of distinct errors |

The fingerprint is `source|ExceptionType|message`, truncated to 200 characters.

The two are recorded at different moments, and the distinction matters:

- **burst budget is spent on the attempt** (`_record_attempt`), so an outage cannot turn every incoming error into another call to a failing endpoint
- **the dedup window opens only once a report has landed** (`_record_delivery`)

Recording the dedup slot before the send meant a report that never posted still counted as reported, dropping the error and silencing its repeats for the full window. `_should_report_error()` is therefore read-only apart from pruning expired entries.

The channel is resolved before the rate limiter is consulted, so an undeliverable post costs nothing.

`_REPORTING_ERROR` stops a failure inside reporting triggering another report.

---

## Notes
- If `BOT_LOGS_CHANNEL_ID` does not resolve to a text channel, `report_error` returns silently. A misconfigured ID means no reports at all, with nothing to say so — verify the channel exists on both servers.
- The channel is staff-only by design: tracebacks and exception strings can contain user IDs and command arguments. This is disclosed in `PRIVACY_POLICY.md`.
- An error post is the intended input to `docs/GITHUB_TICKETS.md`'s reply flow — reply to one, @-mention the bot, and the traceback goes into the issue.

---

## Source Files
`main.py` — configuration, handlers, and reporting live alongside the bot's startup wiring.
