import difflib
import re
import time
from bs4 import BeautifulSoup
import requests
import requests_cache
from datetime import timedelta, datetime, timezone

# Mimic a real browser session to avoid blocks/disconnections
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://matcherino.com/",
    "Origin": "https://matcherino.com",
}

# HEADERS is tuned for the JSON API; an HTML page needs an HTML Accept or the
# server may negotiate a non-HTML response and the selectors silently miss.
PAGE_HEADERS = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Initialize a cached session
session = requests_cache.CachedSession(
    "matcherino_cache", expire_after=timedelta(seconds=60)
)
session.headers.update(HEADERS)

# Fuzzy match: ratio >= this → accept (minor typos). Below → team name mismatch warning.
TEAM_NAME_SIMILARITY_THRESHOLD = 0.60

# Per-tourney cache of bracket team names (teams don't change mid-tourney).
# Keyed by bounty_id → list of {"name": str, "entrant_id": int}.
_bracket_teams_cache: dict[str, list[dict]] = {}


def clear_bracket_teams_cache():
    """Clear cached team lists. Call when a tourney session ends."""
    _bracket_teams_cache.clear()


def _normalize_for_compare(s: str) -> str:
    """Normalize string for similarity: strip, lower, collapse whitespace."""
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.lower().strip().split())


def _team_name_matches(
    topic_team: str,
    team_a_name: str,
    team_b_name: str,
) -> tuple[bool, float, str | None]:
    """
    Compare topic team name to bracket team names using SequenceMatcher.
    Returns (matches_either, best_ratio, best_match_team_name).
    Minor typos (e.g. 'Fire Boys' vs 'FireBoys') pass.
    """
    topic_n = _normalize_for_compare(topic_team)
    if not topic_n:
        return True, 1.0, None  # No topic name to check

    a_n = _normalize_for_compare(team_a_name)
    b_n = _normalize_for_compare(team_b_name)
    # Skip mismatch check when bracket has no real team names
    if a_n in ("tbd", "bye") and b_n in ("tbd", "bye"):
        return True, 1.0, None

    ratio_a = (
        difflib.SequenceMatcher(None, topic_n, a_n).ratio()
        if a_n not in ("tbd", "bye")
        else 0.0
    )
    ratio_b = (
        difflib.SequenceMatcher(None, topic_n, b_n).ratio()
        if b_n not in ("tbd", "bye")
        else 0.0
    )

    best_ratio = 0.0
    best_name: str | None = None

    if a_n not in ("tbd", "bye"):
        best_ratio = ratio_a
        best_name = team_a_name
    if b_n not in ("tbd", "bye") and ratio_b > best_ratio:
        best_ratio = ratio_b
        best_name = team_b_name

    matches = best_ratio >= TEAM_NAME_SIMILARITY_THRESHOLD
    return matches, best_ratio, best_name


