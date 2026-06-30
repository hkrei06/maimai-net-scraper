"""
Shared maimai-net session + scraping.

This is the single home for two things:
  1. The auth chain + session (clal -> session cookies), replicating b50.py exactly
     (curl_cffi, ``chrome131`` impersonation, ``MAIMAI_CLAL``).
  2. The "essential" scrapers that turn a maimai-net page into plain dicts.

Everything else - the b50 generator and the Discord cogs - imports from here, so the
auth chain is written once and each scraper is written once. The scrapers are
synchronous; async callers (cogs) should wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from urllib.parse import quote

from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

CLAL = os.getenv("MAIMAI_CLAL", "").strip()
if CLAL.startswith("clal="):
    CLAL = CLAL[len("clal="):]

AIME_GW_LOGIN = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)
BASE_URL = "https://maimaidx-eng.com"
MOBILE = f"{BASE_URL}/maimai-mobile"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ── Auth + session (replicates b50.py exactly) ───────────────────────────────

_session: cffi_requests.Session | None = None
_cookies: str | None = None
_lock = threading.Lock()

# Cached {title, idx} list scraped from the song-list page once and reused until
# the idx expire (see get_song_index / IdxExpired below).
_song_index: list[dict] | None = None
_song_index_lock = threading.Lock()

# Cached player profile scraped from /home, refreshed when older than the TTL
# or when the session resets (see get_profile below).
PROFILE_TTL = 600  # seconds (10 min) — profile data (esp. rating) is volatile
_profile: dict | None = None
_profile_at: float = 0.0
_profile_lock = threading.Lock()


def validate_clal(session: cffi_requests.Session) -> str:
    """Step 1: send clal to aime-gw, return the 302 redirect URL."""
    print(f"[auth] step 1: validating clal (len={len(CLAL)}) -> {AIME_GW_LOGIN}")
    resp = session.get(
        AIME_GW_LOGIN,
        headers={"Cookie": f"clal={CLAL}", "User-Agent": USER_AGENT},
        allow_redirects=False,
    )
    print(f"[auth] step 1: status={resp.status_code}")
    if resp.status_code == 302:
        loc = resp.headers.get("Location", "")
        print(f"[auth] step 1: OK, redirect -> {loc[:80]}")
        return loc
    if resp.status_code == 200:
        print("[auth] step 1: FAILED - gateway returned 200, clal is expired/invalid")
        raise RuntimeError("clal has expired. Get a new one.")
    print(f"[auth] step 1: FAILED - unexpected status {resp.status_code}")
    raise RuntimeError(f"Unexpected status {resp.status_code} from aime-gw")


def get_session_cookies(session: cffi_requests.Session, redirect_url: str) -> str:
    """Step 2: follow the redirect, return the session cookie string."""
    resp = session.get(
        redirect_url,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=False,
    )
    print(f"[auth] step 2: exchanging redirect -> status={resp.status_code}")
    raw = resp.headers.get_list("Set-Cookie") if hasattr(resp.headers, "get_list") else []
    if not raw:
        sc = resp.headers.get("Set-Cookie", "")
        if sc:
            raw = [sc]
    if not raw:
        jar = {c.name: c.value for c in session.cookies}
        if jar:
            print(f"[auth] step 2: OK (from cookie jar): {', '.join(jar)}")
            return "; ".join(f"{k}={v}" for k, v in jar.items())
        print("[auth] step 2: FAILED - no cookies received")
        raise RuntimeError("No cookies received from redirect")
    names = [h.split("=", 1)[0] for h in raw]
    print(f"[auth] step 2: OK, got cookies: {', '.join(names)}")
    return "; ".join(h.split(";")[0] for h in raw)


def get_session() -> tuple[cffi_requests.Session, str]:
    """Return a cached (session, cookies) pair, running the auth chain once."""
    global _session, _cookies
    with _lock:
        if _session is None or _cookies is None:
            if not CLAL:
                raise RuntimeError("set MAIMAI_CLAL in .env (your clal cookie value)")
            print("[auth] no cached session - running auth chain...")
            session = cffi_requests.Session(impersonate="chrome131")
            redirect_url = validate_clal(session)
            _cookies = get_session_cookies(session, redirect_url)
            _session = session
            print("[auth] session established and cached")
        else:
            print("[auth] reusing cached session")
    return _session, _cookies


def reset_session() -> None:
    """Drop the cached session so the next call re-authenticates."""
    global _session, _cookies, _song_index, _profile
    with _lock:
        _session = None
        _cookies = None
        _song_index = None  # idx are session-scoped; force a fresh scrape
        _profile = None     # re-scrape /home after a fresh login


def _get(url: str, referer: str | None = None):
    """GET ``url`` with the authed session (following redirects).

    Resets the session and raises if maimai-net bounced us to the auth gateway
    (expired session). Returns the raw response so callers can inspect the final
    URL — e.g. to detect an idx that bounced back to the song list.
    """
    session, cookies = get_session()
    headers = {"Cookie": cookies, "User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    print(f"[scrap] GET {url}")
    resp = session.get(url, headers=headers, allow_redirects=True)
    print(f"[scrap] -> status={resp.status_code} bytes={len(resp.content)} url={resp.url}")
    if resp.status_code != 200 or "common_auth" in str(resp.url):
        print("[scrap] bounced to auth - session expired, resetting")
        reset_session()
        raise RuntimeError("Session expired, please try the command again.")
    return resp


def fetch_html(url: str, referer: str | None = None) -> str:
    """GET ``url`` with the authed session and return the HTML."""
    return _get(url, referer).text


# ── Scrapers (HTML -> dicts) ─────────────────────────────────────────────────

def fetch_recent_scores(limit: int = 20) -> list[dict]:
    """Recent plays from the playlog page."""
    soup = BeautifulSoup(fetch_html(f"{MOBILE}/record/"), "html.parser")

    plays = []
    for entry in soup.select("div.p_10.t_l.f_0.v_b"):
        play: dict = {}

        top = entry.select_one(".playlog_top_container")
        if top:
            diff_img = top.select_one(".playlog_diff")
            if diff_img:
                play["difficulty"] = diff_img["src"].split("diff_")[1].replace(".png", "").upper()
            track_span = top.select_one(".red.f_b")
            date_span = top.select_one(".sub_title .v_b")
            play["track"] = track_span.text.strip() if track_span else None
            play["date"] = date_span.text.strip() if date_span else None

        title_block = entry.select_one(".basic_block.m_5")
        if title_block:
            level_div = title_block.select_one(".playlog_level_icon")
            play["level"] = level_div.text.strip() if level_div else None
            if level_div:
                level_div.extract()
            play["title"] = title_block.get_text(strip=True)

        achievement = entry.select_one(".playlog_achievement_txt")
        play["achievement"] = achievement.text.strip() if achievement else None

        rank_img = entry.select_one(".playlog_scorerank")
        play["rank_img"] = rank_img["src"] if rank_img else None

        dx_block = entry.select_one(".playlog_score_block_star .white")
        play["dx_score"] = dx_block.text.strip() if dx_block else None

        play["is_new_record"] = bool(entry.select_one(".playlog_achievement_newrecord"))

        idx_input = entry.select_one("input[name='idx']")
        play["idx"] = idx_input["value"] if idx_input else None

        plays.append(play)

    return plays[:limit]


def fetch_songs_by_level(level: str) -> list[dict]:
    """All charts for a given level key (e.g. '21' = LEVEL 14)."""
    soup = BeautifulSoup(
        fetch_html(f"{MOBILE}/record/musicLevel/search/?level={level}"), "html.parser"
    )

    songs = []
    for entry in soup.select("div[class*='score_back']"):
        name_tag = entry.select_one(".music_name_block")
        idx_input = entry.select_one("input[name='idx']")
        lv_tag = entry.select_one(".music_lv_block")
        score_tag = entry.select_one(".music_score_block")

        if not name_tag or not idx_input:
            continue

        classes = " ".join(entry.get("class", []))
        if "remaster" in classes:
            diff = "Re:MASTER"
        elif "master" in classes:
            diff = "MASTER"
        elif "expert" in classes:
            diff = "EXPERT"
        elif "advanced" in classes:
            diff = "ADVANCED"
        else:
            diff = "BASIC"

        songs.append({
            "title": name_tag.get_text(strip=True),
            "diff": diff,
            "level": lv_tag.get_text(strip=True) if lv_tag else "?",
            "score": score_tag.get_text(strip=True) if score_tag else None,
            "idx": idx_input["value"],
        })

    return songs


# ── Cached song idx index ────────────────────────────────────────────────────
#
# The song-list page lists every song with its ``idx`` (a per-session token used
# to open that song's detail page). We scrape it once and reuse the idx until
# they expire. An idx is "expired" when opening musicDetail bounces back to the
# bare musicGenre list page; ``fetch_song_detail`` raises ``IdxExpired`` then,
# and callers refresh the index with ``get_song_index(force=True)``.

SONG_LIST_URL = f"{MOBILE}/record/musicGenre/search/?genre=99&diff=3"


class IdxExpired(RuntimeError):
    """Raised when a musicDetail request bounced back to the song list."""


def _scrape_song_index() -> list[dict]:
    soup = BeautifulSoup(fetch_html(SONG_LIST_URL), "html.parser")
    songs = []
    for name_div in soup.select("div.music_name_block"):
        form = name_div.find_parent("form")
        idx_input = form.find("input", {"name": "idx"}) if form else None
        if not idx_input:
            continue
        songs.append({"title": name_div.get_text(strip=True), "idx": idx_input["value"]})
    return songs


def get_song_index(force: bool = False) -> list[dict]:
    """Cached {title, idx} list: scraped once, reused until forced to refresh."""
    global _song_index
    with _song_index_lock:
        if force or _song_index is None:
            _song_index = _scrape_song_index()
            print(f"[scrap] cached {len(_song_index)} song idx")
        return _song_index


def fetch_song_by_name(name: str, exact: bool = False) -> list[dict]:
    """Match songs against the cached idx index (no network unless cache empty).

    ``exact`` matches the title case-insensitively in full; otherwise substring.
    """
    target = name.lower()
    results = []
    for song in get_song_index():
        title = song["title"]
        if exact:
            if title.lower() != target:
                continue
        elif target not in title.lower():
            continue
        results.append({"title": title, "idx": song["idx"]})
    return results


def fetch_live_detail_by_name(name: str, exact: bool = True) -> dict | None:
    """Look up a song's idx from the cached index and fetch its live detail.

    Returns ``None`` if no title matches. If the cached idx has expired, refreshes
    the whole index once and retries before giving up.
    """
    matches = fetch_song_by_name(name, exact)
    if not matches:
        return None
    try:
        return fetch_song_detail(matches[0]["idx"])
    except IdxExpired:
        print("[scrap] idx expired - refreshing song index and retrying")
        get_song_index(force=True)
        matches = fetch_song_by_name(name, exact)
        if not matches:
            return None
        return fetch_song_detail(matches[0]["idx"])


def encode_idx(idx: str) -> str:
    """URL-encode an idx from its first non-alphanumeric char to the end.

    The leading alphanumeric run is left untouched; everything from the first
    special char (e.g. ``/``, ``+``, ``=``) onward is percent-encoded as UTF-8.
    """
    for i, ch in enumerate(idx):
        if not (ch.isascii() and ch.isalnum()):
            return idx[:i] + quote(idx[i:], safe="", encoding="utf-8")
    return idx


# ── Player profile (scraped once from /home) ─────────────────────────────────
#
# The /home page carries the player header: icon, name, rating frame + value,
# course rank and class rank. Class names are stable across users; only the
# image filenames (costume/rank artwork) differ per account, so we select by
# stable class/path and read the per-user src/text. Scraped once and cached
# (cleared on reset_session) so commands don't re-fetch /home every time.

HOME_URL = f"{MOBILE}/home/"


def _img_src(node) -> str:
    """Absolute src of an <img> node (prefix BASE_URL if relative), else ''."""
    if not node:
        return ""
    src = node.get("src", "")
    if src and not src.startswith("http"):
        src = f"{BASE_URL}{src}"
    return src


def _img_data_uri(url: str) -> str:
    """Download a maimai image URL and return it as a base64 ``data:`` URI.

    Profile/rank art lives on maimai's server. Embedding it (rather than passing
    a remote URL to the template) is what makes it render reliably: Playwright
    often screenshots before a remote <img> finishes loading. Returns '' on any
    failure so a missing image degrades gracefully instead of breaking profile.
    """
    if not url:
        return ""
    try:
        session, cookies = get_session()
        resp = session.get(url, headers={"Cookie": cookies, "User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return ""
        mime = (resp.headers.get("Content-Type") or "image/png").split(";")[0].strip()
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


def _scrape_profile() -> dict:
    soup = BeautifulSoup(fetch_html(HOME_URL, referer=f"{MOBILE}/"), "html.parser")
    block = soup.select_one(".see_through_block .basic_block")
    if not block:
        raise RuntimeError("could not find the profile block on /home")

    name_el = block.select_one(".name_block")
    rating_el = block.select_one(".rating_block")
    # Images are embedded as data URIs so they render in the Playwright shot.
    return {
        "icon_url":         _img_data_uri(_img_src(block.select_one("img[src*='/Icon/']"))),
        "name":             name_el.get_text(strip=True) if name_el else "",
        "rating":           rating_el.get_text(strip=True) if rating_el else "",
        "rating_frame_url": _img_data_uri(_img_src(block.select_one("img[src*='/rating_base_']"))),
        "course_rank_url":  _img_data_uri(_img_src(block.select_one("img[src*='/course/course_rank_']"))),
        "class_rank_url":   _img_data_uri(_img_src(block.select_one("img[src*='/class/class_rank_']"))),
    }


def get_profile(force: bool = False) -> dict:
    """Cached player profile from /home, re-scraped when stale.

    Returns ``icon_url``, ``name``, ``rating`` (string), ``rating_frame_url``,
    ``course_rank_url`` and ``class_rank_url``. Re-scraped when the cache is older
    than ``PROFILE_TTL`` (so profile/rating changes show within ~10 min) or after
    ``reset_session`` clears it. Pass ``force=True`` to re-scrape immediately.
    """
    global _profile, _profile_at
    with _profile_lock:
        if force or _profile is None or time.time() - _profile_at > PROFILE_TTL:
            _profile = _scrape_profile()
            _profile_at = time.time()
            # Don't print the raw name: it may be full-width/JP and crash a
            # non-UTF-8 console (e.g. cp1252), which would kill the profile fetch.
            print(f"[scrap] cached profile (rating {_profile['rating']})")
        return _profile


def fetch_song_detail(idx: str) -> dict:
    """Title, artist, genre and all difficulty scores for a song idx.

    Raises ``IdxExpired`` if the idx has expired: maimai-net redirects an expired
    idx back to the musicGenre song-list page instead of the detail page.
    """
    resp = _get(f"{MOBILE}/record/musicDetail/?idx={encode_idx(idx)}")
    if "record/musicGenre" in str(resp.url):
        print("[scrap] idx expired (bounced to musicGenre)")
        raise IdxExpired("idx expired")
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.select_one(".m_5.f_15.break")
    artist = soup.select_one(".m_5.f_12.break")
    genre = soup.select_one(".m_10.m_t_5.t_r.f_12.blue")

    diff_ids = [
        ("basic", "BASIC"),
        ("advanced", "ADVANCED"),
        ("expert", "EXPERT"),
        ("master", "MASTER"),
        ("remaster", "Re:MASTER"),
    ]
    difficulties = []
    for block_id, diff_name in diff_ids:
        block = soup.select_one(f"div#{block_id}")
        if not block:
            continue

        lv_tag = block.select_one(".music_lv_back")
        score_tag = block.select_one(".music_score_block.w_120")

        difficulties.append({
            "diff": diff_name,
            "level": lv_tag.get_text(strip=True) if lv_tag else "?",
            "score": score_tag.get_text(strip=True) if score_tag else None,
        })

    return {
        "title": title.get_text(strip=True) if title else "Unknown",
        "artist": artist.get_text(strip=True) if artist else "Unknown",
        "genre": genre.get_text(strip=True) if genre else "Unknown",
        "difficulties": difficulties,
    }


def fetch_friend_list() -> list[dict]:
    """Friends with name, rating and idx."""
    soup = BeautifulSoup(fetch_html(f"{MOBILE}/friend/"), "html.parser")

    friends = []
    for block in soup.select("div.see_through_block"):
        name_div = block.select_one(".name_block")
        rating_div = block.select_one(".rating_block")
        detail_form = block.select_one("form[action*='friendDetail']")

        if not name_div or not detail_form:
            continue

        idx_input = detail_form.select_one("input[name='idx']")

        friends.append({
            "name": name_div.text.strip(),
            "rating": rating_div.text.strip() if rating_div else "N/A",
            "idx": idx_input["value"] if idx_input else None,
        })

    return friends
