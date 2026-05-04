"""
ARCL scraper — all data directly from arcl.org. No cricclubs dependency.

TeamStats.aspx page structure (4 tables):
  Table 1 — Match schedule (opponent, date, result)
  Table 2 — Points table (team vs opponent head-to-head points)
  Table 3 — Batting stats: Player, PlayerID, Runs, Balls, 4s, 6s, SR
  Table 4 — Bowling stats: Player, PlayerID, Overs, Maidens, Runs, Wkts, Avg, Econ
"""
import re
import time
import random
import string
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.adar.config import ARCL_SCRAPE_PAGES, settings

logger = logging.getLogger(__name__)

ARCL_BASE = "https://www.arcl.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

LEAGUE_IDS = {
    2: "Women", 4: "Kids/Youth", 5: "Tapeball",
    6: "Champions League", 7: "Men Div A-D",
    8: "Men Div E-H", 9: "Men Div G-H", 10: "Men Div H", 33: "Kids C",
}


@dataclass
class ScrapedChunk:
    content: str
    source_url: str
    page_type: str
    section: Optional[str] = None
    player_name: Optional[str] = None
    player_id: Optional[str] = None
    team_name: Optional[str] = None
    team_id: Optional[str] = None
    season: Optional[str] = None
    season_id: Optional[int] = None
    league_id: Optional[int] = None
    division: Optional[str] = None
    extra: dict = field(default_factory=dict)


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current, current_len = [], [], 0
    for s in sentences:
        slen = len(s.split())
        if current_len + slen > chunk_size and current:
            chunks.append(" ".join(current))
            tail, tlen = [], 0
            for prev in reversed(current):
                if tlen + len(prev.split()) <= overlap:
                    tail.insert(0, prev)
                    tlen += len(prev.split())
                else:
                    break
            current, current_len = tail, tlen
        current.append(s)
        current_len += slen
    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if len(c.strip()) > 50]


async def _get(url: str, client: httpx.AsyncClient) -> Optional[BeautifulSoup]:
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def _safe_float(val: str) -> float:
    try:
        return float(val.replace("*", "").replace("-", "0").strip())
    except (ValueError, AttributeError):
        return 0.0


def _safe_int(val: str) -> int:
    try:
        return int(val.replace("*", "").replace("-", "0").strip())
    except (ValueError, AttributeError):
        return 0


def _extract_player_id_from_row(row) -> tuple[str, str]:
    """Extract player_id and profile_url from a table row's links."""
    for a in row.find_all("a", href=True):
        href = a["href"]
        for pattern in [
            r'player_id=(\d+)',
            r'playerId=(\d+)',
        ]:
            m = re.search(pattern, href, re.I)
            if m:
                pid = m.group(1)
                profile_url = f"{ARCL_BASE}/Pages/UI/PlayerHistory.aspx?player_id={pid}"
                return pid, profile_url
    return "", ""


def _parse_table_headers(table) -> list[str]:
    """Get normalized column headers from a table."""
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [_clean(th.get_text()).lower() for th in rows[0].find_all(["th", "td"])]
    return headers


def _col(cols: list[str], idx: Optional[int], default="") -> str:
    if idx is not None and 0 <= idx < len(cols):
        return cols[idx]
    return default


