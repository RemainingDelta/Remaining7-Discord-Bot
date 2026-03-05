import difflib
import re
import time
from bs4 import BeautifulSoup
import requests
import requests_cache
from datetime import timedelta, datetime, timezone

# Mimic a real browser session to avoid blocks/disconnections
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://matcherino.com/',
    'Origin': 'https://matcherino.com'
}

# Initialize a cached session
session = requests_cache.CachedSession(
    'matcherino_cache',
    expire_after=timedelta(seconds=60)
)
session.headers.update(HEADERS)

# Fuzzy match: ratio >= this → accept (minor typos). Below → team name mismatch warning.
TEAM_NAME_SIMILARITY_THRESHOLD = 0.60

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

    ratio_a = difflib.SequenceMatcher(None, topic_n, a_n).ratio() if a_n not in ("tbd", "bye") else 0.0
    ratio_b = difflib.SequenceMatcher(None, topic_n, b_n).ratio() if b_n not in ("tbd", "bye") else 0.0

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

def fetch_ticket_context(url: str, target_match_number: int, topic_team_name: str | None = None) -> dict:
    """
    Parses a Matcherino URL, hits their hidden API for live bracket data, 
    maps entrant IDs to team names, calculates the VISUAL match numbers,
    and compiles historical bracket runs and elapsed time.
    """
    id_match = re.search(r'tournaments/(\d+)', url)
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
        bracket_data = data['body'][0]
        raw_matches = bracket_data.get('matches', [])
        raw_entrants = bracket_data.get('entrants', [])
        
        if not raw_matches:
            return {"error": "Bracket is empty."}

        # Build lookup dictionary for Entrant IDs -> Team Names
        entrant_map = {0: {"name": "TBD", "players": []}, 1: {"name": "BYE", "players": []}}
        for e in raw_entrants:
            e_id = e.get('id')
            name = e.get('name') or (e.get('team') and e['team'].get('name')) or "Unknown Team"
            
            # Fix: Extract players from the team members list
            players = []
            team_members = e.get('team', {}).get('members', [])
            for m in team_members:
                p_name = m.get('displayName') # This is the Matcherino Name
                if p_name:
                    players.append(p_name)
            
            # Fallback for solo players or older API versions
            if not players:
                players = [p.get('name') for p in e.get('players', []) if p.get('name')]

            entrant_map[e_id] = {"name": name, "players": players}

        def get_team_info(entrant_dict):
            if not entrant_dict:
                return {"name": "TBD", "score": 0, "players": []}
            e_id = entrant_dict.get('entrantId', 0)
            score = entrant_dict.get('score', 0)
            info = entrant_map.get(e_id, {"name": "TBD", "players": []})
            return {"name": info["name"], "score": score, "players": info["players"]}
        
        # VISUAL MATCH MAPPING
        visible_matches = []
        for m in raw_matches:
            e_a = m.get('entrantA', {}).get('entrantId', 0)
            e_b = m.get('entrantB', {}).get('entrantId', 0)
            if e_a != 1 and e_b != 1:
                visible_matches.append(m)

        visible_matches.sort(key=lambda x: x.get('matchNum', 9999))

        visual_match_map = {}
        for i, m in enumerate(visible_matches, start=1):
            m['visualNum'] = i
            visual_match_map[i] = m

        current_match = visual_match_map.get(int(target_match_number))
        
        if not current_match:
            return {"error": f"Visual Match #{target_match_number} not found in this bracket."}

        team_a = get_team_info(current_match.get('entrantA'))
        team_b = get_team_info(current_match.get('entrantB'))
        
        match_status = current_match.get('status', 'unknown')
        
        # --- IMPROVED TIMING LOGIC ---
        # statusAt = Last update time (when teams were paired OR score changed)
        # createdAt = When the tournament started (structural creation)
        
        update_time_unix = None
        time_elapsed_str = "Unknown"
        
        # We prefer statusAt for "Time since paired/updated"
        time_str = current_match.get('statusAt') or current_match.get('createdAt')
        
        if time_str:
            try:
                dt = datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
                update_time_unix = int(dt.timestamp()) 
                
                current_unix = int(time.time())
                elapsed_seconds = current_unix - update_time_unix
                
                if elapsed_seconds < 0: elapsed_seconds = 0
                    
                minutes, seconds = divmod(elapsed_seconds, 60)
                hours, minutes = divmod(minutes, 60)
                
                if hours > 0:
                    time_elapsed_str = f"{hours}h {minutes}m {seconds}s"
                else:
                    time_elapsed_str = f"{minutes}m {seconds}s"
            except Exception:
                pass

        team_a_history = []
        team_b_history = []
        
        for v_num, match in visual_match_map.items():
            if str(v_num) == str(target_match_number):
                continue
                
            t_a_past = get_team_info(match.get('entrantA'))
            t_b_past = get_team_info(match.get('entrantB'))
            
            # Process History for Team A from the current matchup
            if team_a['name'] not in ["TBD", "BYE"] and team_a['name'] in (t_a_past['name'], t_b_past['name']):
                is_pos_a = t_a_past['name'] == team_a['name']
                opp_name = t_b_past['name'] if is_pos_a else t_a_past['name']
                
                if opp_name.upper() not in ["BYE", "TBD"]:
                    t_score = t_a_past['score'] if is_pos_a else t_b_past['score']
                    o_score = t_b_past['score'] if is_pos_a else t_a_past['score']
                    team_a_history.append(f"Match {v_num}: {team_a['name']} vs {opp_name} ({t_score} - {o_score})")

            # Process History for Team B from the current matchup
            if team_b['name'] not in ["TBD", "BYE"] and team_b['name'] in (t_a_past['name'], t_b_past['name']):
                is_pos_a = t_a_past['name'] == team_b['name']
                opp_name = t_b_past['name'] if is_pos_a else t_a_past['name']
                
                if opp_name.upper() not in ["BYE", "TBD"]:
                    t_score = t_a_past['score'] if is_pos_a else t_b_past['score']
                    o_score = t_b_past['score'] if is_pos_a else t_a_past['score']
                    team_b_history.append(f"Match {v_num}: {team_b['name']} vs {opp_name} ({t_score} - {o_score})")

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
    
    
def fetch_payout_report(tournament_id: str) -> dict:
    """
    Scrapes Tourney Name & Prize Pool from HTML.
    Targeting specific classes for white-labeled tournament pages.
    """
    url = f"https://matcherino.com/tournaments/{tournament_id}"
    total_prize = 0.0
    tourney_name = "Tournament Results"
    
    # 1. Scrape Name & Amount from HTML
    try:
        page_res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(page_res.text, 'html.parser')
        
        # --- GET TOURNAMENT NAME ---
        # 1st Choice: The specific class you identified
        name_tag = soup.find('div', class_='title mr-08')
        
        # 2nd Choice: Fallback to the title container class found in the sidebars
        if not name_tag:
            name_tag = soup.find('div', class_='title-container')
            
        if name_tag:
            # We strip to remove extra spaces/newlines
            tourney_name = name_tag.get_text(strip=True)
            
        # --- GET PRIZE POOL ---
        amt_container = soup.find('div', class_='prize-pool-amt')
        if amt_container:
            raw_text = amt_container.find('span').text
            total_prize = float(raw_text.replace('$', '').replace(',', ''))
            
    except Exception as e:
        print(f"Scraping Error: {e}")

    # 2. Fetch API Bracket Data
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={tournament_id}&id=0&isAdmin=false"
    try:
        response = session.get(api_url, timeout=10)
        data = response.json()
        bracket_data = data['body'][0]
        raw_matches = bracket_data.get('matches', [])
        raw_entrants = bracket_data.get('entrants', [])
    except Exception as e:
        return {"error": f"API Connection failed: {e}"}

    # 3. ID -> Name Map
    entrant_map = {0: "TBD", 1: "BYE"}
    for e in raw_entrants:
        e_id = e.get('id')
        name = e.get('name') or (e.get('team') and e['team'].get('name')) or "Unknown"
        entrant_map[e_id] = name

    # 4. Filter & Sort Matches (Finals usually [-2], Bronze usually [-1])
    # Logic based on Matcherino match number sequencing
    visible_matches = [m for m in raw_matches if m.get('entrantA', {}).get('entrantId', 0) > 1 and m.get('entrantB', {}).get('entrantId', 0) > 1]
    visible_matches.sort(key=lambda x: x.get('matchNum', 0))

    if len(visible_matches) < 2:
        return {"error": "Not enough matches to determine Top 4."}

    # Final Match is normally the second-to-last match created in the bracket sequence
    final_match = visible_matches[-2] 
    bronze_match = visible_matches[-1]

    def resolve_names(m):
        e_a, e_b = m.get('entrantA', {}), m.get('entrantB', {})
        id_a, id_b = e_a.get('entrantId', 0), e_b.get('entrantId', 0)
        score_a, score_b = e_a.get('score', 0), e_b.get('score', 0)
        
        # Winner check with fallback to score if the match isn't officially "closed" in API
        w_id = m.get('winnerId')
        if not w_id or w_id == 0:
            w_id = id_a if score_a > score_b else id_b
        
        l_id = id_b if w_id == id_a else id_a
        return entrant_map.get(w_id, "Unknown"), entrant_map.get(l_id, "Unknown")

    p1_team, p2_team = resolve_names(final_match)
    p3_team, p4_team = resolve_names(bronze_match)

    return {
        "tourney_name": tourney_name,
        "total": total_prize,
        "results": {
            "1st": p1_team, "p1": total_prize * 0.50,
            "2nd": p2_team, "p2": total_prize * 0.25,
            "3rd": p3_team, "p3": total_prize * 0.15,
            "4th": p4_team, "p4": total_prize * 0.10
        }
    }
    
