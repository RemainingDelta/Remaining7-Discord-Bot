import json
import re
import time
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

def fetch_ticket_context(url: str, target_match_number: int) -> dict:
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
                
            t_a = get_team_info(match.get('entrantA'))
            t_b = get_team_info(match.get('entrantB'))
            
            if team_a['name'] not in ["TBD", "BYE"] and team_a['name'] in (t_a['name'], t_b['name']):
                opponent = t_b['name'] if t_a['name'] == team_a['name'] else t_a['name']
                if opponent.upper() not in ["BYE", "TBD"]:
                    team_a_history.append(f"Match {v_num}: vs {opponent} ({t_a['score']} - {t_b['score']})")

            if team_b['name'] not in ["TBD", "BYE"] and team_b['name'] in (t_a['name'], t_b['name']):
                opponent = t_b['name'] if t_a['name'] == team_b['name'] else t_a['name']
                if opponent.upper() not in ["BYE", "TBD"]:
                    team_b_history.append(f"Match {v_num}: vs {opponent} ({t_a['score']} - {t_b['score']})")

        return {
            "status": "success",
            "match_number": target_match_number,
            "match_status": match_status,
            "time_elapsed": time_elapsed_str,
            "update_time": update_time_unix,
            "team_a": team_a,
            "team_b": team_b,
            "team_a_history": team_a_history,
            "team_b_history": team_b_history
        }

    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}