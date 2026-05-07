"""
team_tools.py — ARCL team data tools.

All schedule and roster data fetched LIVE from arcl.org.
Standings (wins/losses/points) read from Firestore arcl_teams collection.
"""
import logging
import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional

from src.adar.db import vector_search, direct_query
from src.adar.config import (
    ARCL_TEAMS_COLLECTION,
    ARCL_SEASON_NAME_TO_ID,
    ARCL_SEASON_MAP,
)

logger = logging.getLogger(__name__)

ARCL_BASE = "https://www.arcl.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Confirmed team_id per season for known teams (avoids repeated DivHome lookups)
TEAM_ID_CACHE: dict[str, dict[int, tuple]] = {
    "agomoni tigers": {
        69: ("7778", 10),
        66: ("7262", 10),
        65: ("7178", 10),
        63: ("6670", 10),
    },
}


def _resolve_season(season: str) -> tuple:
    """Resolve season name -> (season_id, resolved_name). Returns latest if empty."""
    if season:
        sid = ARCL_SEASON_NAME_TO_ID.get(season)
        if sid:
            return sid, season
        for name, s in ARCL_SEASON_NAME_TO_ID.items():
            if season.lower() in name.lower() or name.lower() in season.lower():
                return s, name
    sid = max(ARCL_SEASON_MAP.keys())
    return sid, ARCL_SEASON_MAP[sid]


async def _find_team_id_live(team_name: str, season_id: int) -> tuple:
    """Search DivHome pages for team_id. Returns (team_id, league_id) or (None, None)."""
    team_lower = team_name.strip().lower()
    async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as client:
        for league_id in [10, 9, 8, 7, 2, 4, 6, 33]:
            url = (f"{ARCL_BASE}/Pages/UI/DivHome.aspx"
                   f"?teams_stats_type_id=2&season_id={season_id}&league_id={league_id}")
            try:
                r = await client.get(url)
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style"]): tag.decompose()
                for row in soup.find_all("tr"):
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if not any(team_lower in c.lower() for c in cols):
                        continue
                    for a in row.find_all("a", href=True):
                        m = re.search(r"team_id=(\d+)", a["href"], re.I)
                        if m:
                            return m.group(1), league_id
            except Exception:
                continue
    return None, None


async def _get_team_id(team_name: str, season_id: int) -> tuple:
    """Get (team_id, league_id) via cache → Firestore → live search."""
    key = team_name.strip().lower()

    # 1. Cache
    if key in TEAM_ID_CACHE and season_id in TEAM_ID_CACHE[key]:
        return TEAM_ID_CACHE[key][season_id]

    # 2. Firestore
    standings = await get_team_standings(team_name)
    if not standings:
        results = await vector_search(ARCL_TEAMS_COLLECTION, team_name, top_k=20)
        standings = [r for r in results
                     if team_name.lower() in r.get("team_name", "").lower()
                     and r.get("team_id")]
    for s in standings:
        if s.get("season_id") == season_id and s.get("team_id"):
            return s["team_id"], s.get("league_id")

    # 3. Live DivHome search
    return await _find_team_id_live(team_name, season_id)


# ─────────────────────────────────────────────────────────────────────────────

async def search_team(name: str, top_k: int = 5) -> list:
    """Search for an ARCL team by name."""
    exact = await direct_query(ARCL_TEAMS_COLLECTION, {"team_name": name}, limit=10)
    with_stats = [r for r in exact if r.get("wins", 0) > 0 or r.get("losses", 0) > 0]
    if with_stats:
        return with_stats
    results = await vector_search(ARCL_TEAMS_COLLECTION, name, top_k=top_k)
    return [
        {"team_name": r.get("team_name"), "division": r.get("division"),
         "season": r.get("season"), "wins": r.get("wins", 0),
         "losses": r.get("losses", 0), "points": r.get("points", 0)}
        for r in results if r.get("wins", 0) > 0 or r.get("losses", 0) > 0
    ]


async def get_team_history(team_name: str) -> list:
    """Get full performance history across all seasons."""
    records = await get_team_standings(team_name)
    if not records:
        results = await vector_search(ARCL_TEAMS_COLLECTION, team_name, top_k=20)
        records = [r for r in results if r.get("wins", 0) > 0 or r.get("losses", 0) > 0]
    if not records:
        return [{"message": f"No history found for '{team_name}'. Run standings ingestion."}]
    history = [
        {"team_name": r.get("team_name", team_name), "season": r.get("season"),
         "division": r.get("division"), "wins": r.get("wins", 0),
         "losses": r.get("losses", 0), "tied": r.get("tied", 0), "points": r.get("points", 0)}
        for r in records
    ]
    history.sort(key=lambda x: x.get("season", ""), reverse=True)
    return history


