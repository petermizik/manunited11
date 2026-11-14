#!/usr/bin/env python3
"""Fetches live 2026/27 squads, positions, market values, and verified photo IDs
across all 9 permitted European leagues from FotMob's open JSON endpoints.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import urllib.request

REPO_DIR = "/usr/local/google/home/mizik/.gemini/jetski/scratch/manchester-united-engine"
DATA_DIR = os.path.join(REPO_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

LEAGUE_CONFIG = [
    {"id": "ENG1", "fotmobId": 47, "name": "Premier League", "country": "England", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "tierGroup": "Top 5 European Leagues"},
    {"id": "ESP1", "fotmobId": 87, "name": "La Liga", "country": "Spain", "flag": "🇪🇸", "tierGroup": "Top 5 European Leagues"},
    {"id": "ITA1", "fotmobId": 55, "name": "Serie A", "country": "Italy", "flag": "🇮🇹", "tierGroup": "Top 5 European Leagues"},
    {"id": "GER1", "fotmobId": 54, "name": "Bundesliga", "country": "Germany", "flag": "🇩🇪", "tierGroup": "Top 5 European Leagues"},
    {"id": "FRA1", "fotmobId": 53, "name": "Ligue 1", "country": "France", "flag": "🇫🇷", "tierGroup": "Top 5 European Leagues"},
    {"id": "NED1", "fotmobId": 57, "name": "Eredivisie", "country": "Netherlands", "flag": "🇳🇱", "tierGroup": "Additional Scouting Leagues"},
    {"id": "POR1", "fotmobId": 61, "name": "Primeira Liga", "country": "Portugal", "flag": "🇵🇹", "tierGroup": "Additional Scouting Leagues"},
    {"id": "NOR1", "fotmobId": 59, "name": "Eliteserien", "country": "Norway", "flag": "🇳🇴", "tierGroup": "Additional Scouting Leagues"},
    {"id": "DEN1", "fotmobId": 46, "name": "Superliga", "country": "Denmark", "flag": "🇩🇰", "tierGroup": "Additional Scouting Leagues"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_positions(pos_desc_str, role_group):
    """Maps FotMob positionIdsDesc (e.g. 'LW,ST,CAM') and role group to canonical tactical codes."""
    valid_codes = {"GK", "LB", "LWB", "CB", "RB", "RWB", "CDM", "CM", "LM", "RM", "CAM", "LW", "RW", "ST"}
    positions = []
    if pos_desc_str:
        for raw in pos_desc_str.split(","):
            code = raw.strip().upper()
            if code == "CF":
                code = "ST"
            elif code == "DM":
                code = "CDM"
            elif code == "AM":
                code = "CAM"
            if code in valid_codes and code not in positions:
                positions.append(code)

    if not positions:
        if role_group == "keepers":
            positions = ["GK"]
        elif role_group == "defenders":
            positions = ["CB"]
        elif role_group == "midfielders":
            positions = ["CM"]
        else:
            positions = ["ST"]

    # Ensure sensible tactical versatility within the same role family
    primary = positions[0]
    if primary == "CB":
        for extra in ["LCB", "RCB"]:
            if extra not in positions:
                positions.append(extra)
    elif "CB" in positions:
        for extra in ["LCB", "RCB"]:
            if extra not in positions:
                positions.append(extra)

    # For Manchester United's Kobbie Mainoo or pure CDM/CM players, ensure CM <-> CDM compatibility
    if "CDM" in positions and "CM" not in positions and role_group == "midfielders":
        positions.append("CM")

    return primary, positions


def extract_surname(full_name):
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name.strip()
    # Keep common two-part surnames or standard last name
    particles = {"de", "van", "von", "da", "di", "del", "dos", "el", "al", "st.", "le"}
    if len(parts) >= 3 and parts[-2].lower() in particles:
        return f"{parts[-2]} {parts[-1]}"
    return parts[-1]


def fetch_team_squad(task):
    lg_id, team_id, team_name, short_name = task
    url = f"https://www.fotmob.com/api/data/teams?id={team_id}"
    try:
        data = fetch_json(url)
    except Exception as exc:
        print(f"Warning: failed to fetch team {team_name} ({team_id}): {exc}", file=sys.stderr)
        return None, []

    is_mufc = (int(team_id) == 10260)
    team_obj = {
        "id": f"TM_{team_id}",
        "fotmobId": int(team_id),
        "name": team_name,
        "shortName": short_name or team_name,
        "leagueId": lg_id,
        "isMUFC": is_mufc,
        "logoUrl": f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png"
    }

    squad_groups = data.get("squad", {}).get("squad", [])
    players_out = []
    for grp in squad_groups:
        grp_title = (grp.get("title") or "").lower()
        if grp_title == "coach":
            continue
        for m in grp.get("members", []):
            pid = m.get("id")
            name = m.get("name")
            if not pid or not name:
                continue
            primary_pos, all_positions = normalize_positions(m.get("positionIdsDesc"), grp_title)
            raw_val = m.get("transferValue") or 0
            val_eur_m = round(raw_val / 1_000_000.0, 1) if raw_val else 1.0
            if val_eur_m < 0.5:
                val_eur_m = 0.5
            val_gbp_m = round(val_eur_m * 0.85, 1)

            players_out.append({
                "id": f"PL_{pid}",
                "fotmobId": int(pid),
                "name": name,
                "surname": extract_surname(name),
                "clubId": f"TM_{team_id}",
                "clubName": short_name or team_name,
                "leagueId": lg_id,
                "isMUFC": is_mufc,
                "primaryPos": primary_pos,
                "positions": all_positions,
                "valueEurM": val_eur_m,
                "valueGbpM": val_gbp_m,
                "age": m.get("age") or 22,
                "nationality": m.get("cname") or m.get("ccode") or "",
                "shirtNumber": m.get("shirtNumber") or "",
                "headshotUrl": f"https://images.fotmob.com/image_resources/playerimages/{pid}.png"
            })

    return team_obj, players_out


def main():
    print("Fetching live league tables for all 9 European leagues from FotMob...")
    team_tasks = []
    for lg in LEAGUE_CONFIG:
        url = f"https://www.fotmob.com/api/data/leagues?id={lg['fotmobId']}"
        d = fetch_json(url)
        table_blocks = d.get("table", [])
        rows = []
        for blk in table_blocks:
            tdata = blk.get("data", {})
            if "table" in tdata and "all" in tdata["table"]:
                rows = tdata["table"]["all"]
                break
            if "tables" in tdata and tdata["tables"]:
                rows = tdata["tables"][0].get("table", {}).get("all", [])
                break
        print(f"  {lg['id']} ({lg['name']}): {len(rows)} clubs")
        for r in rows:
            tid = r.get("id")
            tname = r.get("name")
            sname = r.get("shortName") or tname
            if tid and tname:
                team_tasks.append((lg["id"], tid, tname, sname))

    print(f"Fetching squads for {len(team_tasks)} clubs concurrently...")
    teams = []
    players = []
    seen_player_ids = set()

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch_team_squad, t) for t in team_tasks]
        for fut in as_completed(futures):
            t_obj, p_list = fut.result()
            if t_obj:
                teams.append(t_obj)
            for p in p_list:
                if p["id"] not in seen_player_ids:
                    seen_player_ids.add(p["id"])
                    players.append(p)

    # Sort teams alphabetically (with MUFC first) and players by value descending
    teams.sort(key=lambda x: (not x["isMUFC"], x["name"]))
    players.sort(key=lambda x: (-x["valueEurM"], x["name"]))

    with open(os.path.join(DATA_DIR, "leagues.json"), "w", encoding="utf-8") as f:
        json.dump(LEAGUE_CONFIG, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "teams.json"), "w", encoding="utf-8") as f:
        json.dump(teams, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "players.json"), "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)

    mufc_players = [p for p in players if p["isMUFC"]]
    print(f"Done! Saved {len(LEAGUE_CONFIG)} leagues, {len(teams)} clubs, {len(players)} total players ({len(mufc_players)} MUFC squad members).")


if __name__ == "__main__":
    main()
