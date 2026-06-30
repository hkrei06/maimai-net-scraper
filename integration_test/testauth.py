"""
maimai DX album scraper — replicates tomomai's auth chain.

Auth chain:
  1. GET aime-gw with Cookie: clal=<value>, redirect=manual → 302 → Location header
  2. GET redirect URL, redirect=manual → Set-Cookie → session cookies
  3. GET /maimai-mobile/playerData/photo/ with session cookies → album HTML
  4. Parse album HTML with BeautifulSoup (same selectors as tomomai's cheerio)

Usage:
  export MAIMAI_CLAL="your_clal_cookie_value_here"
  python fetch_albums.py
"""

import os
import re
import json
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta

from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv

# ── Config ──────────────────────────────────────────────────────────────────

load_dotenv()

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
ALBUM_URL = f"{BASE_URL}/maimai-mobile/playerData/photo/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
JST = timezone(timedelta(hours=9))


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class AlbumData:
    song_name: str
    music_type: str        # "dx" | "std"
    difficulty: str        # basic/advanced/expert/master/remaster/utage
    taken_at: str          # ISO 8601
    image_url: str
    venue: str | None


# ── Helpers ─────────────────────────────────────────────────────────────────

def normalize_name(text: str) -> str:
    """NFKC normalize + strip, same as tomomai's normalizeName."""
    return unicodedata.normalize("NFKC", text).strip()


def music_type_from_icon(icon_src: str | None) -> str | None:
    """Same logic as tomomai's musicTypeFromIcon."""
    if not icon_src:
        return None
    if "music_dx.png" in icon_src:
        return "dx"
    if "music_standard.png" in icon_src:
        return "std"
    return None


def difficulty_from_class(class_str: str) -> str:
    """Same priority as tomomai's difficulty detection."""
    for diff in ("utage", "remaster", "master", "expert", "advanced", "basic"):
        if diff in class_str:
            return diff
    return "basic"


# ── Auth chain ──────────────────────────────────────────────────────────────

def validate_clal(session: cffi_requests.Session) -> str:
    """
    Step 1: send clal to aime-gw, get 302 redirect URL.
    Returns the redirect URL (contains ssid exchange params).
    """
    print(f"[1/3] Validating clal (length={len(CLAL)})...")

    resp = session.get(
        AIME_GW_LOGIN,
        headers={
            "Cookie": f"clal={CLAL}",
            "User-Agent": USER_AGENT,
        },
        allow_redirects=False,
    )

    if resp.status_code == 302:
        redirect_url = resp.headers.get("Location", "")
        print(f"      ✓ clal valid → redirect to {redirect_url[:80]}...")
        return redirect_url
    elif resp.status_code == 200:
        raise RuntimeError("clal has expired. Get a new one.")
    else:
        raise RuntimeError(f"Unexpected status {resp.status_code} from aime-gw")


def get_session_cookies(session: cffi_requests.Session, redirect_url: str) -> str:
    """
    Step 2: follow redirect URL (manual), extract Set-Cookie → session cookie string.
    Same as tomomai's getCookiesFromRedirect.
    """
    print("[2/3] Exchanging redirect for session cookies...")

    resp = session.get(
        redirect_url,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=False,
    )

    print(f"      Response status: {resp.status_code}")

    # Extract Set-Cookie headers — curl_cffi exposes them via resp.headers
    # which may merge them. Use the cookie jar instead for reliability.
    raw_set_cookies = resp.headers.get_list("Set-Cookie") if hasattr(resp.headers, "get_list") else []

    # Fallback: parse from the single Set-Cookie if get_list unavailable
    if not raw_set_cookies:
        sc = resp.headers.get("Set-Cookie", "")
        if sc:
            raw_set_cookies = [sc]

    if not raw_set_cookies:
        # Last resort: check if curl_cffi auto-populated the cookie jar
        jar_cookies = {c.name: c.value for c in session.cookies}
        if jar_cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in jar_cookies.items())
            print(f"      ✓ Got {len(jar_cookies)} cookies from jar")
            return cookie_str
        raise RuntimeError("No cookies received from redirect")

    # Parse name=value from each Set-Cookie (strip attributes after ';')
    cookies = "; ".join(h.split(";")[0] for h in raw_set_cookies)
    print(f"      ✓ Got {len(raw_set_cookies)} Set-Cookie header(s)")
    return cookies