async def get_team_season(team_name: str, season: str) -> dict:
    """Get a team's record for a specific season."""
    records = await get_team_standings(team_name, season=season)
    if not records:
        all_rec = await get_team_standings(team_name)
        records = [r for r in all_rec if season.lower() in r.get("season", "").lower()]
    if not records:
        return {"message": f"No data for {team_name} in {season}. Run standings ingestion."}
    r = records[0]
    return {
        "team_name": r.get("team_name", team_name), "season": r.get("season", season),
        "division": r.get("division"), "wins": r.get("wins", 0),
        "losses": r.get("losses", 0), "tied": r.get("tied", 0), "points": r.get("points", 0),
    }


async def get_team_players_live(team_name: str, season: str = "") -> dict:
    """
    Fetch team roster with batting and bowling stats LIVE from arcl.org.

    Args:
        team_name: e.g. 'Agomoni Tigers'
        season: e.g. 'Summer 2025' (optional — latest if omitted)
    """
    season_id, resolved_season = _resolve_season(season)
    team_id, league_id = await _get_team_id(team_name, season_id)

    if not team_id:
        return {
            "team_name": team_name, "season": resolved_season,
            "message": (f"team_id not found for '{team_name}' in {resolved_season}. "
                        "Run: python -m ingestion.run_ingestion --only standings"),
        }

    url = (f"{ARCL_BASE}/Pages/UI/TeamStats.aspx"
           f"?team_id={team_id}&league_id={league_id}&season_id={season_id}")

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
    except Exception as e:
        return {"team_name": team_name, "message": f"Fetch error: {e}"}

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style"]): tag.decompose()
    tables = soup.find_all("table")

    if len(tables) < 3:
        return {"team_name": team_name, "message": "No stats available for this season."}

    def find_table(stat_type):
        bat_kws  = {"runs", "balls", "fours", "sixs", "strike rate"}
        bowl_kws = {"overs", "maidens", "wickets", "eco rate"}
        kws = bat_kws if stat_type == "batting" else bowl_kws
        for t in tables:
            rows = t.find_all("tr")
            if len(rows) < 2: continue
            hdrs = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th","td"])]
            if sum(1 for h in hdrs if any(k in h for k in kws)) >= 2:
                return t, hdrs
        return None, []

    def parse(table, hdrs):
        if not table: return {}
        rows = table.find_all("tr")
        def ci(*names):
            for n in names:
                for i, h in enumerate(hdrs):
                    if h == n.lower(): return i
            for n in names:
                for i, h in enumerate(hdrs):
                    if n.lower() in h: return i
            return None
        pid_col  = ci("player_id", "playerid")
        name_col = ci("player", "name") or 0
        result   = {}
        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not any(cols): continue
            pname = cols[name_col] if name_col < len(cols) else ""
            pid   = cols[pid_col]  if pid_col is not None and pid_col < len(cols) else ""
            if not pname or pname.lower() in ("player","name","total",""): continue
            if pname not in result:
                result[pname] = {"player_id": pid, "cols": cols, "headers": hdrs}
        return result

    def gv(data, *names):
        cols = data.get("cols", []); hdrs = data.get("headers", [])
        for n in names:
            for i, h in enumerate(hdrs):
                if n.lower() == h or n.lower() in h:
                    v = cols[i] if i < len(cols) else ""
                    return v if v not in ("","-") else ""
        return ""

    bat_t,  bat_h  = find_table("batting")
    bowl_t, bowl_h = find_table("bowling")
    bat_d  = parse(bat_t,  bat_h)
    bowl_d = parse(bowl_t, bowl_h)

    seen   = {}
    players = []

    for pname in set(list(bat_d.keys()) + list(bowl_d.keys())):
        bat  = bat_d.get(pname, {})
        bowl = bowl_d.get(pname, {})
        pid  = bat.get("player_id") or bowl.get("player_id", "")

        batting = {}
        if bat:
            batting["innings"]  = gv(bat, "innings") or "0"
            batting["runs"]     = gv(bat, "runs") or "0"
            v = gv(bat, "balls");        batting["balls_faced"]  = v if v else None
            v = gv(bat, "fours");        batting["fours"]        = v if v else None
            v = gv(bat, "sixs","six");   batting["sixes"]        = v if v else None
            v = gv(bat, "strike rate","sr"); batting["strike_rate"] = v if v else None
        batting = {k: v for k, v in batting.items() if v is not None}

        bowling = {}
        if bowl:
            bowling["innings"] = gv(bowl, "innings") or "0"
            bowling["wickets"] = gv(bowl, "wickets") or "0"
            v = gv(bowl, "overs");                    bowling["overs"]     = v if v and v!="0" else None
            v = gv(bowl, "maidens");                  bowling["maidens"]   = v if v else None
            v = gv(bowl, "runs");                     bowling["runs_given"]= v if v and v!="0" else None
            v = gv(bowl, "average");                  bowling["average"]   = v if v and v!="0" else None
            v = gv(bowl, "eco rate","economy","eco"); bowling["economy"]   = v if v and v!="0" else None
        bowling = {k: v for k, v in bowling.items() if v is not None}

        try:
            runs = int(batting.get("runs", 0))
        except (ValueError, TypeError):
            runs = 0

        entry = {
            "player_name": pname, "player_id": pid,
            "profile_url": f"{ARCL_BASE}/Pages/UI/PlayerHistory.aspx?player_id={pid}" if pid else "",
            "batting": batting, "bowling": bowling,
        }

        if pname in seen:
            try:
                ex_runs = int(players[seen[pname]]["batting"].get("runs", 0))
            except (ValueError, TypeError):
                ex_runs = 0
            if runs > ex_runs:
                players[seen[pname]] = entry
        else:
            seen[pname] = len(players)
            players.append(entry)

    players.sort(key=lambda x: int(x["batting"].get("runs", 0) or 0), reverse=True)

    return {
        "team_name": team_name, "season": resolved_season,
        "season_id": season_id, "team_id": team_id,
        "source_url": url, "total": len(players), "players": players,
    }