def fetch_bracket_progress(url: str) -> dict:
    """
    Scans the entire bracket to provide accurate progress metrics and identify bottlenecks.
    """
    id_match = re.search(r'tournaments/(\d+)', url)
    if not id_match:
        return {"error": "Invalid Matcherino URL."}
    
    bounty_id = id_match.group(1)
    api_url = f"https://api.matcherino.com/__api/brackets?bountyId={bounty_id}&id=0&isAdmin=false"
    
    try:
        response = session.get(api_url, timeout=10)
        data = response.json()
        if not data.get('body') or len(data['body']) == 0:
            return {"error": "Matcherino API returned an empty body. Is the ID correct?"}
        bracket_data = data['body'][0]
        raw_matches = bracket_data.get('matches', [])
        raw_entrants = bracket_data.get('entrants', [])
    except Exception as e:
        return {"error": f"API Connection failed: {e}"}

    if not raw_matches:
        return {"error": "Bracket is empty."}

    # 1. Map Entrant IDs to Names
    entrant_map = {0: "TBD", 1: "BYE"}
    for e in raw_entrants:
        e_id = e.get('id')
        name = e.get('name') or (e.get('team') and e['team'].get('name')) or "Unknown"
        entrant_map[e_id] = name

    # 2. Filter Real Matches & Resolve Rounds
    real_matches = []
    for m in raw_matches:
        e_a = m.get('entrantA', {}).get('entrantId', 0)
        e_b = m.get('entrantB', {}).get('entrantId', 0)
        if e_a == 1 or e_b == 1: continue # Skip BYE placeholders
            
        m['resolved_round'] = m.get('round') or m.get('roundNum') or 1
        real_matches.append(m)
    
    total_matches = len(real_matches)
    finished_statuses = ('closed', 'completed', 'complete', 'done')
    closed_matches = [m for m in real_matches if str(m.get('status')).lower() in finished_statuses]
    incomplete_matches = [m for m in real_matches if m not in closed_matches]
    
    # 3. Active Match Logic: Both teams known + Not finished
    # This fixes the "0 Paired" bug by including all playable matches
    active_matches = []
    for m in incomplete_matches:
        if m.get('entrantA', {}).get('entrantId', 0) > 1 and m.get('entrantB', {}).get('entrantId', 0) > 1:
            active_matches.append(m)
    
    # 4. Round & Path Logic
    max_round = max([m['resolved_round'] for m in real_matches]) if real_matches else 1
    
    # Dominant Round: The highest round currently seeing active play
    if active_matches:
        dominant_round = max([m['resolved_round'] for m in active_matches])
    else:
        dominant_round = max([m['resolved_round'] for m in incomplete_matches]) if incomplete_matches else max_round

    # 5. Bottlenecks: Active matches lagging behind the front-line round
    bottlenecks = []
    for m in active_matches:
        if m['resolved_round'] < dominant_round:
            bottlenecks.append({
                "id": m.get('matchNum'),
                "round": m['resolved_round'],
                "team_a": entrant_map.get(m.get('entrantA', {}).get('entrantId', 0), "Unknown"),
                "team_b": entrant_map.get(m.get('entrantB', {}).get('entrantId', 0), "Unknown"),
                "score_a": m.get('entrantA', {}).get('score', 0),
                "score_b": m.get('entrantB', {}).get('score', 0)
            })

    return {
        "status": "success",
        "total": total_matches,
        "closed": len(closed_matches),
        "completion_pct": round((len(closed_matches) / total_matches) * 100, 1) if total_matches > 0 else 0,
        "dominant_round": dominant_round,
        "max_round": max_round,
        "bottlenecks": sorted(bottlenecks, key=lambda x: x['round']), # Sort by round
        "active_count": len(active_matches)
    }
    
    
    