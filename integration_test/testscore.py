"""Prototype: type a song name -> get its scores.

Verifies the "scrape idx once" idea. It fetches the full song list a single
time, caches title -> idx, then reuses those idx for every musicDetail lookup
in the same session. If detail keeps working for many different songs without
re-scraping the list, the cache approach is sound and can move into scrapv2.

Reuses testauth's proven curl_cffi auth chain (impersonate + clal).

Usage:
    python testscore.py        (needs MAIMAI_CLAL in .env)
"""
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from testauth import (
    CLAL,
    BASE_URL,
    USER_AGENT,
    validate_clal,
    get_session_cookies,
)

GENRE_URL  = f"{BASE_URL}/maimai-mobile/record/musicGenre/search/?genre=99&diff=3"
DETAIL_URL = f"{BASE_URL}/maimai-mobile/record/musicDetail/?idx="

DIFF_BLOCKS = [
    ("basic",    "BASIC"),
    ("advanced", "ADVANCED"),
    ("expert",   "EXPERT"),
    ("master",   "MASTER"),
    ("remaster", "Re:MASTER"),
]


def build_idx_map(session, cookies: str) -> dict[str, str]:
    """One request: scrape the whole list into {title: idx}."""
    resp = session.get(
        GENRE_URL,
        headers={"Cookie": cookies, "User-Agent": USER_AGENT,
                 "Referer": f"{BASE_URL}/maimai-mobile/"},
    )
    soup = BeautifulSoup(resp.text, "html.parser")

    idx_map: dict[str, str] = {}
    for name_div in soup.select("div.music_name_block"):
        form = name_div.find_parent("form")
        if not form:
            continue
        idx_input = form.find("input", {"name": "idx"})
        if not idx_input:
            continue
        idx_map[name_div.get_text(strip=True)] = idx_input["value"]
    return idx_map


def encode_idx(idx: str) -> str:
    """URL-encode an idx from its first non-alphanumeric char to the end.

    The leading alphanumeric run is left untouched; everything from the first
    special char (e.g. ``/``, ``+``, ``=``) onward is percent-encoded as UTF-8.
    """
    for i, ch in enumerate(idx):
        if not (ch.isascii() and ch.isalnum()):
            return idx[:i] + quote(idx[i:], safe="", encoding="utf-8")
    print(idx)
    return idx


def fetch_detail(session, cookies: str, idx: str):
    """Fetch musicDetail for a cached idx, return (title, [(diff, lv, score)])."""
    resp = session.get(
        DETAIL_URL + encode_idx(idx),
        headers={"Cookie": cookies, "User-Agent": USER_AGENT,
                 "Referer": f"{BASE_URL}/maimai-mobile/"},
    )
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.select_one(".m_5.f_15.break")
    rows = []
    for block_id, name in DIFF_BLOCKS:
        block = soup.select_one(f"div#{block_id}")
        if not block:
            continue
        lv    = block.select_one(".music_lv_back")
        score = block.select_one(".music_score_block.w_120")
        rows.append((
            name,
            lv.get_text(strip=True) if lv else "?",
            score.get_text(strip=True) if score else "—",
        ))
    return (title.get_text(strip=True) if title else "Unknown"), rows


def find_title(idx_map: dict[str, str], query: str) -> str | None:
    """Exact (case-insensitive) match first, else first substring match."""
    ql = query.lower()
    for t in idx_map:
        if t.lower() == ql:
            return t
    for t in idx_map:
        if ql in t.lower():
            return t
    return None


def main():
    if not CLAL:
        print("Error: set MAIMAI_CLAL in .env")
        return

    session = cffi_requests.Session(impersonate="chrome131")
    redirect = validate_clal(session)
    cookies = get_session_cookies(session, redirect)

    print("\nScraping full song list once...")
    idx_map = build_idx_map(session, cookies)
    print(f"Cached {len(idx_map)} songs. The list is NOT fetched again.\n")

    while True:
        query = input("Song name (blank to quit): ").strip()
        if not query:
            break

        title = find_title(idx_map, query)
        if not title:
            print("  not found in list\n")
            continue

        try:
            name, rows = fetch_detail(session, cookies, idx_map[title])
        except Exception as e:
            print(f"  error: {e}\n")
            continue

        print(f"\n  {name}   (idx={idx_map[title]})")
        for diff, lv, score in rows:
            print(f"    {diff:<10} Lv{lv:<5} {score}")
        print()

    session.close()


if __name__ == "__main__":
    main()