async def get_team_schedule(team_name: str, season: str = "") -> dict:
    """
    Get playing schedule and umpiring assignments LIVE from arcl.org.

    Args:
        team_name: e.g. 'Agomoni Tigers'
        season: e.g. 'Spring 2026' (optional — latest if omitted)
    """
    season_id, resolved_season = _resolve_season(season)
    team_id, league_id = await _get_team_id(team_name, season_id)

    if not team_id:
        return {
            "team_name": team_name, "season": resolved_season,
            "message": f"team_id not found for '{team_name}' in {resolved_season}.",
        }

    sched_url = (f"{ARCL_BASE}/Pages/UI/LeagueSchedule.aspx"
                 f"?league_id={league_id}&season_id={season_id}")
    team_lower     = team_name.strip().lower()
    playing        = []
    umpiring       = []

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(sched_url)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script","style"]): tag.decompose()

            tables = soup.find_all("table")
            best   = max(tables, key=lambda t: len(t.find_all("tr")), default=None)
            if not best:
                raise ValueError("No tables found")

            rows  = best.find_all("tr")
            raw_h = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            norm  = [h.strip().lower() for h in raw_h]

            def ci(*names):
                for n in names:
                    for i, h in enumerate(norm):
                        if h == n.lower(): return i
                for n in names:
                    for i, h in enumerate(norm):
                        if n.lower() in h: return i
                return None

            dc = ci("date") or 0
            tc = ci("start time","time")
            ec = ci("end time","end")
            gc = ci("ground","venue")
            t1 = ci("team1")
            t2 = ci("team2")
            u1 = ci("umpire")
            u2 = ci("umpire2")
            wc = ci("winner")
            rc = ci("runner")

            def get(cols, idx, default=""):
                return cols[idx] if idx is not None and idx < len(cols) else default

            for row in rows[1:]:
                cols   = [td.get_text(strip=True) for td in row.find_all("td")]
                if not any(cols): continue
                t1v    = get(cols, t1); t2v = get(cols, t2)
                u1v    = get(cols, u1); u2v = get(cols, u2)
                winner = get(cols, wc); runner = get(cols, rc)
                is_play = team_lower in t1v.lower() or team_lower in t2v.lower()
                is_ump  = (team_lower in u1v.lower() or team_lower in u2v.lower()) and not is_play
                if not is_play and not is_ump: continue

                entry = {
                    "date": get(cols,dc), "time": get(cols,tc), "end_time": get(cols,ec),
                    "ground": get(cols,gc), "team1": t1v, "team2": t2v,
                    "status": "Played" if winner else "Upcoming",
                }
                if winner: entry["result"] = winner
                if runner: entry["margin"] = runner

                if is_play:
                    entry["opponent"]     = t2v if team_lower in t1v.lower() else t1v
                    entry["home_or_away"] = "Home" if team_lower in t1v.lower() else "Away"
                    entry["umpire"]       = u1v
                    playing.append(entry)
                else:
                    umpiring.append(entry)

    except Exception as e:
        logger.error(f"Schedule error: {e}")
        return {"team_name": team_name, "season": resolved_season, "message": f"Error: {e}"}

    played   = [m for m in playing if m["status"] == "Played"]
    upcoming = [m for m in playing if m["status"] == "Upcoming"]

    return {
        "team_name": team_name, "season": resolved_season, "source_url": sched_url,
        "played_count": len(played), "upcoming_count": len(upcoming),
        "umpiring_count": len(umpiring),
        "played_matches": played, "upcoming_matches": upcoming, "umpiring_matches": umpiring,
    }