# ─────────────────────────────────────────────────────────────────────────────
# TEAM STATS — 4-table structure
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_team_stats(
    team_id: str,
    team_name: str,
    league_id: int,
    season_id: int,
    season_label: str,
    division: str,
    client: httpx.AsyncClient,
) -> list[ScrapedChunk]:
    """
    Scrape all 4 tables from TeamStats.aspx:
      Table 1 — Schedule
      Table 2 — Points table
      Table 3 — Batting stats per player
      Table 4 — Bowling stats per player

    Returns one chunk per player (with both batting + bowling),
    plus one chunk for the team schedule.
    """
    url = (
        f"{ARCL_BASE}/Pages/UI/TeamStats.aspx"
        f"?team_id={team_id}&league_id={league_id}&season_id={season_id}"
    )
    soup = await _get(url, client)
    if not soup:
        return []

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    tables = soup.find_all("table")
    if len(tables) < 3:
        logger.debug(f"  {team_name} s={season_id}: only {len(tables)} tables found, skipping")
        return []

    chunks = []

    # ── Table 1 — Schedule ────────────────────────────────────────────────
    # Confirmed headers: Date, Time, End Time, Ground, Team1, Team2,
    #                    Umpire1, Umpire2, Match Type, Division
    # A row is a PLAYING match if team_name == Team1 or Team2.
    # A row is an UMPIRING assignment if team_name == Umpire1 or Umpire2.
    playing_matches = []
    umpiring_matches = []
    try:
        t1 = tables[0]
        raw_h = [th.get_text(strip=True) for th in t1.find_all("tr")[0].find_all(["th", "td"])]
        norm_h = [h.strip().lower() for h in raw_h]

        def ci(*names):
            for name in names:
                for i, h in enumerate(norm_h):
                    if h == name.lower(): return i
            for name in names:
                for i, h in enumerate(norm_h):
                    if name.lower() in h: return i
            return None

        date_col   = ci("date") or 0
        time_col   = ci("time")
        end_col    = ci("end time", "end")
        ground_col = ci("ground", "venue", "location")
        team1_col  = ci("team1", "home team", "team 1")
        team2_col  = ci("team2", "away team", "team 2")
        ump1_col   = ci("umpire1", "umpire 1", "umpire")
        ump2_col   = ci("umpire2", "umpire 2")
        type_col   = ci("match type", "type")
        div_col    = ci("divison", "division", "div")

        def gcol(cols, idx, default=""):
            if idx is not None and idx < len(cols):
                return cols[idx]
            return default

        for row in t1.find_all("tr")[1:]:
            cols = [_clean(td.get_text()) for td in row.find_all("td")]
            if not any(cols):
                continue

            team1  = gcol(cols, team1_col)
            team2  = gcol(cols, team2_col)
            ump1   = gcol(cols, ump1_col)
            ump2   = gcol(cols, ump2_col)
            date   = gcol(cols, date_col)
            time   = gcol(cols, time_col)
            end    = gcol(cols, end_col)
            ground = gcol(cols, ground_col)
            mtype  = gcol(cols, type_col)

            match_info = {
                "date": date, "time": time, "end_time": end,
                "ground": ground, "team1": team1, "team2": team2,
                "match_type": mtype,
            }

            team_name_lower = team_name.lower()
            is_playing  = (team_name_lower in team1.lower() or
                           team_name_lower in team2.lower())
            is_umpiring = (team_name_lower in ump1.lower() or
                           team_name_lower in ump2.lower())

            if is_playing:
                opponent = team2 if team_name_lower in team1.lower() else team1
                match_info["role"]     = "playing"
                match_info["opponent"] = opponent
                playing_matches.append(match_info)
            elif is_umpiring:
                match_info["role"] = "umpiring"
                umpiring_matches.append(match_info)

        # Build content chunk — clearly separate playing from umpiring
        if playing_matches or umpiring_matches:
            content_parts = [
                f"Team: {team_name}.",
                f"Season: {season_label}.",
                f"Division: {division}.",
            ]

            if playing_matches:
                play_lines = []
                for m in playing_matches:
                    play_lines.append(
                        f"{m['date']} {m['time']} vs {m['opponent']} at {m['ground']}"
                    )
                content_parts.append(f"Playing matches ({len(playing_matches)}): {' | '.join(play_lines)}.")
            else:
                content_parts.append("Playing matches: None scheduled yet.")

            if umpiring_matches:
                ump_lines = []
                for m in umpiring_matches:
                    ump_lines.append(
                        f"{m['date']} {m['time']} {m['team1']} vs {m['team2']} at {m['ground']}"
                    )
                content_parts.append(f"Umpiring assignments ({len(umpiring_matches)}): {' | '.join(ump_lines)}.")

            chunks.append(ScrapedChunk(
                content=" ".join(content_parts),
                source_url=url,
                page_type="team_schedule",
                team_name=team_name,
                team_id=team_id,
                season=season_label,
                season_id=season_id,
                league_id=league_id,
                division=division,
                extra={
                    "playing_matches":   playing_matches,
                    "umpiring_matches":  umpiring_matches,
                    "playing_count":     len(playing_matches),
                    "umpiring_count":    len(umpiring_matches),
                    "team_id":           team_id,
                },
            ))
    except Exception as e:
        logger.debug(f"Schedule table parse error: {e}")

    # ── Table 3 — Batting Stats ───────────────────────────────────────────
    batting_by_player: dict[str, dict] = {}
    try:
        t3 = tables[2]
        headers = _parse_table_headers(t3)

        # Find column indexes by keyword matching
        def find_col_idx(*keywords):
            for kw in keywords:
                for i, h in enumerate(headers):
                    if kw in h:
                        return i
            return None

        # Typical batting columns: Player, Runs, Balls, 4s, 6s, SR, HS, Avg, Innings
        name_col  = find_col_idx("player", "name", "batsman") or 0
        runs_col  = find_col_idx("run")
        balls_col = find_col_idx("ball", "bf")
        fours_col = find_col_idx("4s", "four", "fours")
        sixes_col = find_col_idx("6s", "six", "sixes")
        sr_col    = find_col_idx("sr", "strike")
        hs_col    = find_col_idx("hs", "high", "best")
        avg_col   = find_col_idx("avg", "average")
        inn_col   = find_col_idx("inn", "inning")

        # Confirmed arcl.org batting columns (same Player_Id column structure as bowling):
        # ['Player', 'Player_Id', 'Team', 'Innings', 'Runs', 'Balls', '4s', '6s', 'SR', 'HS', 'Avg', 'NO']
        raw_headers_bat = [th.get_text(strip=True)
                           for th in t3.find_all("tr")[0].find_all(["th", "td"])]
        norm_bat = [h.strip().lower() for h in raw_headers_bat]

        def col_idx_bat(*names):
            for name in names:
                for i, h in enumerate(norm_bat):
                    if h == name.lower():
                        return i
            for name in names:
                for i, h in enumerate(norm_bat):
                    if name.lower() in h:
                        return i
            return None

        # Confirmed arcl.org batting headers:
        # Player, Player_Id, Team, Innings, Runs, Balls, Fours, Sixs, Strike Rate
        bat_pid_col   = col_idx_bat("player_id", "playerid", "id")
        bat_inn_col   = col_idx_bat("innings", "inns", "inn")
        bat_runs_col  = col_idx_bat("runs", "run")
        bat_balls_col = col_idx_bat("balls", "ball", "bf")
        bat_fours_col = col_idx_bat("fours", "four", "4s")
        bat_sixes_col = col_idx_bat("sixs", "sixes", "six", "6s")
        bat_sr_col    = col_idx_bat("strike rate", "sr", "s/r")
        bat_hs_col    = col_idx_bat("hs", "highest", "best")   # may not exist
        bat_avg_col   = col_idx_bat("avg", "average")           # may not exist
        bat_no_col    = col_idx_bat("no", "not out")            # may not exist

        logger.debug(f"Batting headers: {raw_headers_bat}")

        for row in t3.find_all("tr")[1:]:
            cols = [_clean(td.get_text()) for td in row.find_all("td")]
            if not cols or len(cols) < 2:
                continue

            player_name = _col(cols, name_col)
            if not player_name or player_name.lower() in ("player", "name", "total", ""):
                continue

            # Get player_id from Player_Id column (most reliable source)
            pid = _col(cols, bat_pid_col) if bat_pid_col is not None else ""
            if not pid:
                pid, _ = _extract_player_id_from_row(row)

            profile_url = (f"https://www.arcl.org/Pages/UI/PlayerHistory.aspx?player_id={pid}"
                           if pid else "")

            batting_by_player[player_name] = {
                "player_id":       pid,
                "profile_url":     profile_url,
                "batting_innings": _safe_int(_col(cols, bat_inn_col)),
                "batting_runs":    _safe_int(_col(cols, bat_runs_col)),
                "batting_balls":   _safe_int(_col(cols, bat_balls_col)),
                "batting_fours":   _safe_int(_col(cols, bat_fours_col)),
                "batting_sixes":   _safe_int(_col(cols, bat_sixes_col)),
                "batting_sr":      _safe_float(_col(cols, bat_sr_col)),
                "batting_highest": _safe_int(_col(cols, bat_hs_col)),
                "batting_average": _safe_float(_col(cols, bat_avg_col)),
                "batting_not_out": _safe_int(_col(cols, bat_no_col)),
            }
    except Exception as e:
        logger.debug(f"Batting table parse error for {team_name}: {e}")

    # ── Table 4 — Bowling Stats ───────────────────────────────────────────
    # Confirmed arcl.org bowling headers:
    # ['Player', 'Player_Id', 'Team', 'Innings', 'Overs', 'Maidens',
    #  'Runs', 'Wickets', 'Average', 'Eco Rate']
    # Indices: 0           1           2       3          4        5
    #          6        7            8          9
    bowling_by_player: dict[str, dict] = {}
    try:
        t4 = tables[3] if len(tables) > 3 else None
        if t4:
            raw_headers = [th.get_text(strip=True) for th in t4.find_all("tr")[0].find_all(["th", "td"])]
            norm        = [h.strip().lower() for h in raw_headers]

            def col_idx(*names):
                """Find column index by exact name, then partial match."""
                for name in names:
                    for i, h in enumerate(norm):
                        if h == name.lower():
                            return i
                for name in names:
                    for i, h in enumerate(norm):
                        if name.lower() in h:
                            return i
                return None

            # Map exact arcl.org column names + common variants
            name_col    = col_idx("player", "name") or 0
            pid_col     = col_idx("player_id", "playerid", "id")        # Player_Id column
            inn_col     = col_idx("innings", "inns", "inn")
            overs_col   = col_idx("overs", "over", "o")
            maiden_col  = col_idx("maidens", "maiden", "m")
            runs_col    = col_idx("runs", "run", "r")
            wkts_col    = col_idx("wickets", "wicket", "wkts", "wkt", "w")
            avg_col     = col_idx("average", "avg")
            econ_col    = col_idx("eco rate", "economy", "econ", "eco", "er")
            sr_col      = col_idx("sr", "strike rate")
            bb_col      = col_idx("bb", "bbi", "best bowling", "best")

            logger.debug(f"Bowling headers: {raw_headers}")
            logger.debug(f"Bowling col map — name:{name_col} pid:{pid_col} "
                         f"overs:{overs_col} maiden:{maiden_col} runs:{runs_col} "
                         f"wkts:{wkts_col} avg:{avg_col} econ:{econ_col}")

            for row in t4.find_all("tr")[1:]:
                cols = [_clean(td.get_text()) for td in row.find_all("td")]
                if not cols or len(cols) < 2:
                    continue

                player_name = _col(cols, name_col)
                if not player_name or player_name.lower() in ("player", "name", "total", ""):
                    continue

                # Get player_id from the Player_Id column (most reliable)
                pid = _col(cols, pid_col) if pid_col is not None else ""
                if not pid:
                    pid, _ = _extract_player_id_from_row(row)
                if not pid and player_name in batting_by_player:
                    pid = batting_by_player[player_name].get("player_id", "")

                profile_url = (f"https://www.arcl.org/Pages/UI/PlayerHistory.aspx?player_id={pid}"
                               if pid else "")

                bowling_by_player[player_name] = {
                    "player_id":        pid,
                    "profile_url":      profile_url,
                    "bowling_innings":  _safe_int(_col(cols, inn_col)),
                    "bowling_overs":    _safe_float(_col(cols, overs_col)),
                    "bowling_maidens":  _safe_int(_col(cols, maiden_col)),
                    "bowling_runs":     _safe_int(_col(cols, runs_col)),
                    "bowling_wickets":  _safe_int(_col(cols, wkts_col)),
                    "bowling_average":  _safe_float(_col(cols, avg_col)),
                    "bowling_economy":  _safe_float(_col(cols, econ_col)),
                    "bowling_sr":       _safe_float(_col(cols, sr_col)),
                    "bowling_best":     _col(cols, bb_col) if bb_col else "",
                }
    except Exception as e:
        logger.debug(f"Bowling table parse error for {team_name}: {e}")

    # ── Merge batting + bowling into one chunk per player ─────────────────
    all_players = set(list(batting_by_player.keys()) + list(bowling_by_player.keys()))

    for player_name in all_players:
        bat  = batting_by_player.get(player_name, {})
        bowl = bowling_by_player.get(player_name, {})

        pid         = bat.get("player_id") or bowl.get("player_id", "")
        profile_url = bat.get("profile_url") or bowl.get("profile_url", "")

        # Build human-readable content
        bat_line = (
            f"Batting — Runs: {bat.get('batting_runs', 0)}, "
            f"Balls: {bat.get('batting_balls', 0)}, "
            f"4s: {bat.get('batting_fours', 0)}, "
            f"6s: {bat.get('batting_sixes', 0)}, "
            f"SR: {bat.get('batting_sr', 0)}, "
            f"Highest: {bat.get('batting_highest', 0)}, "
            f"Avg: {bat.get('batting_average', 0)}"
        ) if bat else "Batting — no data"

        bowl_line = (
            f"Bowling — Overs: {bowl.get('bowling_overs', 0)}, "
            f"Maidens: {bowl.get('bowling_maidens', 0)}, "
            f"Runs given: {bowl.get('bowling_runs', 0)}, "
            f"Wickets: {bowl.get('bowling_wickets', 0)}, "
            f"Avg: {bowl.get('bowling_average', 0)}, "
            f"Economy: {bowl.get('bowling_economy', 0)}, "
            f"Best: {bowl.get('bowling_best', '-')}"
        ) if bowl else "Bowling — no data"

        content = (
            f"Player: {player_name}. "
            f"Player ID: {pid}. "
            f"Team: {team_name}. "
            f"Season: {season_label}. "
            f"Division: {division}. "
            f"{bat_line}. "
            f"{bowl_line}."
        )

        chunks.append(ScrapedChunk(
            content=content,
            source_url=url,
            page_type="player_season",
            player_name=player_name,
            player_id=pid,
            team_name=team_name,
            team_id=team_id,
            season=season_label,
            season_id=season_id,
            league_id=league_id,
            division=division,
            extra={
                # IDs
                "player_id":       pid,
                "profile_url":     profile_url,
                "team_id":         team_id,
                # Batting
                "batting_runs":    bat.get("batting_runs", 0),
                "batting_balls":   bat.get("batting_balls", 0),
                "batting_fours":   bat.get("batting_fours", 0),
                "batting_sixes":   bat.get("batting_sixes", 0),
                "batting_sr":      bat.get("batting_sr", 0.0),
                "batting_highest": bat.get("batting_highest", 0),
                "batting_average": bat.get("batting_average", 0.0),
                "batting_innings": bat.get("batting_innings", 0),
                # Bowling
                "bowling_overs":   bowl.get("bowling_overs", 0.0),
                "bowling_maidens": bowl.get("bowling_maidens", 0),
                "bowling_runs":    bowl.get("bowling_runs", 0),
                "bowling_wickets": bowl.get("bowling_wickets", 0),
                "bowling_average": bowl.get("bowling_average", 0.0),
                "bowling_economy": bowl.get("bowling_economy", 0.0),
                "bowling_sr":      bowl.get("bowling_sr", 0.0),
                "bowling_best":    bowl.get("bowling_best", ""),
            },
        ))

    logger.debug(f"  {team_name} s={season_id} l={league_id}: {len(chunks)} player chunks")
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# STANDINGS — DivHome
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_divhome_standings(
    season_id: int,
    league_id: int,
    client: httpx.AsyncClient,
) -> tuple[list[dict], list[dict]]:
    url = (
        f"{ARCL_BASE}/Pages/UI/DivHome.aspx"
        f"?teams_stats_type_id=2&season_id={season_id}&league_id={league_id}"
    )
    soup = await _get(url, client)
    if not soup:
        return [], []

    page_text = _clean(soup.get_text())
    if len(page_text) < 100:
        return [], []

    # Use known season map first, fall back to page heading, then generic label
    from src.adar.config import ARCL_SEASON_MAP
    season_label = ARCL_SEASON_MAP.get(season_id, "")
    if not season_label:
        for tag in ["h1", "h2", "h3"]:
            el = soup.find(tag)
            if el:
                txt = _clean(el.get_text())
                if re.search(r'(Spring|Summer|Fall|Winter|Kids|Women|Champions)', txt, re.I):
                    season_label = txt
                    break
    if not season_label:
        season_label = f"Season {season_id}"

    # Map league_id directly to a specific division name
    # More reliable than parsing page headings (which show "Sponsors" etc.)
    LEAGUE_TO_DIVISION = {
        2:  "Women",
        4:  "Kids/Youth",
        5:  "Tapeball",
        6:  "Champions League",
        7:  "Men Div A-D",
        8:  "Men Div E-H",
        9:  "Men Div G-H",
        10: "Div H",
        33: "Kids C",
    }
    league_name = LEAGUE_IDS.get(league_id, f"League {league_id}")
    current_division = LEAGUE_TO_DIVISION.get(league_id, league_name)
    standings, team_refs = [], []

    SKIP_HEADINGS = re.compile(
        r"(sponsor|adverti|partner|contact|about|login|register|news|copyright|home)",
        re.I,
    )
    DIV_HEADINGS = re.compile(
        r"(div\s+[a-h]|division\s+[a-h]|women|kids|youth|champions|tapeball)",
        re.I,
    )

    for element in soup.find_all(["h2", "h3", "h4", "strong", "table"]):
        if element.name in ["h2", "h3", "h4", "strong"]:
            txt = _clean(element.get_text())
            if not txt or len(txt) < 2:
                continue
            # Only override with a page heading if it is a specific sub-division name
            if DIV_HEADINGS.search(txt) and not SKIP_HEADINGS.search(txt):
                current_division = txt
            continue

        # This is a table element — parse it as standings
        if element.name != "table":
            continue

        rows = element.find_all("tr")
        if len(rows) < 2:
            continue

        # Get headers and find columns
        # Confirmed arcl.org headers:
        # ['Team Name', 'Rank', 'Played', 'Won', 'Lost', 'Draw', 'Abdn', 'Penalty', 'Points', ...]
        raw_headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
        norm_h = [h.strip().lower() for h in raw_headers]

        def find_col(*kws):
            for kw in kws:
                for i, h in enumerate(norm_h):
                    if h == kw.lower():
                        return i
            for kw in kws:
                for i, h in enumerate(norm_h):
                    if kw.lower() in h:
                        return i
            return None

        team_col = find_col("team name", "team", "club") or 0
        won_col  = find_col("won", "win")
        lost_col = find_col("lost", "loss")
        tied_col = find_col("draw", "tied", "abdn")
        pts_col  = find_col("points", "pts")

        def get_int(cols, idx):
            if idx is not None and idx < len(cols):
                try:
                    return int(cols[idx])
                except (ValueError, TypeError):
                    pass
            return 0

        for row in rows[1:]:
            cols = [_clean(td.get_text()) for td in row.find_all("td")]
            if not cols or len(cols) < 2:
                continue

            team_name = cols[team_col] if team_col < len(cols) else ""
            if not team_name or team_name.lower() in ("team name", "team", "club", ""):
                continue

            wins   = get_int(cols, won_col)
            losses = get_int(cols, lost_col)
            tied   = get_int(cols, tied_col)
            points = get_int(cols, pts_col)

            if wins == 0 and losses == 0 and points == 0:
                continue

            team_id = None
            for a in row.find_all("a", href=True):
                m = re.search(r'team_id=(\d+)', a["href"], re.I)
                if m:
                    team_id = m.group(1)
                    break

            record = {
                "team_name": team_name, "team_id": team_id,
                "division": current_division, "season": season_label,
                "season_id": season_id, "league_id": league_id,
                "wins": wins, "losses": losses, "tied": tied, "points": points,
                "source_url": url,
            }
            standings.append(record)
            if team_id:
                team_refs.append({
                    "team_id": team_id, "team_name": team_name,
                    "league_id": league_id, "season_id": season_id,
                    "season": season_label, "division": current_division,
                })

    return standings, team_refs


