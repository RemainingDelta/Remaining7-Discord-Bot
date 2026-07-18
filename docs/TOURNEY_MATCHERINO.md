# Tourney Matcherino Integration

## Overview
The Matcherino integration connects the bot to live Brawl Stars tournament brackets hosted on matcherino.com. It scrapes the Matcherino **private API** (not a public-facing endpoint) to pull real-time bracket state: team rosters, match scores, bracket progression, and placements. All scraping is wrapped in a 60-second `requests_cache` layer so repeated calls within the same minute hit local cache instead of the live API.

---

## API Endpoint

All bracket data comes from a single undocumented Matcherino API:

```
GET https://api.matcherino.com/__api/brackets?bountyId={id}&id=0&isAdmin=false
```

The `bountyId` is the numeric tournament ID extracted from the Matcherino URL with a regex:

```python
id_match = re.search(r"tournaments/(\d+)", url)
bounty_id = id_match.group(1)
```

The response contains a `body[0]` object with two key lists:
- `matches` — all bracket slots, including BYE placeholders
- `entrants` — all registered teams with their members

---

## HTTP Session Setup

To avoid being blocked by Matcherino's anti-bot detection, the bot mimics a real Chrome browser:

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://matcherino.com/",
    "Origin": "https://matcherino.com",
}
session = requests_cache.CachedSession("matcherino_cache", expire_after=timedelta(seconds=60))
session.headers.update(HEADERS)
```

The `CachedSession` writes to a local SQLite file (`matcherino_cache.sqlite`) and serves cached responses for 60 seconds before hitting the live API again.

---

## Entrant Map Construction

After fetching the API, the bot builds a lookup dictionary of `entrant_id → {name, players}`:

```python
entrant_map = {0: {"name": "TBD", "players": []}, 1: {"name": "BYE", "players": []}}
for e in raw_entrants:
    e_id = e.get("id")
    name = e.get("name") or (e.get("team") and e["team"].get("name")) or "Unknown Team"
    players = [m.get("displayName") for m in e.get("team", {}).get("members", [])]
    entrant_map[e_id] = {"name": name, "players": players}
```

- ID `0` = TBD (slot not yet filled)
- ID `1` = BYE (automatic advancement)
- Any other ID = real team

Player names come from `team.members[].displayName` (their Matcherino usernames). Fallback: `e.get("players", [])` for older API versions or solo players.

---

## Visual Match Number Mapping

The Matcherino API uses internal `matchNum` values that don't match what staff see on the bracket UI. The bot reconstructs visual numbering by:

1. Filtering out BYE matches (those where either `entrantA.entrantId == 1` or `entrantB.entrantId == 1`)
2. Sorting the remaining matches by `matchNum`
3. Assigning sequential visual numbers starting from 1

```python
visible_matches = [m for m in raw_matches if e_a != 1 and e_b != 1]
visible_matches.sort(key=lambda x: x.get("matchNum", 9999))
for i, m in enumerate(visible_matches, start=1):
    m["visualNum"] = i
    visual_match_map[i] = m
```

A reverse map `raw_to_visual` allows converting back from internal API `matchNum` to the visual number shown to staff.

---

## TBD Chain Resolution

When a match slot is TBD (team not yet known), the bot recursively traces `entrantSources` to show which upstream match will produce the team:

```python
def resolve_name(entrant_dict, source_entry, depth=0):
    name = get_team_info(entrant_dict)["name"]
    if name not in ("TBD", "BYE"):
        return name  # known team — done
    if not source_entry or depth > 1:
        return "TBD"  # give up at depth 2
    raw_src = source_entry.get("matchNum")
    v_src = raw_to_visual.get(raw_src, raw_src)
    src = visual_match_map.get(v_src)
    # Recurse into the upstream match
    a = resolve_name(src.get("entrantA"), ...)
    b = resolve_name(src.get("entrantB"), ...)
    return f"Waiting on Match #{v_src} ({a} vs {b})"
```

The recursion caps at depth 2 to avoid stack overflows in deep brackets.

---

## Match Timing

Each match has two timestamp fields:
- `statusAt` — updated whenever the match status changes (team paired, score updated, match closed)
- `createdAt` — when the structural bracket slot was created

The bot prefers `statusAt` as a proxy for "time since last activity":

```python
time_str = current_match.get("statusAt") or current_match.get("createdAt")
dt = datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
elapsed_seconds = int(time.time()) - int(dt.timestamp())
```

Elapsed time is displayed as `Xm Ys` or `Xh Ym Ys`.

---

## Fuzzy Team Name Matching

When a ticket is opened, the member types their team name in a modal. This typed name may not exactly match the bracket (spaces vs. no spaces, typos, casing). The bot uses `difflib.SequenceMatcher` to compare:

```python
TEAM_NAME_SIMILARITY_THRESHOLD = 0.60