async def get_teams_in_division(division: str, season: str = "") -> list:
    """Get all teams in a division sorted by points."""
    div_clean  = division.strip().upper().replace("DIB","DIV")
    div_letter = div_clean.replace("DIV","").replace("DIVISION","").strip()

    DIV_TO_LEAGUE = {
        "H":10,"DIV H":10,"G":9,"DIV G":9,
        "A":7,"B":7,"C":7,"D":7,"E":8,"F":8,
        "WOMEN":2,"WOMAN":2,"KIDS":4,"YOUTH":4,"CHAMPIONS":6,
    }
    league_id_filter = DIV_TO_LEAGUE.get(div_letter) or DIV_TO_LEAGUE.get(div_clean)
    _, resolved_season = _resolve_season(season)

    if league_id_filter:
        f = {"league_id": league_id_filter}
        if season: f["season"] = resolved_season
        records = await direct_query(ARCL_TEAMS_COLLECTION, f, limit=50)
        records = [r for r in records if r.get("wins",0)>0 or r.get("losses",0)>0]
        if records:
            teams = [{"team_name":r.get("team_name"),"season":r.get("season"),
                      "division":r.get("division"),"wins":r.get("wins",0),
                      "losses":r.get("losses",0),"points":r.get("points",0)} for r in records]
            teams.sort(key=lambda x:x.get("points",0), reverse=True)
            return teams

    results = await vector_search(ARCL_TEAMS_COLLECTION, f"division {division} {season}".strip(), top_k=30)
    teams = [
        {"team_name":r.get("team_name"),"season":r.get("season"),
         "division":r.get("division"),"wins":r.get("wins",0),
         "losses":r.get("losses",0),"points":r.get("points",0)}
        for r in results
        if div_letter in r.get("division","").upper()
        and (not season or season.lower() in r.get("season","").lower())
        and (r.get("wins",0)>0 or r.get("losses",0)>0)
    ]
    teams.sort(key=lambda x:x.get("points",0), reverse=True)
    return teams


async def get_season_info(season_name: str = "") -> dict:
    """Look up season ID from name, or list all known seasons."""
    if season_name:
        sid = ARCL_SEASON_NAME_TO_ID.get(season_name)
        if not sid:
            for name, s in ARCL_SEASON_NAME_TO_ID.items():
                if season_name.lower() == name.lower():
                    sid = s; season_name = name; break
        if not sid:
            matches = [{"season_name":n,"season_id":s}
                       for n,s in ARCL_SEASON_NAME_TO_ID.items()
                       if season_name.lower() in n.lower()]
            if matches:
                return {"query": season_name, "matches": sorted(matches, key=lambda x:x["season_name"])}
            return {"error": f"Season '{season_name}' not found."}
        return {"season_name":season_name,"season_id":sid,"is_current":sid==max(ARCL_SEASON_MAP.keys())}

    return {
        "current_season":    ARCL_SEASON_MAP.get(max(ARCL_SEASON_MAP.keys())),
        "current_season_id": max(ARCL_SEASON_MAP.keys()),
        "all_seasons": [{"season_name":n,"season_id":s}
                        for s,n in sorted(ARCL_SEASON_MAP.items(),reverse=True)
                        if "cancelled" not in n.lower()],
    }


async def list_divisions(season: str = "") -> list:
    """List all divisions available, optionally for a specific season."""
    results = await vector_search(ARCL_TEAMS_COLLECTION, f"division teams {season}".strip(), top_k=50)
    divs = {}
    for r in results:
        if r.get("wins",0)==0 and r.get("losses",0)==0: continue
        div = r.get("division","Unknown"); s = r.get("season","")
        if not season or season.lower() in s.lower():
            key = f"{div}|{s}"
            if key not in divs: divs[key] = {"division":div,"season":s,"team_count":0}
            divs[key]["team_count"] += 1
    return sorted(divs.values(), key=lambda x:(x["season"],x["division"]), reverse=True)