def find_match_by_team_name(url: str, topic_team_name: str) -> dict:
    """
    Fallback when no valid match number is provided: fuzzy-match the team
    name against all bracket entrants, then locate their current match.

    Returns dict with:
      - status: "found" | "no_match"  (or "error" key on failure)
      - match_number: visual match number (if found)
      - matched_team: bracket team name (if found)
      - ratio: similarity ratio (if found)
    """
    id_match = re.search(r"tournaments/(\d+)", url)
    if not id_match:
        return {"error": "Invalid Matcherino URL."}

    topic_n = _normalize_for_compare(topic_team_name)
    if not topic_n:
        return {"error": "No team name provided for lookup."}

    bounty_id = id_match.group(1)
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={bounty_id}&id=0&isAdmin=false"

    try:
        response = session.get(api_url, timeout=10)
        if response.status_code != 200:
            return {"error": f"Failed to fetch API. Status: {response.status_code}"}
        data = response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Matcherino connection failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Parsing failed: {str(e)}"}

    try:
        bracket_data = data["body"][0]
        raw_matches = bracket_data.get("matches", [])
        raw_entrants = bracket_data.get("entrants", [])

        if not raw_matches:
            return {"error": "Bracket is empty."}

        # Build entrant map (id → name)
        entrant_map: dict[int, str] = {}
        for e in raw_entrants:
            e_id = e.get("id")
            name = (
                e.get("name")
                or (e.get("team") and e["team"].get("name"))
                or "Unknown Team"
            )
            entrant_map[e_id] = name

        # Cache team list per tournament (teams don't change mid-tourney)
        if bounty_id not in _bracket_teams_cache:
            _bracket_teams_cache[bounty_id] = [
                {"name": name, "entrant_id": eid}
                for eid, name in entrant_map.items()
                if eid > 1 and name.upper() not in ("TBD", "BYE", "UNKNOWN TEAM")
            ]

        # Fuzzy match against cached teams
        best_ratio = 0.0
        best_team_name: str | None = None
        best_entrant_id: int | None = None
        for team in _bracket_teams_cache[bounty_id]:
            team_n = _normalize_for_compare(team["name"])
            ratio = difflib.SequenceMatcher(None, topic_n, team_n).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_team_name = team["name"]
                best_entrant_id = team["entrant_id"]

        if best_ratio < TEAM_NAME_SIMILARITY_THRESHOLD:
            return {
                "status": "no_match",
                "best_ratio": best_ratio,
                "best_team": best_team_name,
            }

        # Team found — locate their current visual match number
        visible_matches = []
        for m in raw_matches:
            e_a = m.get("entrantA", {}).get("entrantId", 0)
            e_b = m.get("entrantB", {}).get("entrantId", 0)
            if e_a != 1 and e_b != 1:
                visible_matches.append(m)

        visible_matches.sort(key=lambda x: x.get("matchNum", 9999))

        # Collect all matches this team participates in
        team_matches: list[tuple[int, dict]] = []
        for i, m in enumerate(visible_matches, start=1):
            e_a = m.get("entrantA", {}).get("entrantId", 0)
            e_b = m.get("entrantB", {}).get("entrantId", 0)
            if best_entrant_id in (e_a, e_b):
                team_matches.append((i, m))

        if not team_matches:
            return {
                "status": "no_match",
                "best_ratio": best_ratio,
                "best_team": best_team_name,
            }

        # Prefer the latest non-closed match; fall back to last match overall
        finished = ("closed", "completed", "complete", "done")
        latest_active = None
        for visual_num, m in team_matches:
            if str(m.get("status", "")).lower() not in finished:
                latest_active = (visual_num, m)

        resolved_visual_num = latest_active[0] if latest_active else team_matches[-1][0]

        return {
            "status": "found",
            "match_number": resolved_visual_num,
            "matched_team": best_team_name,
            "ratio": best_ratio,
        }

    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


