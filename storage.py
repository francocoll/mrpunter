import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FAVORITES_FILE = DATA_DIR / "favorites.json"
SEEN_FILE = DATA_DIR / "seen_matches.json"


def _load(path: Path, default) -> dict | list:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path: Path, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ── Favorites ────────────────────────────────────────────────────────────────
# Structure: { league_id: { "name": str, "country": str } }

def load_favorites() -> dict[str, dict]:
    return _load(FAVORITES_FILE, {})


def save_favorites(favorites: dict[str, dict]) -> None:
    _save(FAVORITES_FILE, favorites)


def add_favorite(league_id: str, name: str, country: str) -> bool:
    favs = load_favorites()
    if league_id in favs:
        return False
    favs[league_id] = {"name": name, "country": country}
    save_favorites(favs)
    return True


def remove_favorite(league_id: str) -> bool:
    favs = load_favorites()
    if league_id not in favs:
        return False
    del favs[league_id]
    save_favorites(favs)
    return True


# ── Subscribers ──────────────────────────────────────────────────────────────
# Structure: list of chat_id integers

SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"


def load_subscribers() -> set[int]:
    return set(_load(SUBSCRIBERS_FILE, []))


def add_subscriber(chat_id: int) -> None:
    subs = load_subscribers()
    subs.add(chat_id)
    _save(SUBSCRIBERS_FILE, list(subs))


def remove_subscriber(chat_id: int) -> None:
    subs = load_subscribers()
    subs.discard(chat_id)
    _save(SUBSCRIBERS_FILE, list(subs))


# ── Seen matches ─────────────────────────────────────────────────────────────
# Structure: list of event_id strings

def load_seen() -> set[str]:
    return set(_load(SEEN_FILE, []))


def save_seen(seen: set[str]) -> None:
    _save(SEEN_FILE, list(seen))


def mark_seen(event_ids: list[str]) -> None:
    seen = load_seen()
    seen.update(event_ids)
    save_seen(seen)


# ── Odds cache ────────────────────────────────────────────────────────────────
# Structure: { event_id: { "initial": snap, "current": snap } }
# "initial" = first observed odds (baseline for % comparison)
# "current" = last observed odds (updated every poll)
# After a notification is sent, "initial" is reset to "current".

ODDS_FILE = DATA_DIR / "odds_cache.json"


def load_odds_cache() -> dict[str, dict]:
    return _load(ODDS_FILE, {})


def save_odds_cache(cache: dict[str, dict]) -> None:
    _save(ODDS_FILE, cache)


# ── Watchlist ─────────────────────────────────────────────────────────────────
# Structure: [ { "id": str, "home": str, "away": str, "event_id": str|null } ]

WATCHLIST_FILE = DATA_DIR / "watchlist.json"


def load_watchlist() -> list[dict]:
    return _load(WATCHLIST_FILE, [])


def save_watchlist(wl: list[dict]) -> None:
    _save(WATCHLIST_FILE, wl)


def add_watch(
    home: str,
    away: str,
    gender: str | None = None,
    event_id: str | None = None,
    notified: bool = False,
) -> str:
    import uuid
    wl = load_watchlist()
    wid = uuid.uuid4().hex[:8]
    wl.append({"id": wid, "home": home, "away": away, "gender": gender, "event_id": event_id, "notified": notified})
    save_watchlist(wl)
    return wid


def remove_watch(wid: str) -> bool:
    wl = load_watchlist()
    new = [w for w in wl if w["id"] != wid]
    if len(new) == len(wl):
        return False
    save_watchlist(new)
    return True