async def get_team_career_stats(team_name: str) -> dict:
    """
    Aggregate player stats across ALL seasons for a team.
    Calculates total runs, wickets, innings, strike rate, economy, games played.
    Also computes a team strength score based on historical performance.

    Args:
        team_name: Team name e.g. 'Agomoni Tigers'

    Returns:
        Dict with aggregated player stats table and team strength analysis
    """
    from src.adar.config import ARCL_SEASON_MAP

    # Get all known season/team_id combos for this team
    cache_key = team_name.strip().lower()
    known_seasons = TEAM_ID_CACHE.get(cache_key, {})

    # Also check Firestore standings for additional seasons
    standings = await get_team_standings(team_name)
    for s in standings:
        sid = s.get("season_id")
        tid = s.get("team_id")
        lid = s.get("league_id")
        if sid and tid and sid not in known_seasons:
            known_seasons[sid] = (tid, lid)

    if not known_seasons:
        return {
            "team_name": team_name,
            "message": (
                f"No season data found for '{team_name}'. "
                "Run: python -m ingestion.run_ingestion --only standings"
            ),
        }

    # Fetch TeamStats for each season
    player_totals: dict[str, dict] = {}
    seasons_fetched = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        for season_id, (team_id, league_id) in sorted(known_seasons.items(), reverse=True):
            season_name = ARCL_SEASON_MAP.get(season_id, f"Season {season_id}")
            url = (f"{ARCL_BASE}/Pages/UI/TeamStats.aspx"
                   f"?team_id={team_id}&league_id={league_id}&season_id={season_id}")
            try:
                r = await client.get(url)
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style"]): tag.decompose()
                tables = soup.find_all("table")
                if len(tables) < 3:
                    continue

                def find_table(stat_type):
                    bat_kws  = {"runs", "balls", "fours", "sixs", "strike rate"}
                    bowl_kws = {"overs", "maidens", "wickets", "eco rate"}
                    kws = bat_kws if stat_type == "batting" else bowl_kws
                    for t in tables:
                        rows = t.find_all("tr")
                        if len(rows) < 2: continue
                        hdrs = [th.get_text(strip=True).lower()
                                for th in rows[0].find_all(["th","td"])]
                        if sum(1 for h in hdrs if any(k in h for k in kws)) >= 2:
                            return t, hdrs
                    return None, []

                def parse(table, hdrs):
                    if not table: return {}
                    rows = table.find_all("tr")
                    def ci(*names):
                        for n in names:
                            for i, h in enumerate(hdrs):
                                if h == n.lower(): return i
                        for n in names:
                            for i, h in enumerate(hdrs):
                                if n.lower() in h: return i
                        return None
                    pid_col  = ci("player_id","playerid")
                    name_col = ci("player","name") or 0
                    result   = {}
                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all("td")]
                        if not any(cols): continue
                        pname = cols[name_col] if name_col < len(cols) else ""
                        pid   = cols[pid_col] if pid_col is not None and pid_col < len(cols) else ""
                        if not pname or pname.lower() in ("player","name","total",""): continue
                        if pname not in result:
                            result[pname] = {"player_id": pid, "cols": cols, "headers": hdrs}
                    return result

                def gv(data, *names):
                    cols = data.get("cols",[]); hdrs = data.get("headers",[])
                    for n in names:
                        for i,h in enumerate(hdrs):
                            if n.lower()==h or n.lower() in h:
                                v = cols[i] if i < len(cols) else ""
                                try: return float(v.replace("*","")) if v not in ("","-","0") else 0.0
                                except: return 0.0
                    return 0.0

                bat_t, bat_h  = find_table("batting")
                bowl_t, bowl_h = find_table("bowling")
                bat_d  = parse(bat_t,  bat_h)
                bowl_d = parse(bowl_t, bowl_h)

                seasons_fetched.append(season_name)

                for pname in set(list(bat_d.keys()) + list(bowl_d.keys())):
                    bat  = bat_d.get(pname, {})
                    bowl = bowl_d.get(pname, {})
                    pid  = bat.get("player_id") or bowl.get("player_id","")

                    if pname not in player_totals:
                        player_totals[pname] = {
                            "player_id":      pid,
                            "seasons_played": 0,
                            "bat_innings":    0,
                            "bat_runs":       0,
                            "bat_balls":      0,
                            "bat_fours":      0,
                            "bat_sixes":      0,
                            "bowl_innings":   0,
                            "bowl_overs":     0.0,
                            "bowl_runs":      0,
                            "bowl_wickets":   0,
                            "seasons":        [],
                        }

                    p = player_totals[pname]
                    p["seasons_played"] += 1
                    p["seasons"].append(season_name)
                    p["bat_innings"]  += int(gv(bat,  "innings") or 0)
                    p["bat_runs"]     += int(gv(bat,  "runs")    or 0)
                    p["bat_balls"]    += int(gv(bat,  "balls")   or 0)
                    p["bat_fours"]    += int(gv(bat,  "fours")   or 0)
                    p["bat_sixes"]    += int(gv(bat,  "sixs","six") or 0)
                    p["bowl_innings"] += int(gv(bowl, "innings") or 0)
                    p["bowl_overs"]   += float(gv(bowl,"overs")  or 0)
                    p["bowl_runs"]    += int(gv(bowl, "runs")    or 0)
                    p["bowl_wickets"] += int(gv(bowl, "wickets") or 0)

            except Exception as e:
                logger.debug(f"Error fetching {season_name}: {e}")
                continue

    if not player_totals:
        return {
            "team_name": team_name,
            "message": "No player data found across seasons. Run standings ingestion first.",
        }

    # Compute derived stats
    players = []
    for pname, p in player_totals.items():
        bat_sr  = round((p["bat_runs"]  / p["bat_balls"]  * 100), 1) if p["bat_balls"]  > 0 else 0
        bowl_eco = round((p["bowl_runs"] / p["bowl_overs"]),        2) if p["bowl_overs"] > 0 else 0
        bowl_avg = round((p["bowl_runs"] / p["bowl_wickets"]),      1) if p["bowl_wickets"] > 0 else 0

        # Player strength score (0-100):
        #   Batting contribution: runs + SR bonus + boundary bonus
        #   Bowling contribution: wickets + economy bonus
        bat_score  = min(p["bat_runs"] * 0.3 + bat_sr * 0.2 + (p["bat_fours"] + p["bat_sixes"] * 1.5) * 0.5, 50)
        bowl_score = min(p["bowl_wickets"] * 3 + (8 - bowl_eco) * 2 if bowl_eco > 0 else 0, 50)
        strength   = round(bat_score + bowl_score, 1)

        players.append({
            "player_name":    pname,
            "player_id":      p["player_id"],
            "seasons_played": p["seasons_played"],
            "batting": {
                "innings":     p["bat_innings"],
                "total_runs":  p["bat_runs"],
                "total_balls": p["bat_balls"],
                "fours":       p["bat_fours"],
                "sixes":       p["bat_sixes"],
                "strike_rate": bat_sr,
            },
            "bowling": {
                "innings":         p["bowl_innings"],
                "total_overs":     round(p["bowl_overs"], 1),
                "total_runs_given":p["bowl_runs"],
                "total_wickets":   p["bowl_wickets"],
                "economy":         bowl_eco,
                "bowling_average": bowl_avg,
            },
            "strength_score":  strength,
            "role": (
                "All-rounder" if p["bat_runs"] > 30 and p["bowl_wickets"] > 3
                else "Batter" if p["bat_runs"] > p["bowl_wickets"] * 5
                else "Bowler" if p["bowl_wickets"] > 0
                else "Batter"
            ),
        })

    players.sort(key=lambda x: x["strength_score"], reverse=True)

    # Team strength analysis
    top5 = players[:5]
    team_strength = round(sum(p["strength_score"] for p in top5) / len(top5), 1) if top5 else 0

    # Win rate from standings
    win_rate = 0
    total_w = total_l = 0
    for s in standings:
        total_w += s.get("wins", 0)
        total_l += s.get("losses", 0)
    if total_w + total_l > 0:
        win_rate = round(total_w / (total_w + total_l) * 100, 1)

    # Top performers
    top_batter  = max(players, key=lambda x: x["batting"]["total_runs"],   default=None)
    top_bowler  = max(players, key=lambda x: x["bowling"]["total_wickets"], default=None)
    top_allround= max(players, key=lambda x: x["strength_score"],           default=None)

    return {
        "team_name":       team_name,
        "seasons_analysed":seasons_fetched,
        "total_players":   len(players),
        "players":         players,
        "team_analysis": {
            "strength_score":  team_strength,
            "strength_rating": (
                "Strong" if team_strength >= 40
                else "Competitive" if team_strength >= 25
                else "Developing"
            ),
            "win_rate_pct":    win_rate,
            "total_wins":      total_w,
            "total_losses":    total_l,
            "top_batter":      top_batter["player_name"]   if top_batter  else "",
            "top_bowler":      top_bowler["player_name"]   if top_bowler  else "",
            "best_allrounder": top_allround["player_name"] if top_allround else "",
            "key_players":     [p["player_name"] for p in top5],
        },
    }