def fetch_ticket_context(
    url: str, target_match_number: int, topic_team_name: str | None = None
) -> dict:
    """
    Parses a Matcherino URL, hits their hidden API for live bracket data,
    maps entrant IDs to team names, calculates the VISUAL match numbers,
    and compiles historical bracket runs and elapsed time.
    """
    id_match = re.search(r"tournaments/(\d+)", url)
    if not id_match:
        return {"error": "Invalid Matcherino URL. Could not find tournament ID."}

    bounty_id = id_match.group(1)
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={bounty_id}&id=0&isAdmin=false"

    try:
        response = session.get(api_url, timeout=10)
        if response.status_code != 200:
            return {"error": f"Failed to fetch API. Status: {response.status_code}"}
        data = response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Matcherino connection failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Parsing failed: {str(e)}"}

    try:
        bracket_data = data["body"][0]
        raw_matches = bracket_data.get("matches", [])
        raw_entrants = bracket_data.get("entrants", [])

        if not raw_matches:
            return {"error": "Bracket is empty."}

        # Build lookup dictionary for Entrant IDs -> Team Names
        entrant_map = {
            0: {"name": "TBD", "players": []},
            1: {"name": "BYE", "players": []},
        }
        for e in raw_entrants:
            e_id = e.get("id")
            name = (
                e.get("name")
                or (e.get("team") and e["team"].get("name"))
                or "Unknown Team"
            )

            # Fix: Extract players from the team members list
            players = []
            team_members = e.get("team", {}).get("members", [])
            for m in team_members:
                p_name = m.get("displayName")  # This is the Matcherino Name
                if p_name:
                    players.append(p_name)

            # Fallback for solo players or older API versions
            if not players:
                players = [p.get("name") for p in e.get("players", []) if p.get("name")]

            entrant_map[e_id] = {"name": name, "players": players}

        def get_team_info(entrant_dict):
            if not entrant_dict:
                return {"name": "TBD", "score": 0, "players": []}
            e_id = entrant_dict.get("entrantId", 0)
            score = entrant_dict.get("score") or 0
            info = entrant_map.get(e_id, {"name": "TBD", "players": []})
            return {"name": info["name"], "score": score, "players": info["players"]}

        # VISUAL MATCH MAPPING
        visible_matches = []
        for m in raw_matches:
            e_a = m.get("entrantA", {}).get("entrantId", 0)
            e_b = m.get("entrantB", {}).get("entrantId", 0)
            if e_a != 1 and e_b != 1:
                visible_matches.append(m)

        visible_matches.sort(key=lambda x: x.get("matchNum", 9999))

        visual_match_map = {}
        for i, m in enumerate(visible_matches, start=1):
            m["visualNum"] = i
            visual_match_map[i] = m

        raw_to_visual = {
            m.get("matchNum"): v_num for v_num, m in visual_match_map.items()
        }

        def find_src(my_entrant, other_entrant, srcs, fallback_idx=0):
            """Return the entrantSources entry for my_entrant by matching entrantId."""
            my_id = (my_entrant or {}).get("entrantId", 0)
            other_id = (other_entrant or {}).get("entrantId", 0)
            if my_id != 0:
                found = next((s for s in srcs if s.get("entrantId") == my_id), None)
                if found:
                    return found
            if other_id != 0:
                found = next((s for s in srcs if s.get("entrantId") != other_id), None)
                if found:
                    return found
            return srcs[fallback_idx] if len(srcs) > fallback_idx else None

        def resolve_name(entrant_dict, source_entry, depth=0):
            name = get_team_info(entrant_dict)["name"]
            if name not in ("TBD", "BYE"):
                return name
            if not source_entry or depth > 1:
                return "TBD"
            raw_src = source_entry.get("matchNum")
            v_src = raw_to_visual.get(raw_src, raw_src)
            src = visual_match_map.get(v_src)
            if not src:
                return f"Waiting on Match #{v_src}"
            srcs = src.get("entrantSources") or []
            src_ea = find_src(src.get("entrantA"), src.get("entrantB"), srcs, 0)
            src_eb = find_src(src.get("entrantB"), src.get("entrantA"), srcs, 1)
            a = resolve_name(src.get("entrantA"), src_ea, depth + 1)
            b = resolve_name(src.get("entrantB"), src_eb, depth + 1)
            if "Waiting on" not in a and "Waiting on" not in b:
                a_score = src.get("entrantA", {}).get("score") or 0
                b_score = src.get("entrantB", {}).get("score") or 0
                return f"Waiting on Match #{v_src} ({a} {a_score} - {b_score} {b})"
            return f"Waiting on Match #{v_src} ({a} vs {b})"

        def build_tbd_chain(source_entry):
            if not source_entry:
                return ["→ No source match information available"]
            raw_src = source_entry.get("matchNum")
            v_src = raw_to_visual.get(raw_src, raw_src)
            src_match = visual_match_map.get(v_src)
            if not src_match:
                return [f"→ Waiting on Match #{v_src}"]
            srcs = src_match.get("entrantSources") or []
            src_ea = find_src(
                src_match.get("entrantA"), src_match.get("entrantB"), srcs, 0
            )
            src_eb = find_src(
                src_match.get("entrantB"), src_match.get("entrantA"), srcs, 1
            )
            a_name = resolve_name(src_match.get("entrantA"), src_ea, depth=1)
            b_name = resolve_name(src_match.get("entrantB"), src_eb, depth=1)
            if "Waiting on" not in a_name and "Waiting on" not in b_name:
                a_score = src_match.get("entrantA", {}).get("score") or 0
                b_score = src_match.get("entrantB", {}).get("score") or 0
                return [f"→ Match #{v_src}: {a_name} {a_score} - {b_score} {b_name}"]
            return [
                f"→ Match #{v_src} [A]: {a_name}",
                f"→ Match #{v_src} [B]: {b_name}",
            ]

        current_match = visual_match_map.get(int(target_match_number))

        if not current_match:
            return {
                "error": f"Visual Match #{target_match_number} not found in this bracket."
            }

        team_a = get_team_info(current_match.get("entrantA"))
        team_b = get_team_info(current_match.get("entrantB"))

        sources = current_match.get("entrantSources") or []
        team_a_is_tbd = team_a["name"] in ("TBD", "BYE")
        team_b_is_tbd = team_b["name"] in ("TBD", "BYE")

        def tbd_label(src_entry):
            if not src_entry:
                return "TBD"
            raw = src_entry.get("matchNum")
            v = raw_to_visual.get(raw, raw)
            src_m = visual_match_map.get(v)
            if not src_m:
                return f"Waiting on Match #{v}"
            srcs_m = src_m.get("entrantSources") or []
            src_mea = find_src(src_m.get("entrantA"), src_m.get("entrantB"), srcs_m, 0)
            src_meb = find_src(src_m.get("entrantB"), src_m.get("entrantA"), srcs_m, 1)
            a_name = resolve_name(src_m.get("entrantA"), src_mea)
            b_name = resolve_name(src_m.get("entrantB"), src_meb)
            a_sc = src_m.get("entrantA", {}).get("score") or 0
            b_sc = src_m.get("entrantB", {}).get("score") or 0
            return f"Waiting on Match #{v} [{a_name} {a_sc} - {b_sc} {b_name}]"

        if team_a_is_tbd:
            src_a = find_src(
                current_match.get("entrantA"), current_match.get("entrantB"), sources, 0
            )
            team_a["name"] = tbd_label(src_a)
            team_a["score"] = None

        if team_b_is_tbd:
            src_b = find_src(
                current_match.get("entrantB"), current_match.get("entrantA"), sources, 1
            )
            team_b["name"] = tbd_label(src_b)
            team_b["score"] = None

        match_status = current_match.get("status", "unknown")

        # --- IMPROVED TIMING LOGIC ---
        # statusAt = Last update time (when teams were paired OR score changed)
        # createdAt = When the tournament started (structural creation)

        update_time_unix = None
        time_elapsed_str = "Unknown"

        # We prefer statusAt for "Time since paired/updated"
        time_str = current_match.get("statusAt") or current_match.get("createdAt")

        if time_str:
            try:
                dt = datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
                update_time_unix = int(dt.timestamp())

                current_unix = int(time.time())
                elapsed_seconds = current_unix - update_time_unix

                if elapsed_seconds < 0:
                    elapsed_seconds = 0

                minutes, seconds = divmod(elapsed_seconds, 60)
                hours, minutes = divmod(minutes, 60)

                if hours > 0:
                    time_elapsed_str = f"{hours}h {minutes}m {seconds}s"
                else:
                    time_elapsed_str = f"{minutes}m {seconds}s"
            except Exception:
                pass

        team_a_history = (
            build_tbd_chain(
                find_src(
                    current_match.get("entrantA"),
                    current_match.get("entrantB"),
                    sources,
                    0,
                )
            )
            if team_a_is_tbd
            else []
        )
        team_b_history = (
            build_tbd_chain(
                find_src(
                    current_match.get("entrantB"),
                    current_match.get("entrantA"),
                    sources,
                    1,
                )
            )
            if team_b_is_tbd
            else []
        )

        for v_num, match in visual_match_map.items():
            if str(v_num) == str(target_match_number):
                continue

            t_a_past = get_team_info(match.get("entrantA"))
            t_b_past = get_team_info(match.get("entrantB"))

            # Process History for Team A from the current matchup
            if team_a["name"] not in ["TBD", "BYE"] and team_a["name"] in (
                t_a_past["name"],
                t_b_past["name"],
            ):
                is_pos_a = t_a_past["name"] == team_a["name"]
                opp_name = t_b_past["name"] if is_pos_a else t_a_past["name"]

                if opp_name.upper() == "TBD":
                    h_srcs = match.get("entrantSources") or []
                    opp_dict = (
                        match.get("entrantB") if is_pos_a else match.get("entrantA")
                    )
                    my_dict = (
                        match.get("entrantA") if is_pos_a else match.get("entrantB")
                    )
                    opp_src = find_src(opp_dict, my_dict, h_srcs)
                    opp_label = resolve_name(opp_dict, opp_src)
                    team_a_history.append(
                        f"Match {v_num}: {team_a['name']} vs {opp_label}"
                    )
                elif opp_name.upper() != "BYE":
                    t_score = t_a_past["score"] if is_pos_a else t_b_past["score"]
                    o_score = t_b_past["score"] if is_pos_a else t_a_past["score"]
                    team_a_history.append(
                        f"Match {v_num}: {team_a['name']} vs {opp_name} ({t_score} - {o_score})"
                    )

            # Process History for Team B from the current matchup
            if team_b["name"] not in ["TBD", "BYE"] and team_b["name"] in (
                t_a_past["name"],
                t_b_past["name"],
            ):
                is_pos_a = t_a_past["name"] == team_b["name"]
                opp_name = t_b_past["name"] if is_pos_a else t_a_past["name"]

                if opp_name.upper() == "TBD":
                    h_srcs = match.get("entrantSources") or []
                    opp_dict = (
                        match.get("entrantB") if is_pos_a else match.get("entrantA")
                    )
                    my_dict = (
                        match.get("entrantA") if is_pos_a else match.get("entrantB")
                    )
                    opp_src = find_src(opp_dict, my_dict, h_srcs)
                    opp_label = resolve_name(opp_dict, opp_src)
                    team_b_history.append(
                        f"Match {v_num}: {team_b['name']} vs {opp_label}"
                    )
                elif opp_name.upper() != "BYE":
                    t_score = t_a_past["score"] if is_pos_a else t_b_past["score"]
                    o_score = t_b_past["score"] if is_pos_a else t_a_past["score"]
                    team_b_history.append(
                        f"Match {v_num}: {team_b['name']} vs {opp_name} ({t_score} - {o_score})"
                    )

        # Fuzzy match: compare topic team name to bracket teams; flag mismatch for staff
        team_name_mismatch = False
        team_name_best_match = None
        team_name_best_match_ratio = None
        if topic_team_name and (topic_team_name := topic_team_name.strip()):
            matches, best_ratio, best_name = _team_name_matches(
                topic_team_name,
                team_a["name"],
                team_b["name"],
            )
            team_name_mismatch = not matches
            team_name_best_match = best_name
            team_name_best_match_ratio = best_ratio

        return {
            "status": "success",
            "match_number": target_match_number,
            "match_status": match_status,
            "time_elapsed": time_elapsed_str,
            "update_time": update_time_unix,
            "team_a": team_a,
            "team_b": team_b,
            "team_a_history": team_a_history,
            "team_b_history": team_b_history,
            "team_name_mismatch": team_name_mismatch,
            "team_name_best_match": team_name_best_match,
            "team_name_best_match_ratio": team_name_best_match_ratio,
        }

    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


