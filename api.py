import re
import logging
import aiohttp
from typing import Any
from config import SPORTS_URL, EVENTS_URL, FOOTBALL_SPORT_ID, HEADERS, COOKIES, TOKEN_REFRESH_URL

logger = logging.getLogger(__name__)

# Mutable token state — shared across all requests
_auth_state: dict = {
    "authorization": HEADERS["authorization"],
    "session": COOKIES["session"],
}


async def _refresh_token() -> None:
    """Fetch a fresh anonymous token from the main page."""
    headers = {
        "user-agent": HEADERS["user-agent"],
        "accept": "text/html",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(TOKEN_REFRESH_URL) as resp:
            html = await resp.text()

    m_token = re.search(r"'internalToken':'([^']+)'", html)
    m_session = re.search(r"'sessionToken':'([^']+)'", html)
    if not m_token or not m_session:
        raise RuntimeError("No se pudieron extraer los tokens del HTML")

    _auth_state["authorization"] = m_token.group(1)
    _auth_state["session"] = m_session.group(1)
    logger.info("Token renovado exitosamente.")


async def _get(url: str, params: dict | None = None) -> Any:
    for attempt in range(2):
        headers = {**HEADERS, "authorization": _auth_state["authorization"]}
        cookies = {"session": _auth_state["session"], "authorization": _auth_state["authorization"]}
        async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 401 and attempt == 0:
                    logger.warning("Token expirado, renovando...")
                    await _refresh_token()
                    continue
                resp.raise_for_status()
                return await resp.json()


class Match:
    __slots__ = (
        "event_id", "league_id", "league_name", "country",
        "home", "away", "name", "start_time", "is_live", "game_time",
        "odds_home", "odds_draw", "odds_away",
        "hc_value", "hc_home", "hc_away",
    )

    def __init__(self, ev: list):
        self.event_id: str = str(ev[0])
        self.league_id: str = str(ev[1])
        self.league_name: str = ev[2]
        self.country: str = ev[7]
        self.home: str = ev[8][0][1].get("ES", ev[8][0][1].get("EN", "?"))
        self.away: str = ev[8][1][1].get("ES", ev[8][1][1].get("EN", "?"))
        self.name: str = ev[10]
        self.start_time: str = ev[11]
        self.is_live: bool = bool(ev[13])
        clock = ev[15] if len(ev) > 15 and isinstance(ev[15], dict) else {}
        raw = clock.get("GameTime", 0)
        self.game_time: int = int(raw) if raw else 0
        self.odds_home: float | None = None
        self.odds_draw: float | None = None
        self.odds_away: float | None = None
        self.hc_value: float | None = None
        self.hc_home: float | None = None
        self.hc_away: float | None = None
        if len(ev) > 19 and ev[19]:
            self._parse_odds(ev[19])

    def _parse_odds(self, markets: list) -> None:
        # 1) Try 1X2
        for mkt in markets:
            if not (isinstance(mkt[0], str) and mkt[0].startswith("0ML")):
                continue
            sels = mkt[7] if len(mkt) > 7 else []
            if len(sels) < 3:
                continue
            for sel in sels:
                pos = sel[7] if len(sel) > 7 else None
                odds = sel[4] if len(sel) > 4 else None
                if pos == 1:
                    self.odds_home = odds
                elif pos == 2:
                    self.odds_draw = odds
                elif pos == 3:
                    self.odds_away = odds
            if self.odds_home and self.odds_draw and self.odds_away:
                return

        # 2) Fallback: Asian Handicap main line
        for mkt in markets:
            if not (isinstance(mkt[0], str) and mkt[0].startswith("0HC")):
                continue
            # skip corners markets
            name = str(mkt[1]).lower()
            if "corner" in name or "córner" in name or "rners" in name:
                continue
            sels = mkt[7] if len(mkt) > 7 else []
            for sel in sels:
                tags = sel[14] if len(sel) > 14 else []
                if "MainPointLine" not in tags:
                    continue
                pos = sel[7] if len(sel) > 7 else None
                odds = sel[4] if len(sel) > 4 else None
                hcap = sel[13] if len(sel) > 13 else None
                if pos == 1 and odds:
                    self.hc_home = odds
                    self.hc_value = hcap  # negative = home is favored
                elif pos == 3 and odds:
                    self.hc_away = odds
            if self.hc_home and self.hc_away:
                return


class League:
    __slots__ = ("league_id", "name", "country", "country_code", "events_qty")

    def __init__(self, raw: dict):
        self.league_id: str = str(raw["_id"])
        self.name: str = raw["LeagueName"]
        self.country: str = raw["RegionName"]
        self.country_code: str = raw.get("RegionCode", "")
        self.events_qty: int = raw.get("eventsQuantity", 0)


class Country:
    __slots__ = ("country_id", "name", "code", "events_qty")

    def __init__(self, raw: dict):
        self.country_id: str = str(raw["_id"])
        self.name: str = raw["RegionName"]
        self.code: str = raw.get("RegionCode", "")
        self.events_qty: int = raw.get("eventsQuantity", 0)


async def get_football_countries() -> list[Country]:
    data = await _get(SPORTS_URL)
    sports = data.get("data", [])
    football = next((s for s in sports if s["_id"] == FOOTBALL_SPORT_ID), None)
    if not football:
        return []
    return [Country(c) for c in football.get("countries", [])]


async def get_leagues_by_country(country_id: str) -> tuple[Country | None, list[League]]:
    data = await _get(SPORTS_URL)
    sports = data.get("data", [])
    football = next((s for s in sports if s["_id"] == FOOTBALL_SPORT_ID), None)
    if not football:
        return None, []
    for raw_country in football.get("countries", []):
        if str(raw_country["_id"]) == country_id:
            country = Country(raw_country)
            leagues = []
            for raw_league in raw_country.get("Leagues", []):
                raw_league["RegionCode"] = raw_country.get("RegionCode", "")
                leagues.append(League(raw_league))
            return country, leagues
    return None, []


async def get_football_leagues() -> list[League]:
    data = await _get(SPORTS_URL)
    sports = data.get("data", [])
    football = next((s for s in sports if s["_id"] == FOOTBALL_SPORT_ID), None)
    if not football:
        return []
    leagues: list[League] = []
    for country in football.get("countries", []):
        code = country.get("RegionCode", "")
        for raw_league in country.get("Leagues", []):
            raw_league["RegionCode"] = code
            leagues.append(League(raw_league))
    return leagues


FEMALE_KEYWORDS = ["women", "[w]", "femenin", "mujeres", "ladies", "feminin", "girl", "damas"]


async def get_female_leagues() -> list[League]:
    all_leagues = await get_football_leagues()
    result = []
    for lg in all_leagues:
        combined = (lg.name + " " + lg.country).lower()
        if any(kw in combined for kw in FEMALE_KEYWORDS):
            if "[v]" not in lg.name.lower() and lg.country != "V-Soccer":
                result.append(lg)
    return result


async def search_leagues(query: str) -> list[League]:
    all_leagues = await get_football_leagues()
    q = query.lower()
    return [
        lg for lg in all_leagues
        if q in lg.name.lower() or q in lg.country.lower()
    ]


import re as _re
import unicodedata as _ud

# Palabras genéricas que no sirven como identificador único de equipo
_COMMON_WORDS = {"fc", "cf", "sc", "ac", "rc", "cd", "sd", "sk", "fk", "bk",
                 "de", "del", "la", "el", "los", "club", "sport", "town"}


def _normalize(s: str) -> str:
    """Lowercase, strip accents, remove gender tags and punctuation."""
    s = s.lower()
    s = _ud.normalize("NFD", s)
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    s = _re.sub(r"\[.{0,3}\]|\(.{0,3}\)", "", s)  # [W], [F], (F), (Fem), etc.
    s = _re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def _distinctive_words(s: str) -> set[str]:
    """Words that are actually identifying (not generic club suffixes)."""
    return {w for w in _normalize(s).split() if w not in _COMMON_WORDS and len(w) > 2}


def _match_score(query_team: str, candidate: str) -> float:
    """0.0–1.0 score. Requires distinctive-word overlap to avoid false positives."""
    q = _normalize(query_team)
    c = _normalize(candidate)
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.9
    qd = _distinctive_words(query_team)
    cd = _distinctive_words(candidate)
    if not qd:
        return 0.0
    overlap = len(qd & cd) / len(qd)
    # require at least one full distinctive word match
    if not (qd & cd):
        return 0.0
    return overlap


def _is_female(m: Match) -> bool:
    female_kw = ["[w]", "[f]", "(f)", "(w)", "femenin", "women", "mujeres",
                 "ladies", "feminin", "girl", "damas"]
    combined = (m.home + m.away + m.league_name).lower()
    return any(k in combined for k in female_kw)


async def search_match(
    home_query: str,
    away_query: str,
    gender: str | None = None,   # "F", "M", or None
) -> list[Match]:
    """
    Return football fixtures matching both team names.
    gender="F" filters to women's matches, "M" to men's, None returns all.
    """
    data = await _get(EVENTS_URL)
    events = data.get("data", [])
    results = []
    for ev in events:
        if len(ev) < 14 or str(ev[3]) != FOOTBALL_SPORT_ID:
            continue
        if len(ev) > 26 and ev[26] == "Outright":
            continue
        try:
            m = Match(ev)
        except (IndexError, KeyError, TypeError):
            continue
        # Excluir E-Fútbol (partidos virtuales con usernames)
        if ev[7] in ("E-Fútbol", "E-Football", "E-Soccer") or str(ev[5]) == "274":
            continue
        if gender == "F" and not _is_female(m):
            continue
        if gender == "M" and _is_female(m):
            continue
        h_score = _match_score(home_query, m.home)
        a_score = _match_score(away_query, m.away)
        if h_score >= 0.6 and a_score >= 0.6:
            results.append((h_score + a_score, m))
    results.sort(key=lambda x: -x[0])
    return [m for _, m in results[:5]]


async def get_events_for_leagues(league_ids: set[str]) -> list[Match]:
    data = await _get(EVENTS_URL)
    events = data.get("data", [])
    matches: list[Match] = []
    for ev in events:
        if len(ev) < 14:
            continue
        if str(ev[1]) in league_ids and str(ev[3]) == FOOTBALL_SPORT_ID:
            if len(ev) > 26 and ev[26] == "Outright":
                continue
            try:
                matches.append(Match(ev))
            except (IndexError, KeyError, TypeError):
                continue
    return matches