async def get_match_scorecard(match_id: str, season_id: int = 69, league_id: int = 10) -> dict:
    """
    Fetch a single match scorecard from arcl.org.
    Returns batting and bowling for both innings including dismissal details.

    Args:
        match_id: Match ID from LeagueSchedule page e.g. '28045'
        season_id: Season ID (default 69 = Spring 2026)
        league_id: League ID (default 10 = Div H)
    """
    url = (f"{ARCL_BASE}/Pages/UI/Matchscorecard.aspx"
           f"?match_id={match_id}&league_id={league_id}&season_id={season_id}")

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
    except Exception as e:
        return {"match_id": match_id, "message": f"Fetch error: {e}"}

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script","style"]): tag.decompose()
    tables = soup.find_all("table")

    if len(tables) < 2:
        return {"match_id": match_id, "message": "No scorecard data found"}

    # Parse match header from table 1
    match_info = {}
    if tables:
        header_text = tables[0].get_text(" ", strip=True)
        import re as _re
        for field, pattern in [
            ("teams",   r"Match:(.*?)Date:"),
            ("date",    r"Date:(.*?)Result:"),
            ("result",  r"Result:(.*?)Man of"),
            ("motm",    r"Man of the match:(.*?)Umpire:"),
            ("umpire",  r"Umpire:(.*?)Ground:"),
            ("ground",  r"Ground:(.*?)Toss:"),
            ("toss",    r"Toss:(.*)"),
        ]:
            m = _re.search(pattern, header_text)
            if m:
                match_info[field] = m.group(1).strip()

    def parse_batting(table):
        rows = table.find_all("tr")
        if len(rows) < 2: return []
        batting = []
        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 4: continue
            batter = cols[0]
            if not batter or batter.lower() in ("", "extras", "total", "fall of wickets"):
                continue
            entry = {
                "batter":   batter,
                "how_out":  cols[1] if len(cols) > 1 else "",
                "fielder":  cols[2] if len(cols) > 2 else "",
                "bowler":   cols[3] if len(cols) > 3 else "",
                "sixes":    cols[4] if len(cols) > 4 else "0",
                "fours":    cols[5] if len(cols) > 5 else "0",
                "runs":     cols[6] if len(cols) > 6 else "0",
                "balls":    cols[7] if len(cols) > 7 else "0",
            }
            batting.append(entry)
        return batting

    def parse_bowling(table):
        rows = table.find_all("tr")
        if len(rows) < 2: return []
        bowling = []
        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 3: continue
            bowler = cols[0]
            if not bowler: continue
            bowling.append({
                "bowler":   bowler,
                "overs":    cols[1] if len(cols) > 1 else "",
                "maidens":  cols[2] if len(cols) > 2 else "",
                "no_balls": cols[3] if len(cols) > 3 else "",
                "wides":    cols[4] if len(cols) > 4 else "",
                "runs":     cols[5] if len(cols) > 5 else "",
                "wickets":  cols[6] if len(cols) > 6 else "",
            })
        return bowling

    # Tables: 0=header, 1=innings1 batting, 2=innings1 bowling, 3=innings2 batting, 4=innings2 bowling
    innings1_batting = parse_batting(tables[1]) if len(tables) > 1 else []
    innings1_bowling = parse_bowling(tables[2]) if len(tables) > 2 else []
    innings2_batting = parse_batting(tables[3]) if len(tables) > 3 else []
    innings2_bowling = parse_bowling(tables[4]) if len(tables) > 4 else []

    return {
        "match_id":       match_id,
        "source_url":     url,
        "match_info":     match_info,
        "innings1": {
            "batting": innings1_batting,
            "bowling": innings1_bowling,
        },
        "innings2": {
            "batting": innings2_batting,
            "bowling": innings2_bowling,
        },
    }