async def scrape_all_standings_and_stats(
    scrape_team_stats_too: bool = True,
    league_filter: list[int] = None,
    season_filter: list[int] = None,
) -> tuple[list[ScrapedChunk], list[ScrapedChunk]]:
    standings_chunks = []
    player_season_chunks = []
    seen_standings = set()
    seen_team_stats = set()

    async with httpx.AsyncClient() as client:
        pairs = set()
        all_leagues = league_filter if league_filter else [7, 8, 2, 9, 10, 4, 33]
        all_seasons = season_filter if season_filter else list(range(35, 70))
        for lid in all_leagues:
            for sid in all_seasons:
                pairs.add((sid, lid))

        stats_url = f"{ARCL_BASE}/Pages/UI/Statistics.aspx"
        soup = await _get(stats_url, client)
        if soup:
            for a in soup.find_all("a", href=True):
                m = re.search(r'season_id=(\d+).*league_id=(\d+)', a["href"])
                if m:
                    sid, lid = int(m.group(1)), int(m.group(2))
                    if (not league_filter or lid in league_filter) and \
                       (not season_filter or sid in season_filter):
                        pairs.add((sid, lid))

        logger.info(f"Checking {len(pairs)} season/league combinations...")

        standings_sem = asyncio.Semaphore(8)

        async def fetch_standings_limited(season_id, league_id):
            async with standings_sem:
                return season_id, league_id, await _fetch_divhome_standings(season_id, league_id, client)

        tasks = [fetch_standings_limited(sid, lid) for sid, lid in sorted(pairs, reverse=True)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_team_refs = []
        for result in results:
            if isinstance(result, Exception):
                continue
            season_id, league_id, (standings, team_refs) = result

            for r in standings:
                key = (r["team_name"], r["season"], r["division"])
                if key in seen_standings:
                    continue
                seen_standings.add(key)

                content = (
                    f"Team: {r['team_name']}. Season: {r['season']}. "
                    f"Division: {r['division']}. Wins: {r['wins']}. "
                    f"Losses: {r['losses']}. Tied: {r['tied']}. Points: {r['points']}."
                )
                standings_chunks.append(ScrapedChunk(
                    content=content, source_url=r["source_url"],
                    page_type="team", team_name=r["team_name"],
                    team_id=r.get("team_id"), season=r["season"],
                    season_id=season_id, league_id=league_id, division=r["division"],
                    extra={
                        "wins": r["wins"], "losses": r["losses"],
                        "tied": r["tied"], "points": r["points"],
                        "team_id": r.get("team_id"),
                    },
                ))
            all_team_refs.extend(team_refs)

        logger.info(f"Standings done: {len(standings_chunks)} records")

        if scrape_team_stats_too:
            unique_refs = []
            for ref in all_team_refs:
                key = (ref["team_id"], ref["season_id"], ref["league_id"])
                if key not in seen_team_stats:
                    seen_team_stats.add(key)
                    unique_refs.append(ref)

            logger.info(f"Fetching TeamStats for {len(unique_refs)} team-seasons...")
            completed = 0
            teamstats_sem = asyncio.Semaphore(6)

            async def fetch_teamstats_limited(ref):
                nonlocal completed
                async with teamstats_sem:
                    chunks = await scrape_team_stats(
                        team_id=ref["team_id"], team_name=ref["team_name"],
                        league_id=ref["league_id"], season_id=ref["season_id"],
                        season_label=ref["season"], division=ref["division"],
                        client=client,
                    )
                    completed += 1
                    if completed % 20 == 0:
                        logger.info(f"  Progress: {completed}/{len(unique_refs)}")
                    return chunks

            teamstats_results = await asyncio.gather(
                *[fetch_teamstats_limited(ref) for ref in unique_refs],
                return_exceptions=True,
            )
            for result in teamstats_results:
                if isinstance(result, Exception):
                    continue
                player_season_chunks.extend(result)

            logger.info(f"TeamStats done: {len(player_season_chunks)} player-season records")

    return standings_chunks, player_season_chunks


async def scrape_all_standings(
    league_filter: list[int] = None,
    season_filter: list[int] = None,
) -> list[ScrapedChunk]:
    standings, _ = await scrape_all_standings_and_stats(
        scrape_team_stats_too=False,
        league_filter=league_filter,
        season_filter=season_filter,
    )
    return standings


# ─────────────────────────────────────────────────────────────────────────────
# RULES / FAQ
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sections(soup, source_url, page_type, league: str = 'general'):
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    chunks = []
    current_section = "General"
    current_text    = []

    # Detect umpiring-related sections to tag them explicitly
    UMPIRE_KEYWORDS = {
        "umpire", "umpiring", "no ball", "no-ball", "wide", "wides",
        "dead ball", "dead-ball", "run out", "appeal", "lbw", "decision",
        "signal", "bye", "leg bye", "penalty", "fielding restriction",
    }

    def is_umpire_related(text):
        t = text.lower()
        return any(kw in t for kw in UMPIRE_KEYWORDS)

    def save_current():
        if not current_text:
            return
        joined = " ".join(current_text)
        # Tag umpiring content explicitly so vector search finds it easily
        prefix = ""
        if is_umpire_related(current_section) or is_umpire_related(joined):
            prefix = f"[UMPIRING RULE — {current_section}] "
        for chunk in _chunk_text(joined):
            # Add league prefix so search can filter correctly
            league_prefix = ""
            if league == "women":
                league_prefix = "[WOMEN'S LEAGUE] "
            elif league == "men":
                league_prefix = "[MEN'S LEAGUE] "
            content = league_prefix + prefix + chunk
            chunks.append(ScrapedChunk(
                content=content,
                source_url=source_url,
                page_type=page_type,
                section=current_section,
                extra={
                    "is_umpiring": bool(prefix),
                    "league":      league,
                },
            ))

    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td"]):
        text = _clean(el.get_text())
        if not text or len(text) < 5:
            continue
        if el.name in ["h1", "h2", "h3", "h4"]:
            save_current()
            current_section = text
            current_text    = []
        else:
            current_text.append(text)

    save_current()
    return chunks


def _extract_faq(soup, source_url):
    chunks = []
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.endswith("?"):
            answer_parts, j = [], i + 1
            while j < len(lines) and not lines[j].endswith("?"):
                answer_parts.append(lines[j])
                j += 1
                if len(answer_parts) > 15:
                    break
            if answer_parts:
                chunks.append(ScrapedChunk(
                    content=f"Q: {line}\nA: {' '.join(answer_parts)}",
                    source_url=source_url, page_type="faq", section="FAQ",
                    extra={"question": line},
                ))
                i = j
                continue
        i += 1
    return chunks


async def scrape_arcl_rules() -> list[ScrapedChunk]:
    all_chunks = []
    async with httpx.AsyncClient() as client:
        for page in ARCL_SCRAPE_PAGES:
            url       = page["url"]
            page_type = page["type"]
            league    = page.get("league", "general")
            logger.info(f"Scraping {url} (league={league})...")
            soup = await _get(url, client)
            if not soup:
                continue
            if page_type == "faq":
                chunks = _extract_faq(soup, url)
            else:
                chunks = _extract_sections(soup, url, page_type, league=league)
            logger.info(f"  -> {len(chunks)} chunks")
            all_chunks.extend(chunks)
            time.sleep(random.uniform(0.3, 0.8))
    return all_chunks


# ─────────────────────────────────────────────────────────────────────────────
# PLAYERS
# ─────────────────────────────────────────────────────────────────────────────

async def _scrape_player_list_by_letter(letter, client):
    url = f"{ARCL_BASE}/Pages/UI/Players.aspx?player_alpha={letter}"
    soup = await _get(url, client)
    if not soup:
        return []
    players = []
    for a in soup.find_all("a", href=True):
        m = re.search(r'[Pp]layer[Hh]istory\.aspx\?.*player_id=(\d+)', a["href"])
        if m:
            pid = m.group(1)
            name = _clean(a.get_text())
            if name and pid:
                players.append({
                    "player_id": pid, "player_name": name,
                    "profile_url": f"{ARCL_BASE}/Pages/UI/PlayerHistory.aspx?player_id={pid}",
                })
    return players


async def _scrape_player_history(player, client):
    url = player["profile_url"]
    soup = await _get(url, client)
    if not soup:
        return None
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    teams, seasons = [], []
    for row in soup.find_all("tr"):
        cols = [_clean(td.get_text()) for td in row.find_all("td")]
        for col in cols:
            if re.match(r'(Spring|Summer|Fall|Winter)\s+\d{4}', col):
                seasons.append(col)
    for a in soup.find_all("a", href=True):
        if "TeamPlayers" in a["href"] or "TeamHistory" in a["href"]:
            t = _clean(a.get_text())
            if t and t not in teams:
                teams.append(t)

    text = _clean(soup.get_text(separator=" "))
    content = (
        f"Player: {player['player_name']}. Player ID: {player['player_id']}. "
        f"Teams: {', '.join(teams) if teams else 'see profile'}. "
        f"Seasons: {', '.join(set(seasons)) if seasons else 'multiple'}. "
        f"Profile: {player['profile_url']}. Summary: {text[:300]}"
    )
    return ScrapedChunk(
        content=content, source_url=url, page_type="player",
        player_name=player["player_name"], player_id=player["player_id"],
        extra={"teams": teams, "seasons": list(set(seasons)),
               "profile_url": player["profile_url"]},
    )


async def scrape_arcl_players(letters=string.ascii_uppercase) -> list[ScrapedChunk]:
    all_chunks = []
    async with httpx.AsyncClient() as client:
        for letter in letters:
            logger.info(f"Players '{letter}'...")
            players = await _scrape_player_list_by_letter(letter, client)
            for player in players:
                chunk = await _scrape_player_history(player, client)
                if chunk:
                    all_chunks.append(chunk)
                time.sleep(random.uniform(0.2, 0.5))
            time.sleep(random.uniform(0.3, 0.8))
    logger.info(f"Total player chunks: {len(all_chunks)}")
    return all_chunks


# ─────────────────────────────────────────────────────────────────────────────
# TEAMS
# ─────────────────────────────────────────────────────────────────────────────

async def _scrape_team_list_by_letter(letter, client):
    url = f"{ARCL_BASE}/Pages/UI/Teams.aspx?team_alpha={letter}"
    soup = await _get(url, client)
    if not soup:
        return []
    teams = []
    for a in soup.find_all("a", href=True):
        m = re.search(r'[Tt]eam[Hh]istory\.aspx\?.*team_name=([^&]+)', a["href"])
        if m:
            name = _clean(a.get_text())
            slug = m.group(1)
            if name:
                teams.append({
                    "team_name": name, "team_slug": slug,
                    "history_url": f"{ARCL_BASE}/Pages/UI/TeamHistory.aspx?team_name={slug}",
                })
    return teams


async def scrape_arcl_teams(letters=string.ascii_uppercase) -> list[ScrapedChunk]:
    all_chunks = []
    async with httpx.AsyncClient() as client:
        for letter in letters:
            logger.info(f"Teams '{letter}'...")
            teams = await _scrape_team_list_by_letter(letter, client)
            for team in teams:
                content = f"Team: {team['team_name']}. ARCL registered team. Profile: {team['history_url']}."
                all_chunks.append(ScrapedChunk(
                    content=content, source_url=team["history_url"],
                    page_type="team", team_name=team["team_name"],
                    extra={"team_slug": team["team_slug"]},
                ))
            time.sleep(random.uniform(0.3, 0.8))
    logger.info(f"Total team chunks: {len(all_chunks)}")
    return all_chunks


# ─────────────────────────────────────────────────────────────────────────────
# CSV FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_from_csv(filepath: str, page_type: str = "player") -> list[ScrapedChunk]:
    import csv
    chunks = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if page_type == "player":
                name = row.get("name", "").strip()
                team = row.get("team", "").strip()
                season = row.get("season", "").strip()
                content = f"Player: {name}. Team: {team}. Season: {season}."
                chunks.append(ScrapedChunk(content=content, source_url=filepath,
                    page_type="player", player_name=name, team_name=team, season=season))
            elif page_type == "team":
                team = row.get("team_name", "").strip()
                season = row.get("season", "").strip()
                division = row.get("division", "").strip()
                wins = row.get("wins", "0").strip()
                losses = row.get("losses", "0").strip()
                points = row.get("points", "0").strip()
                content = f"Team: {team}. Season: {season}. Division: {division}. Wins: {wins}. Losses: {losses}. Points: {points}."
                chunks.append(ScrapedChunk(content=content, source_url=filepath,
                    page_type="team", team_name=team, season=season, division=division,
                    extra={"wins": wins, "losses": losses, "points": points}))
    logger.info(f"Loaded {len(chunks)} records from {filepath}")
    return chunks