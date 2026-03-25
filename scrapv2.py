import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# AUTH AND SESSION
# ──────────────────────────────────────────────

BASE_URL = "https://maimaidx-eng.com/maimai-mobile"
AUTH_URL = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)

_session: requests.Session | None = None

def get_session() -> requests.Session:
    global _session
    if _session is None:
        lng_raw = os.getenv("LNGCOOKIE", "")
        _, _, clal_value = lng_raw.partition("=")
        clal_value = clal_value.strip() or lng_raw.strip()

        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        s.cookies.set("clal", clal_value, domain="lng-tgk-aime-gw.am-all.net")
        resp = s.get(AUTH_URL, allow_redirects=True)
        print(f"[auth] final URL: {resp.url}")
        print(f"[auth] status: {resp.status_code}")
        _session = s
    return _session

# ──────────────────────────────────────────────
# LEVEL MAPPING
# ──────────────────────────────────────────────
LEVEL_MAP = {
    "1":   "1",  "2":   "2",  "3":   "3",  "4":   "4",
    "5":   "5",  "6":   "6",  "7":   "7",  "7+":  "8",
    "8":   "9",  "8+":  "10", "9":   "11", "9+":  "12",
    "10":  "13", "10+": "14", "11":  "15", "11+": "16",
    "12":  "17", "12+": "18", "13":  "19", "13+": "20",
    "14":  "21", "14+": "22", "15":  "23",
}

# ──────────────────────────────────────────────
# SCRAPING FUNCTIONS
# ──────────────────────────────────────────────
def fetch_recent_scores(limit: int = 20) -> list[dict]:
    """Returns list of recent plays from the playlog page."""
    session = get_session()
    resp = session.get(f"{BASE_URL}/record/")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    plays = []
    for entry in soup.select("div.p_10.t_l.f_0.v_b"):
        play = {}

        # difficulty + track + date
        top = entry.select_one(".playlog_top_container")
        if top:
            diff_img = top.select_one(".playlog_diff")
            if diff_img:
                play["difficulty"] = diff_img["src"].split("diff_")[1].replace(".png", "").upper()
            track_span = top.select_one(".red.f_b")
            date_span  = top.select_one(".sub_title .v_b")
            play["track"] = track_span.text.strip() if track_span else None
            play["date"]  = date_span.text.strip()  if date_span  else None

        # title + level
        title_block = entry.select_one(".basic_block.m_5")
        if title_block:
            level_div = title_block.select_one(".playlog_level_icon")
            play["level"] = level_div.text.strip() if level_div else None
            if level_div:
                level_div.extract()
            play["title"] = title_block.get_text(strip=True)

        # achievement score
        achievement = entry.select_one(".playlog_achievement_txt")
        play["achievement"] = achievement.text.strip() if achievement else None

        # rank image (SSS+, SS, etc.)
        rank_img = entry.select_one(".playlog_scorerank")
        play["rank_img"] = rank_img["src"] if rank_img else None

        # dx score
        dx_block = entry.select_one(".playlog_score_block_star .white")
        play["dx_score"] = dx_block.text.strip() if dx_block else None

        # new record flag
        play["is_new_record"] = bool(entry.select_one(".playlog_achievement_newrecord"))

        # idx for detail page
        idx_input = entry.select_one("input[name='idx']")
        play["idx"] = idx_input["value"] if idx_input else None

        plays.append(play)

    return plays[:limit]


def fetch_songs_by_level(level: str) -> list[dict]:
    """Returns list of songs for a given level key (e.g. '21' = LEVEL 14)."""
    session = get_session()
    url = f"{BASE_URL}/record/musicLevel/search/?level={level}"
    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    songs = []
    for entry in soup.select("div[class*='score_back']"):
        name_tag  = entry.select_one(".music_name_block")
        idx_input = entry.select_one("input[name='idx']")
        lv_tag    = entry.select_one(".music_lv_block")
        score_tag = entry.select_one(".music_score_block")

        if not name_tag or not idx_input:
            continue

        classes = " ".join(entry.get("class", []))
        if "remaster" in classes:   diff = "Re:MASTER"
        elif "master" in classes:   diff = "MASTER"
        elif "expert" in classes:   diff = "EXPERT"
        elif "advanced" in classes: diff = "ADVANCED"
        else:                       diff = "BASIC"

        songs.append({
            "title": name_tag.get_text(strip=True),
            "diff":  diff,
            "level": lv_tag.get_text(strip=True) if lv_tag else "?",
            "score": score_tag.get_text(strip=True) if score_tag else None,
            "idx":   idx_input["value"],
        })

    return songs


def fetch_song_by_name(name: str) -> list[dict]:
    """Search songs using a single request (diff=3), return name + idx matches."""
    session = get_session()
    url = f"{BASE_URL}/record/musicGenre/search/?genre=99&diff=3"
    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for entry in soup.select("div[class*='score_back']"):
        name_tag  = entry.select_one(".music_name_block")
        idx_input = entry.select_one("input[name='idx']")

        if not name_tag or not idx_input:
            continue

        title = name_tag.get_text(strip=True)
        if name.lower() not in title.lower():
            continue

        results.append({
            "title": title,
            "idx":   idx_input["value"],
        })

    return results


def fetch_song_detail(idx: str) -> dict:
    """Returns title, artist, genre, and all difficulty scores for a song idx."""
    session = get_session()
    url = f"{BASE_URL}/record/musicDetail/?idx={idx}"
    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title  = soup.select_one(".m_5.f_15.break")
    artist = soup.select_one(".m_5.f_12.break")
    genre  = soup.select_one(".m_10.m_t_5.t_r.f_12.blue")

    # parse per-difficulty scores from the detail page
    diff_ids = [
        ("basic",    "BASIC"),
        ("advanced", "ADVANCED"),
        ("expert",   "EXPERT"),
        ("master",   "MASTER"),
        ("remaster", "Re:MASTER"),
    ]
    difficulties = []
    for block_id, diff_name in diff_ids:
        block = soup.select_one(f"div#{block_id}")
        print(f"[detail] {block_id}: {'found' if block else 'NOT FOUND'}")
        if not block:
            continue

        lv_tag    = block.select_one(".music_lv_back")
        score_tag = block.select_one(".music_score_block.w_120")  # achievement % block
        print(f"[detail] {block_id} lv={lv_tag} score={score_tag}")

        difficulties.append({
            "diff":  diff_name,
            "level": lv_tag.get_text(strip=True)    if lv_tag    else "?",
            "score": score_tag.get_text(strip=True) if score_tag else None,
        })

    return {
        "title":        title.get_text(strip=True)  if title  else "Unknown",
        "artist":       artist.get_text(strip=True) if artist else "Unknown",
        "genre":        genre.get_text(strip=True)  if genre  else "Unknown",
        "difficulties": difficulties,  # list of {diff, level, score} — only present difficulties included
    }


def fetch_friend_list() -> list[dict]:
    """Returns list of friends with name, rating and idx."""
    session = get_session()
    resp = session.get(f"{BASE_URL}/friend/")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    friends = []
    for block in soup.select("div.see_through_block"):
        name_div    = block.select_one(".name_block")
        rating_div  = block.select_one(".rating_block")
        detail_form = block.select_one("form[action*='friendDetail']")

        if not name_div or not detail_form:
            continue

        idx_input = detail_form.select_one("input[name='idx']")

        friends.append({
            "name":   name_div.text.strip(),
            "rating": rating_div.text.strip() if rating_div else "N/A",
            "idx":    idx_input["value"] if idx_input else None,
        })

    return friends