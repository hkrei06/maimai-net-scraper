import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# CONFIG
BASE_URL  = "https://maimaidx-eng.com/maimai-mobile"
SEGA_HOST = "lng-tgk-aime-gw.am-all.net"
MAI_HOST  = "maimaidx-eng.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/home/",
    "Accept-Language": "en-US,en;q=0.9",
}

LEVELS = {
    "1":  "LEVEL 1",   "2":  "LEVEL 2",   "3":  "LEVEL 3",
    "4":  "LEVEL 4",   "5":  "LEVEL 5",   "6":  "LEVEL 6",
    "7":  "LEVEL 7",   "8":  "LEVEL 7+",  "9":  "LEVEL 8",
    "10": "LEVEL 8+",  "11": "LEVEL 9",   "12": "LEVEL 9+",
    "13": "LEVEL 10",  "14": "LEVEL 10+", "15": "LEVEL 11",
    "16": "LEVEL 11+", "17": "LEVEL 12",  "18": "LEVEL 12+",
    "19": "LEVEL 13",  "20": "LEVEL 13+", "21": "LEVEL 14",
    "22": "LEVEL 14+", "23": "LEVEL 15",
}


# ──────────────────────────────────────────────
# SESSION SETUP
# ──────────────────────────────────────────────
def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)

    lng_raw = os.getenv("LNGCOOKIE")
    mai_raw = os.getenv("MAIMAI_COOKIES")

    if not lng_raw or not mai_raw:
        print("Missing LNGCOOKIE or MAIMAI_COOKIES in .env")
        exit(1)

    _, _, clal_value = lng_raw.partition("=")
    session.cookies.set("clal", clal_value.strip(), domain=SEGA_HOST)

    for part in mai_raw.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            session.cookies.set(name.strip(), value.strip(), domain=MAI_HOST)

    return session


def is_logged_in(session: requests.Session) -> bool:
    resp = session.get(f"{BASE_URL}/home/", allow_redirects=True)
    print(f"  Status   : {resp.status_code}")
    print(f"  Final URL: {resp.url}")
    return "maimaidx-eng.com/maimai-mobile/home" in resp.url


# ──────────────────────────────────────────────
# SCRAPING
# ──────────────────────────────────────────────
def fetch_songs_by_level(session: requests.Session, level: str) -> list:
    """Scrape song list for a given level. Always fetches fresh idx values."""
    url = f"{BASE_URL}/record/musicLevel/search/?level={level}"
    print(f"\n  Fetching fresh song list for {LEVELS.get(level, level)}...")

    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    songs = []
    entries = soup.select("div[class*='score_back']")

    for entry in entries:
        name_tag  = entry.select_one(".music_name_block")
        idx_input = entry.select_one("input[name='idx']")
        lv_tag    = entry.select_one(".music_lv_block")
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
            "diff":  diff,
            "level": lv_tag.get_text(strip=True) if lv_tag else "?",
            "score": score_tag.get_text(strip=True) if score_tag else "No score",
            "idx":   idx_input["value"],
        })

    print(f"  Found {len(songs)} songs.")
    return songs


def fetch_song_detail(session: requests.Session, idx: str) -> dict:
    """Fetch detail page for a specific song using its fresh idx."""
    url = f"{BASE_URL}/record/musicDetail/?idx={idx}"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    title  = soup.select_one(".m_5.f_15.break")
    artist = soup.select_one(".m_5.f_12.break")
    genre  = soup.select_one(".m_10.m_t_5.t_r.f_12.blue")

    return {
        "title":  title.get_text(strip=True)  if title  else "Unknown",
        "artist": artist.get_text(strip=True) if artist else "Unknown",
        "genre":  genre.get_text(strip=True)  if genre  else "Unknown",
    }


# ──────────────────────────────────────────────
# MENUS
# ──────────────────────────────────────────────
def pick_level() -> str:
    print("\n" + "="*40)
    print("  SELECT LEVEL")
    print("="*40)
    for key, label in LEVELS.items():
        print(f"  [{key:>2}]  {label}")
    print("  [ 0]  Exit")

    while True:
        choice = input("\n> Enter level number: ").strip()
        if choice == "0":
            return "0"
        if choice in LEVELS:
            return choice
        print("  Invalid choice, try again.")


def pick_song(songs: list) -> dict | None:
    print("\n" + "="*60)
    print("  SONG LIST")
    print("="*60)

    for i, song in enumerate(songs, 1):
        score_str = f"  [{song['score']}]" if song["score"] != "No score" else ""
        print(f"  [{i:>3}]  {song['title']:<45} ({song['diff']}){score_str}")

    print("  [  0]  Back")

    while True:
        choice = input("\n> Enter song number: ").strip()
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(songs):
            return songs[int(choice) - 1]
        print("  Invalid choice, try again.")


def display_detail(song: dict, detail: dict):
    print("\n" + "="*40)
    print("  SONG DETAIL")
    print("="*40)
    print(f"  Title      : {detail['title']}")
    print(f"  Artist     : {detail['artist']}")
    print(f"  Genre      : {detail['genre']}")
    print(f"  Difficulty : {song['diff']} Lv.{song['level']}")
    print(f"  Your Score : {song['score']}")
    print("="*40)


# ──────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  maimai DX NET Scraper")
    print("="*40)

    session = build_session()

    print("  Verifying session...")
    if not is_logged_in(session):
        print("  Session invalid. Re-export cookies and update .env.")
        exit(1)
    print("  Logged in successfully!")

    while True:
        level = pick_level()
        if level == "0":
            print("\n  Bye!")
            break

        # Fresh scrape on every level entry — idx always up to date
        songs = fetch_songs_by_level(session, level)

        if not songs:
            print("  No songs found for this level.")
            continue

        while True:
            selected = pick_song(songs)
            if selected is None:
                break  # back to level select

            print(f"\n  Fetching detail for '{selected['title']}'...")
            detail = fetch_song_detail(session, selected["idx"])
            display_detail(selected, detail)

            input("\n  Press Enter to go back to song list...")