def fetch_album_html(session: cffi_requests.Session, cookies: str) -> str:
    """
    Step 3: GET album page with session cookies.
    Same as tomomai's maimaiGetHtml for the album URL.
    """
    print("[3/3] Fetching album page...")

    resp = session.get(
        ALBUM_URL,
        headers={
            "Cookie": cookies,
            "User-Agent": USER_AGENT,
            "Referer": f"{BASE_URL}/maimai-mobile/",
        },
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Album page returned HTTP {resp.status_code}")

    html = resp.text
    print(f"      ✓ Got {len(html)} chars of HTML")
    return html


# ── Parse ───────────────────────────────────────────────────────────────────

def parse_albums(html: str) -> list[AlbumData]:
    """
    Parse album HTML using same selectors as tomomai's fetchAlbumData.
    Uses BeautifulSoup (cheerio equivalent).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    albums: list[AlbumData] = []

    # tomomai: $(".m_10.p_5.f_0")
    blocks = soup.select(".m_10.p_5.f_0")
    print(f"\nFound {len(blocks)} album blocks")

    for i, block in enumerate(blocks):
        try:
            # Song name: .black_block
            name_el = block.select_one(".black_block")
            if not name_el:
                print(f"  [!] Album {i}: no .black_block found, skipping")
                continue
            song_name = normalize_name(name_el.get_text())
            if not song_name:
                print(f"  [!] Album {i}: empty song name, skipping")
                continue

            # Difficulty: .p_r class string
            diff_el = block.select_one(".p_r")
            diff_class = " ".join(diff_el.get("class", [])) if diff_el else ""
            difficulty = difficulty_from_class(diff_class)

            # Music type: .music_kind_icon img src
            icon_el = block.select_one(".music_kind_icon")
            icon_src = icon_el.get("src") if icon_el else None
            if difficulty == "utage":
                music_type = "dx"
            else:
                music_type = music_type_from_icon(icon_src) or "std"

            # Taken at: .block_info → YYYY/MM/DD HH:MM
            info_el = block.select_one(".block_info")
            info_text = info_el.get_text().strip() if info_el else ""
            date_match = re.search(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", info_text)
            if not date_match:
                print(f"  [!] Album {i} ({song_name}): can't parse date from '{info_text}', skipping")
                continue
            y, mo, d, h, mi = date_match.groups()
            taken_at = datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=JST)

            # Image URL: img.w_430
            img_el = block.select_one("img.w_430")
            image_url = ""
            if img_el:
                src = img_el.get("src", "")
                image_url = src if src.startswith("http") else f"{BASE_URL}{src}"
            if not image_url:
                print(f"  [!] Album {i} ({song_name}): no image URL, skipping")
                continue

            # Venue: .see_through_block
            venue_el = block.select_one(".see_through_block")
            venue = venue_el.get_text().strip() or None if venue_el else None

            albums.append(AlbumData(
                song_name=song_name,
                music_type=music_type,
                difficulty=difficulty,
                taken_at=taken_at.isoformat(),
                image_url=image_url,
                venue=venue,
            ))

        except Exception as e:
            print(f"  [!] Album {i}: error — {e}")

    return albums


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    if not CLAL:
        print("Error: set MAIMAI_CLAL environment variable")
        print("  export MAIMAI_CLAL='your_clal_value'")
        return

    session = cffi_requests.Session(impersonate="chrome131")

    # Auth chain (same as tomomai)
    redirect_url = validate_clal(session)
    cookies = get_session_cookies(session, redirect_url)
    html = fetch_album_html(session, cookies)

    # Parse (same selectors as tomomai)
    albums = parse_albums(html)

    print(f"\n{'='*60}")
    print(f"Extracted {len(albums)} albums")
    print(f"{'='*60}\n")

    for album in albums:
        print(f"  {album.difficulty:>8} | {album.music_type:>3} | {album.song_name}")
        print(f"           {album.taken_at}  {album.venue or ''}")
        print(f"           {album.image_url[:80]}")
        print()



if __name__ == "__main__":
    main()