def _parse_tournament_name(soup) -> str | None:
    """Read the tournament name from a tournament page, or None if absent.

    Kept free of HTTP so it can be unit-tested in isolation.
    """
    # 1st choice: the specific title class. 2nd: the sidebar title container.
    name_tag = soup.find("div", class_="title mr-08") or soup.find(
        "div", class_="title-container"
    )
    if not name_tag:
        return None
    return name_tag.get_text(strip=True) or None


def _parse_prize_pool(soup) -> float | None:
    """Read the prize pool from a tournament page.

    Returns a float -- 0.0 is a legitimate value for a free tourney -- or None
    when the amount could not be read. Keeping those two distinct is the whole
    point: conflating them is what made the Hall of Fame publish "$0.00" for a
    scrape failure, with no error and no log line.

    Kept free of HTTP so it can be unit-tested in isolation.
    """
    container = soup.find("div", class_="prize-pool-amt")
    if not container:
        print("[PAYOUT] prize pool element (div.prize-pool-amt) not found on page")
        return None

    span = container.find("span")
    if not span:
        print("[PAYOUT] prize pool container has no <span> child")
        return None

    raw_text = span.get_text(strip=True)
    try:
        return float(raw_text.replace("$", "").replace(",", "").strip())
    except ValueError:
        print(f"[PAYOUT] prize pool text is not numeric: {raw_text!r}")
        return None


