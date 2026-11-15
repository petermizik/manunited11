#!/usr/bin/env python3
"""Fetches official Transfermarkt market values, squads, positions, and portraits
across all 9 permitted European leagues via Transfermarkt's JSON API
(https://tmapi-alpha.transfermarkt.technology).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import urllib.request

REPO_DIR = "/usr/local/google/home/mizik/.gemini/jetski/scratch/manchester-united-engine"
DATA_DIR = os.path.join(REPO_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

TM_API_BASE = "https://tmapi-alpha.transfermarkt.technology"

LEAGUE_CONFIG = [
    {"id": "ENG1", "tmCode": "GB1", "name": "Premier League", "country": "England", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "tierGroup": "Top 5 European Leagues"},
    {"id": "ESP1", "tmCode": "ES1", "name": "La Liga", "country": "Spain", "flag": "🇪🇸", "tierGroup": "Top 5 European Leagues"},
    {"id": "ITA1", "tmCode": "IT1", "name": "Serie A", "country": "Italy", "flag": "🇮🇹", "tierGroup": "Top 5 European Leagues"},
    {"id": "GER1", "tmCode": "L1",  "name": "Bundesliga", "country": "Germany", "flag": "🇩🇪", "tierGroup": "Top 5 European Leagues"},
    {"id": "FRA1", "tmCode": "FR1", "name": "Ligue 1", "country": "France", "flag": "🇫🇷", "tierGroup": "Top 5 European Leagues"},
    {"id": "NED1", "tmCode": "NL1", "name": "Eredivisie", "country": "Netherlands", "flag": "🇳🇱", "tierGroup": "Additional Scouting Leagues"},
    {"id": "POR1", "tmCode": "PO1", "name": "Primeira Liga", "country": "Portugal", "flag": "🇵🇹", "tierGroup": "Additional Scouting Leagues"},
    {"id": "NOR1", "tmCode": "NO1", "name": "Eliteserien", "country": "Norway", "flag": "🇳🇴", "tierGroup": "Additional Scouting Leagues"},
    {"id": "DEN1", "tmCode": "DK1", "name": "Superliga", "country": "Denmark", "flag": "🇩🇰", "tierGroup": "Additional Scouting Leagues"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

TM_POS_MAP = {
    "GK": ["GK"],
    "CB": ["CB", "LCB", "RCB"],
    "SW": ["CB", "LCB", "RCB"],
    "LB": ["LB", "LWB"],
    "RB": ["RB", "RWB"],
    "DM": ["CDM", "CM"],
    "CM": ["CM", "CDM"],
    "LM": ["LM", "LWB", "LW"],
    "RM": ["RM", "RWB", "RW"],
    "AM": ["CAM", "CM"],
    "LW": ["LW", "LM"],
    "RW": ["RW", "RM"],
    "SS": ["CAM", "ST", "LW", "RW"],
    "CF": ["ST"],
}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def map_tm_positions(attrs):
    raw_short_codes = []
    for key in ("position", "firstSidePosition", "secondSidePosition"):
        pos_obj = attrs.get(key)
        if isinstance(pos_obj, dict) and pos_obj.get("shortName"):
            raw_short_codes.append(pos_obj["shortName"].strip().upper())

    mapped = []
    for code in raw_short_codes:
        for target in TM_POS_MAP.get(code, []):
            if target not in mapped:
                mapped.append(target)

    if not mapped:
        grp = (attrs.get("positionGroup") or "").upper()
        if grp == "GOALKEEPER":
            mapped = ["GK"]
        elif grp == "DEFENDER":
            mapped = ["CB", "LCB", "RCB"]
        elif grp == "MIDFIELDER":
            mapped = ["CM", "CDM"]
        else:
            mapped = ["ST"]

    return mapped[0], mapped


def extract_surname(player_obj):
    last_name = (player_obj.get("lastName") or "").strip()
    artist_name = (player_obj.get("artistName") or "").strip()
    full_name = (player_obj.get("name") or "").strip()
    if artist_name:
        return artist_name
    if last_name:
        return last_name
    parts = full_name.split()
    return parts[-1] if parts else full_name


def fetch_club_squad_and_players(task):
    lg_id, club_id, club_meta = task
    is_mufc = (str(club_id) == "985")
    base_details = club_meta.get("baseDetails") or {}
    club_name = club_meta.get("name") or f"Club {club_id}"
    short_name = base_details.get("shortName") or club_name
    crest_url = club_meta.get("crestUrl") or f"https://img.a.transfermarkt.technology/wappen/big/{club_id}.png"

    team_obj = {
        "id": f"TM_{club_id}",
        "tmClubId": str(club_id),
        "name": club_name,
        "shortName": short_name,
        "leagueId": lg_id,
        "isMUFC": is_mufc,
        "logoUrl": crest_url,
    }

    try:
        sq_resp = fetch_json(f"{TM_API_BASE}/club/{club_id}/squad")
        squad_items = sq_resp.get("data", {}).get("squad", [])
    except Exception as exc:
        print(f"Warning: failed squad fetch for {club_name} ({club_id}): {exc}", file=sys.stderr)
        return team_obj, []

    shirt_map = {}
    player_ids = []
    for item in squad_items:
        pid = str(item.get("playerId") or "")
        if pid:
            player_ids.append(pid)
            shirt_map[pid] = item.get("shirtNumber") or ""

    if not player_ids:
        return team_obj, []

    # Fetch player details in batches of 20
    players_out = []
    for i in range(0, len(player_ids), 20):
        batch = player_ids[i:i + 20]
        query = "&".join([f"ids[]={pid}" for pid in batch])
        try:
            pl_resp = fetch_json(f"{TM_API_BASE}/players?{query}")
            pl_list = pl_resp.get("data") or []
        except Exception as exc:
            print(f"Warning: failed player batch for {club_name}: {exc}", file=sys.stderr)
            continue

        for p in pl_list:
            pid = str(p.get("id") or "")
            name = p.get("name")
            if not pid or not name:
                continue
            attrs = p.get("attributes") or {}
            primary_pos, all_positions = map_tm_positions(attrs)

            mv_curr = (p.get("marketValueDetails") or {}).get("current") or {}
            raw_eur = mv_curr.get("value") or 0
            val_eur_m = round(raw_eur / 1_000_000.0, 2)
            val_gbp_m = round(val_eur_m * 0.85, 2)
            determined_date = mv_curr.get("determined") or ""

            age = (p.get("lifeDates") or {}).get("age") or 22
            portrait_url = p.get("portraitUrl") or ""

            players_out.append({
                "id": f"PL_{pid}",
                "tmPlayerId": pid,
                "name": name,
                "surname": extract_surname(p),
                "clubId": f"TM_{club_id}",
                "clubName": short_name,
                "leagueId": lg_id,
                "isMUFC": is_mufc,
                "primaryPos": primary_pos,
                "positions": all_positions,
                "valueEurM": val_eur_m,
                "valueGbpM": val_gbp_m,
                "valueUpdated": determined_date,
                "age": age,
                "shirtNumber": shirt_map.get(pid, ""),
                "headshotUrl": portrait_url,
            })

    return team_obj, players_out


def main():
    print("Fetching Transfermarkt competition tables across all 9 leagues...")
    league_club_pairs = []
    all_club_ids = []
    for lg in LEAGUE_CONFIG:
        code = lg["tmCode"]
        d = fetch_json(f"{TM_API_BASE}/competition/{code}/table")
        tables = d.get("data", {}).get("tables") or []
        clubs = tables[0].get("clubs", []) if tables else []
        print(f"  {lg['id']} ({lg['name']} / {code}): {len(clubs)} clubs")
        for c in clubs:
            cid = str(c.get("clubId") or "")
            if cid:
                league_club_pairs.append((lg["id"], cid))
                all_club_ids.append(cid)

    # Batch-fetch club details (/clubs?ids[]=...)
    club_meta_map = {}
    for i in range(0, len(all_club_ids), 25):
        batch = all_club_ids[i:i + 25]
        q = "&".join([f"ids[]={cid}" for cid in batch])
        resp = fetch_json(f"{TM_API_BASE}/clubs?{q}")
        for c_obj in (resp.get("data") or []):
            club_meta_map[str(c_obj.get("id"))] = c_obj

    tasks = [(lg_id, cid, club_meta_map.get(cid, {"id": cid})) for lg_id, cid in league_club_pairs]
    print(f"Fetching official Transfermarkt squads & market values for {len(tasks)} clubs...")

    teams = []
    players = []
    seen_pids = set()

    with ThreadPoolExecutor(max_workers=14) as pool:
        futures = [pool.submit(fetch_club_squad_and_players, t) for t in tasks]
        for fut in as_completed(futures):
            t_obj, p_list = fut.result()
            if t_obj:
                teams.append(t_obj)
            for p in p_list:
                if p["id"] not in seen_pids:
                    seen_pids.add(p["id"])
                    players.append(p)

    teams.sort(key=lambda x: (not x["isMUFC"], x["name"]))
    players.sort(key=lambda x: (-x["valueEurM"], x["name"]))

    with open(os.path.join(DATA_DIR, "leagues.json"), "w", encoding="utf-8") as f:
        json.dump(LEAGUE_CONFIG, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "teams.json"), "w", encoding="utf-8") as f:
        json.dump(teams, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "players.json"), "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)

    mufc_count = sum(1 for p in players if p["isMUFC"])
    print(f"Success! Saved {len(LEAGUE_CONFIG)} leagues, {len(teams)} clubs, {len(players)} Transfermarkt players ({mufc_count} MUFC).")


if __name__ == "__main__":
    main()
