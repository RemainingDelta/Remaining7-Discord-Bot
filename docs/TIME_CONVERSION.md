# Time Conversion

## Overview
`/convert-time` converts a date and time from any supported timezone into all six Discord timestamp formats. This makes it easy to share event times that automatically render in each viewer's local timezone inside Discord.

---

## Command: `/convert-time <date> <time> <timezone>`

**Parameters**:
- `date` — e.g. `June 21, 2026` or `2026-06-21`
- `time` — e.g. `3:00 PM` or `15:00`
- `timezone` — alias (e.g. `EST`) or full IANA name (e.g. `America/New_York`)

**Flow**:
1. Looks up `timezone` in `TIMEZONE_ALIASES` dict; if not found, treats it as a raw IANA timezone name
2. Parses date + time string into a `datetime` object
3. Localizes to the provided timezone using `pytz` or `zoneinfo`
4. Converts to UTC and gets the Unix timestamp
5. Returns an embed with all Discord timestamp format strings

---

## Discord Timestamp Formats

All six formats output as copyable text the user can paste into Discord:

| Format Code | Example Output |
|-------------|---------------|
| `<t:X:t>` | Short time: `3:00 PM` |
| `<t:X:T>` | Long time: `3:00:00 PM` |
| `<t:X:d>` | Short date: `06/21/2026` |
| `<t:X:D>` | Long date: `June 21, 2026` |
| `<t:X:f>` | Short datetime: `June 21, 2026 3:00 PM` |
| `<t:X:F>` | Long datetime: `Saturday, June 21, 2026 3:00 PM` |
| `<t:X:R>` | Relative: `in 2 hours` |

Each is shown as both the raw markup (`<t:...>`) and a preview of how it renders.

---

## TIMEZONE_ALIASES

A dictionary in `features/general.py` mapping common abbreviations to IANA timezone names:

```python
TIMEZONE_ALIASES = {
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "PT":  "America/Los_Angeles",
    "ET":  "America/New_York",
    "CT":  "America/Chicago",
    "MT":  "America/Denver",
    "GMT": "UTC",
    "UTC": "UTC",
    "BST": "Europe/London",
    "IST": "Asia/Kolkata",
    "AEST": "Australia/Sydney",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "CET": "Europe/Paris",
    # ... and more
}
```

Any IANA name not in this dict can also be used directly (e.g. `America/Chicago`, `Asia/Dubai`).

---

## Tests

`tests/test_convert_time.py` covers:
- All alias lookups
- 12h and 24h time parsing
- Correct Unix timestamp output for known input
- Edge cases (midnight, DST transitions)

---

## Source File
`features/general.py` — `/convert-time` command and `TIMEZONE_ALIASES`