def _fetch_tournament_page(url: str) -> str | None:
    """GET a tournament page's HTML, retrying once so a transient 429 or timeout
    doesn't surface as an unreadable prize pool. None if both attempts fail."""
    for attempt in (1, 2):
        try:
            res = session.get(url, headers=PAGE_HEADERS, timeout=10)
            res.raise_for_status()
            return res.text
        except Exception as e:
            print(f"[PAYOUT] page fetch attempt {attempt}/2 failed: {e}")
            if attempt == 1:
                time.sleep(1)
    return None


def fetch_payout_report(tournament_id: str) -> dict:
    """
    Scrapes Tourney Name & Prize Pool from HTML.
    Targeting specific classes for white-labeled tournament pages.

    "total" is a float when the prize pool was read (0.0 is valid -- a free
    tourney) and None when it could not be read; when it is None the "results"
    prize values are None too and the caller must not publish the report. The
    name and prize scrapes are independent, so one failing never silently
    zeroes the other.
    """
    url = f"https://matcherino.com/tournaments/{tournament_id}"
    total_prize = None
    tourney_name = "Tournament Results"

    # 1. Scrape Name & Amount from HTML (independently -- see docstring)
    html = _fetch_tournament_page(url)
    if html is not None:
        soup = BeautifulSoup(html, "html.parser")
        tourney_name = _parse_tournament_name(soup) or tourney_name
        total_prize = _parse_prize_pool(soup)

    # 2. Fetch API Bracket Data
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={tournament_id}&id=0&isAdmin=false"
    try:
        response = session.get(api_url, timeout=10)
        data = response.json()
        bracket_data = data["body"][0]
        raw_matches = bracket_data.get("matches", [])
        raw_entrants = bracket_data.get("entrants", [])
    except Exception as e:
        return {"error": f"API Connection failed: {e}"}

    # 3. ID -> Name Map
    entrant_map = {0: "TBD", 1: "BYE"}
    for e in raw_entrants:
        e_id = e.get("id")
        name = e.get("name") or (e.get("team") and e["team"].get("name")) or "Unknown"
        entrant_map[e_id] = name

    # 4. Filter & Sort Matches (Finals usually [-2], Bronze usually [-1])
    # Logic based on Matcherino match number sequencing
    visible_matches = [
        m
        for m in raw_matches
        if m.get("entrantA", {}).get("entrantId", 0) > 1
        and m.get("entrantB", {}).get("entrantId", 0) > 1
    ]
    visible_matches.sort(key=lambda x: x.get("matchNum", 0))

    if len(visible_matches) < 2:
        return {"error": "Not enough matches to determine Top 4."}

    # Final Match is normally the second-to-last match created in the bracket sequence
    final_match = visible_matches[-2]
    bronze_match = visible_matches[-1]

    def resolve_names(m):
        e_a, e_b = m.get("entrantA", {}), m.get("entrantB", {})
        id_a, id_b = e_a.get("entrantId", 0), e_b.get("entrantId", 0)
        score_a, score_b = e_a.get("score", 0), e_b.get("score", 0)

        # Winner check with fallback to score if the match isn't officially "closed" in API
        w_id = m.get("winnerId")
        if not w_id or w_id == 0:
            w_id = id_a if score_a > score_b else id_b

        l_id = id_b if w_id == id_a else id_a
        return entrant_map.get(w_id, "Unknown"), entrant_map.get(l_id, "Unknown")

    p1_team, p2_team = resolve_names(final_match)
    p3_team, p4_team = resolve_names(bronze_match)

    def _split(pct: float) -> float | None:
        # None total means "unknown", so the splits are unknown too. Computing
        # them would raise on None, and defaulting them to 0.0 would recreate
        # the original bug.
        return None if total_prize is None else total_prize * pct

    return {
        "tourney_name": tourney_name,
        "total": total_prize,
        "results": {
            "1st": p1_team,
            "p1": _split(0.50),
            "2nd": p2_team,
            "p2": _split(0.25),
            "3rd": p3_team,
            "p3": _split(0.15),
            "4th": p4_team,
            "p4": _split(0.10),
        },
    }