async def get_player_dismissals(player_name: str, team_name: str, season: str = "") -> dict:
    """
    Get dismissal breakdown for a player across all matches in a season.
    Shows how they were dismissed (bowled, caught, run out, LBW, not out etc.)
    and who dismissed them.

    Args:
        player_name: Player name e.g. 'Jiban Adhikary'
        team_name:   Team name e.g. 'Agomoni Tigers'
        season:      Season e.g. 'Spring 2026' (latest if omitted)
    """
    season_id, resolved_season = _resolve_season(season)
    team_id, league_id = await _get_team_id(team_name, season_id)

    if not team_id:
        return {
            "player_name": player_name,
            "message": f"Could not find team_id for '{team_name}'",
        }

    # Fetch all match IDs for this team from LeagueSchedule
    sched_url = (f"{ARCL_BASE}/Pages/UI/LeagueSchedule.aspx"
                 f"?league_id={league_id}&season_id={season_id}")
    team_lower = team_name.strip().lower()
    match_ids = []

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(sched_url)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script","style"]): tag.decompose()

            import re as _re
            for a in soup.find_all("a", href=True):
                href = a["href"]
                m = _re.search(r"match_id=(\d+)", href, _re.I)
                if not m: continue
                # Only matches where this team is playing
                link_text = a.get_text(strip=True).lower()
                parent_text = a.find_parent("tr")
                if parent_text:
                    row_text = parent_text.get_text(" ").lower()
                    if team_lower in row_text:
                        mid = m.group(1)
                        if mid not in match_ids:
                            match_ids.append(mid)
    except Exception as e:
        return {"player_name": player_name, "message": f"Schedule fetch error: {e}"}

    if not match_ids:
        return {
            "player_name": player_name,
            "message": f"No matches found for {team_name} in {resolved_season}",
        }

    # Fetch each scorecard and extract dismissals for this player
    player_lower = player_name.strip().lower()
    dismissals   = []
    matches_played = 0

    for mid in match_ids[:20]:  # cap at 20 matches
        scorecard = await get_match_scorecard(mid, season_id, league_id)
        if "message" in scorecard:
            continue

        match_info = scorecard.get("match_info", {})
        date       = match_info.get("date", "")
        teams      = match_info.get("teams", "")

        for innings_key in ["innings1", "innings2"]:
            for batter in scorecard[innings_key]["batting"]:
                if player_lower in batter["batter"].lower():
                    matches_played += 1
                    dismissals.append({
                        "match_id":  mid,
                        "date":      date,
                        "match":     teams,
                        "runs":      batter["runs"],
                        "balls":     batter["balls"],
                        "how_out":   batter["how_out"] or "not out",
                        "bowler":    batter["bowler"],
                        "fielder":   batter["fielder"],
                        "fours":     batter["fours"],
                        "sixes":     batter["sixes"],
                    })

    if not dismissals:
        return {
            "player_name":   player_name,
            "team_name":     team_name,
            "season":        resolved_season,
            "message":       f"{player_name} not found in any scorecard for {team_name} in {resolved_season}",
        }

    # Aggregate dismissal types
    from collections import Counter
    how_out_counts = Counter(d["how_out"].lower() for d in dismissals)
    top_dismissers = Counter(
        d["bowler"] for d in dismissals
        if d["bowler"] and d["how_out"].lower() not in ("not out", "retired")
    )

    try:
        runs_list = [int(d["runs"]) for d in dismissals if d["runs"].isdigit()]
    except Exception:
        runs_list = []

    return {
        "player_name":    player_name,
        "team_name":      team_name,
        "season":         resolved_season,
        "matches_played": matches_played,
        "dismissal_summary": dict(how_out_counts),
        "top_dismissers":    dict(top_dismissers.most_common(5)),
        "batting_scores":    [{"match": d["match"], "date": d["date"],
                               "runs": d["runs"], "balls": d["balls"],
                               "how_out": d["how_out"], "bowler": d["bowler"]}
                              for d in dismissals],
        "stats": {
            "total_innings": len(dismissals),
            "not_outs":      how_out_counts.get("not out", 0),
            "highest_score": max(runs_list) if runs_list else 0,
            "total_runs":    sum(runs_list),
        },
    }


async def get_team_standings(
    team_name: str,
    season: Optional[str] = None,
) -> list[dict]:
    """Direct lookup for a team's standings records by exact team_name."""
    filters = {"team_name": team_name}
    if season:
        filters["season"] = season
    records = await direct_query(ARCL_TEAMS_COLLECTION, filters, limit=50)
    records = [
        r for r in records
        if r.get("wins", 0) > 0 or r.get("losses", 0) > 0 or r.get("points", 0) > 0
    ]
    records.sort(key=lambda x: x.get("season", ""), reverse=True)
    return records