def _normalize_for_compare(s):
    return " ".join(s.lower().strip().split())  # lowercase, collapse whitespace

ratio = difflib.SequenceMatcher(None, topic_name, bracket_name).ratio()
matches = ratio >= TEAM_NAME_SIMILARITY_THRESHOLD
```

- **ratio ≥ 0.60** → accept (minor typos pass, e.g. "FireBoys" vs "Fire Boys")
- **ratio < 0.60** → flag mismatch warning to staff

TBD and BYE slots are excluded from matching.

---

## Per-Tournament Team Cache

To avoid re-fetching the full entrant list on every ticket refresh, the bot caches the team roster per `bounty_id`:

```python
_bracket_teams_cache: dict[str, list[dict]] = {}

if bounty_id not in _bracket_teams_cache:
    _bracket_teams_cache[bounty_id] = [
        {"name": name, "entrant_id": eid}
        for eid, name in entrant_map.items()
        if eid > 1 and name.upper() not in ("TBD", "BYE", "UNKNOWN TEAM")
    ]
```

This cache is cleared at the end of a tournament session via `clear_bracket_teams_cache()`, which is called by `!endtourney`.

---

## Team Name Fallback (No Match Number)

If a ticket topic has no `bracket:` number, the bot falls back to `find_match_by_team_name()`:

1. Loads the team cache for the bracket
2. Fuzzy-matches the topic team name against every team in the cache
3. Finds all matches that team participates in
4. Prefers the latest non-closed match (active match takes priority over finished ones)
5. Returns the resolved visual match number

If a match number is successfully resolved this way, the bot **persists it back into the channel topic** (`bracket:{num}`) so future refreshes skip the lookup:

```python
updated_topic = re.sub(r"bracket:[^|]*", f"bracket:{match_num}", channel.topic)
await channel.edit(topic=updated_topic)
```

---

## Match History Construction

For each team in the current match, the bot scans all other bracket matches to build a history. For each past match:
- If the team appears and the opponent is known → append `"Match N: TeamA vs TeamB (score - score)"`
- If the opponent is TBD → resolve the TBD chain and append the upstream context

---

## Bracket Progress Scanning (`fetch_bracket_progress`)

Used by the progress dashboard. Scans the entire bracket to produce:

| Field | Meaning |
|-------|---------|
| `total` | Total real (non-BYE) matches |
| `closed` | Matches with status `closed/completed/done` |
| `completion_pct` | `closed / total * 100` |
| `dominant_round` | Highest round currently seeing active play |
| `max_round` | Total number of rounds in the bracket |
| `bottlenecks` | Active matches lagging behind the dominant round |
| `winner_team` | Team that won the final round match |
| `active_matches` | All matches where both teams are known and match is not closed |

**Round normalization**: Matcherino gives first-round BYEs when participant count is ≤ half the bracket size. After filtering BYEs, `resolved_round` may start at 2+. The bot normalizes: `resolved_round -= (min_round - 1)` so Round 1 is always the first real round.

**Bottleneck detection**: Any active match in a round below the `dominant_round` is flagged as a bottleneck (blocking the rest of the bracket from advancing).

---

## Payout Report (`fetch_payout_report`)

Scrapes the tournament HTML page for the name and prize pool, then uses the API to determine Top 4 placement:

- **HTML scrape**: Finds `div.title.mr-08` (or `div.title-container`) for name; `div.prize-pool-amt span` for prize pool
- **Final match determination**: `visible_matches[-2]` = Grand Final (second-to-last created match in Matcherino's sequence), `visible_matches[-1]` = Bronze Match
- **Placement split**: 1st = 50%, 2nd = 25%, 3rd = 15%, 4th = 10% of total prize pool

---

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `TEAM_NAME_SIMILARITY_THRESHOLD` | `0.60` | Minimum fuzzy ratio to accept a team name match |
| `expire_after` | `60s` | `requests_cache` TTL |
| API timeout | `10s` | Per-request timeout |
| BYE entrant ID | `1` | Matches with this ID are filtered out as invisible |
| TBD entrant ID | `0` | Unfilled bracket slots |

---

## Source File
`features/tourney/matcherino.py`