def fetch_bracket_progress(url: str) -> dict:
    """
    Scans the entire bracket to provide accurate progress metrics and identify bottlenecks.
    """
    id_match = re.search(r"tournaments/(\d+)", url)
    if not id_match:
        return {"error": "Invalid Matcherino URL."}

    bounty_id = id_match.group(1)
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={bounty_id}&id=0&isAdmin=false"

    try:
        response = session.get(api_url, timeout=10)
        data = response.json()
        if not data.get("body") or len(data["body"]) == 0:
            return {
                "error": "Matcherino API returned an empty body. Is the ID correct?"
            }
        bracket_data = data["body"][0]
        raw_matches = bracket_data.get("matches", [])
        raw_entrants = bracket_data.get("entrants", [])
    except Exception as e:
        return {"error": f"API Connection failed: {e}"}

    if not raw_matches:
        return {"error": "Bracket is empty."}

    # 1. Map Entrant IDs to Names
    entrant_map = {0: "TBD", 1: "BYE"}
    for e in raw_entrants:
        e_id = e.get("id")
        name = e.get("name") or (e.get("team") and e["team"].get("name")) or "Unknown"
        entrant_map[e_id] = name

    # 2. Filter Real Matches & Resolve Rounds
    real_matches = []
    for m in raw_matches:
        e_a = m.get("entrantA", {}).get("entrantId", 0)
        e_b = m.get("entrantB", {}).get("entrantId", 0)
        if e_a == 1 or e_b == 1:
            continue  # Skip BYE placeholders

        m["resolved_round"] = m.get("round") or m.get("roundNum") or 1
        real_matches.append(m)

    # Normalize round numbers so the first real round is always Round 1.
    # When participant count is <= half the bracket size, Matcherino gives every
    # team a first-round BYE. After filtering those out, resolved_round starts
    # at 2+, shifting every displayed round label up by one.
    if real_matches:
        min_round = min(m["resolved_round"] for m in real_matches)
        if min_round > 1:
            for m in real_matches:
                m["resolved_round"] -= min_round - 1

    # Build visual numbering map (the numbers staff see on the bracket UI).
    # We keep this consistent with fetch_ticket_context: sort visible matches by API matchNum
    # and assign sequential visual numbers.
    visual_sorted_matches = sorted(real_matches, key=lambda x: x.get("matchNum", 9999))
    visual_num_by_match_key: dict[tuple[int, int], int] = {}
    for visual_num, m in enumerate(visual_sorted_matches, start=1):
        match_num = m.get("matchNum")
        round_num = m.get("resolved_round", 0)
        if match_num is not None:
            visual_num_by_match_key[(int(match_num), int(round_num))] = visual_num

    total_matches = len(real_matches)
    finished_statuses = ("closed", "completed", "complete", "done")
    closed_matches = [
        m for m in real_matches if str(m.get("status")).lower() in finished_statuses
    ]
    incomplete_matches = [m for m in real_matches if m not in closed_matches]

    # 3. Active Match Logic: Both teams known + Not finished
    # This fixes the "0 Paired" bug by including all playable matches
    active_matches = []
    for m in incomplete_matches:
        if (
            m.get("entrantA", {}).get("entrantId", 0) > 1
            and m.get("entrantB", {}).get("entrantId", 0) > 1
        ):
            active_matches.append(m)

    # 4. Round & Path Logic
    max_round = max([m["resolved_round"] for m in real_matches]) if real_matches else 1

    winner_team = None
    final_round_matches = [
        m
        for m in real_matches
        if int(m.get("resolved_round", 0)) == int(max_round)
        and m.get("entrantA", {}).get("entrantId", 0) > 1
        and m.get("entrantB", {}).get("entrantId", 0) > 1
    ]
    if final_round_matches:
        final_round_matches_sorted = sorted(
            final_round_matches, key=lambda x: x.get("matchNum", 0)
        )
        for fm in final_round_matches_sorted:
            entrant_a = fm.get("entrantA", {})
            entrant_b = fm.get("entrantB", {})
            id_a = entrant_a.get("entrantId", 0)
            id_b = entrant_b.get("entrantId", 0)
            score_a = entrant_a.get("score", 0)
            score_b = entrant_b.get("score", 0)

            winner_id = fm.get("winnerId")
            if not winner_id or winner_id == 0:
                if score_a == score_b:
                    continue
                winner_id = id_a if score_a > score_b else id_b

            winner_team = entrant_map.get(winner_id, "Unknown")
            if winner_team and winner_team.upper() not in {"UNKNOWN", "TBD", "BYE"}:
                break

    # Dominant Round: The highest round currently seeing active play
    if active_matches:
        dominant_round = max([m["resolved_round"] for m in active_matches])
    else:
        dominant_round = (
            max([m["resolved_round"] for m in incomplete_matches])
            if incomplete_matches
            else max_round
        )

    active_match_details = []
    for m in active_matches:
        raw_match_num = m.get("matchNum")
        raw_round_num = int(m.get("resolved_round", 0))
        visual_num = None
        if raw_match_num is not None:
            visual_num = visual_num_by_match_key.get(
                (int(raw_match_num), raw_round_num)
            )

        active_match_details.append(
            {
                "id": visual_num if visual_num is not None else raw_match_num,
                "round": raw_round_num,
                "team_a": entrant_map.get(
                    m.get("entrantA", {}).get("entrantId", 0), "Unknown"
                ),
                "team_b": entrant_map.get(
                    m.get("entrantB", {}).get("entrantId", 0), "Unknown"
                ),
                "score_a": m.get("entrantA", {}).get("score", 0),
                "score_b": m.get("entrantB", {}).get("score", 0),
                "announcement_key": f"{raw_round_num}:{raw_match_num if raw_match_num is not None else visual_num}",
            }
        )

    # All resolved matches (active + closed) — used for stage announcements so that
    # semi-finals remain detectable after they close and finals become active.
    all_match_details = []
    for m in real_matches:
        raw_match_num = m.get("matchNum")
        raw_round_num = int(m.get("resolved_round", 0))
        visual_num = None
        if raw_match_num is not None:
            visual_num = visual_num_by_match_key.get(
                (int(raw_match_num), raw_round_num)
            )

        all_match_details.append(
            {
                "id": visual_num if visual_num is not None else raw_match_num,
                "round": raw_round_num,
                "team_a": entrant_map.get(
                    m.get("entrantA", {}).get("entrantId", 0), "Unknown"
                ),
                "team_b": entrant_map.get(
                    m.get("entrantB", {}).get("entrantId", 0), "Unknown"
                ),
                "score_a": m.get("entrantA", {}).get("score", 0),
                "score_b": m.get("entrantB", {}).get("score", 0),
                "announcement_key": f"{raw_round_num}:{raw_match_num if raw_match_num is not None else visual_num}",
            }
        )

    # 5. Bottlenecks: Active matches lagging behind the front-line round
    bottlenecks = []
    for m in active_matches:
        if m["resolved_round"] < dominant_round:
            raw_match_num = m.get("matchNum")
            raw_round_num = int(m.get("resolved_round", 0))
            visual_num = None
            if raw_match_num is not None:
                visual_num = visual_num_by_match_key.get(
                    (int(raw_match_num), raw_round_num)
                )

            bottlenecks.append(
                {
                    # "id" is intentionally the visual bracket number for staff-facing embeds.
                    "id": visual_num if visual_num is not None else raw_match_num,
                    "round": m["resolved_round"],
                    "team_a": entrant_map.get(
                        m.get("entrantA", {}).get("entrantId", 0), "Unknown"
                    ),
                    "team_b": entrant_map.get(
                        m.get("entrantB", {}).get("entrantId", 0), "Unknown"
                    ),
                    "score_a": m.get("entrantA", {}).get("score", 0),
                    "score_b": m.get("entrantB", {}).get("score", 0),
                }
            )

    # --- Per-round timestamp data (for snapshot round_duration) ---
    round_timestamps = {}
    for m in real_matches:
        r = m["resolved_round"]
        if r not in round_timestamps:
            round_timestamps[r] = {
                "start_candidates": [],
                "end_candidates": [],
                "match_count": 0,
            }
        round_timestamps[r]["match_count"] += 1
        # min(statusAt) across all matches in the round = round start proxy
        ts = m.get("statusAt") or m.get("createdAt")
        if ts:
            round_timestamps[r]["start_candidates"].append(ts)
        # max(endAt) across done matches only = round end proxy
        if str(m.get("status", "")).lower() in finished_statuses:
            end_ts = m.get("endAt") or m.get("statusAt")
            if end_ts:
                round_timestamps[r]["end_candidates"].append(end_ts)

    return {
        "status": "success",
        "total": total_matches,
        "closed": len(closed_matches),
        "completion_pct": round((len(closed_matches) / total_matches) * 100, 1)
        if total_matches > 0
        else 0,
        "dominant_round": dominant_round,
        "max_round": max_round,
        "winner_team": winner_team,
        "bottlenecks": sorted(bottlenecks, key=lambda x: x["round"]),  # Sort by round
        "active_count": len(active_matches),
        "active_matches": sorted(
            active_match_details,
            key=lambda x: (x["round"], x["id"] if isinstance(x["id"], int) else 9999),
        ),
        "all_matches": sorted(
            all_match_details,
            key=lambda x: (x["round"], x["id"] if isinstance(x["id"], int) else 9999),
        ),
        "round_timestamps": round_timestamps,
    }
