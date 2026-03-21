import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# AUTH AND SESSION
# ──────────────────────────────────────────────

CLAL = os.getenv("LNGCOOKIE")

AUTH_URL = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
session.cookies.set("clal", CLAL, domain="lng-tgk-aime-gw.am-all.net")
response = session.get(AUTH_URL, allow_redirects=True)

# ──────────────────────────────────────────────
# SCRAPING FUNCTIONS
# ──────────────────────────────────────────────
def fetch_recent_scores(limit: int = 20) -> list[dict]:
    """Returns list of recent plays from the playlog page."""
    session = get_session()
    resp = session.get(f"{BASE_URL}/record/playlog/")
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
    """Search all songs across all genres and return matches by name."""
    session = get_session()

    # genre=99 means ALL songs, diff=0 to 4 covers all difficulties
    results = []
    seen_titles = set()

    for diff_num in range(5):  # 0=BASIC 1=ADVANCED 2=EXPERT 3=MASTER 4=Re:MASTER
        url = f"{BASE_URL}/record/musicGenre/search/?genre=99&diff={diff_num}"
        resp = session.get(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        for entry in soup.select("div[class*='score_back']"):
            name_tag  = entry.select_one(".music_name_block")
            idx_input = entry.select_one("input[name='idx']")
            lv_tag    = entry.select_one(".music_lv_block")
            score_tag = entry.select_one(".music_score_block")

            if not name_tag or not idx_input:
                continue

            title = name_tag.get_text(strip=True)

            # case-insensitive partial match
            if name.lower() not in title.lower():
                continue

            diff_map = {0: "BASIC", 1: "ADVANCED", 2: "EXPERT", 3: "MASTER", 4: "Re:MASTER"}

            results.append({
                "title": title,
                "diff":  diff_map[diff_num],
                "level": lv_tag.get_text(strip=True) if lv_tag else "?",
                "score": score_tag.get_text(strip=True) if score_tag else None,
                "idx":   idx_input["value"],
            })

    return results


def fetch_song_detail(idx: str) -> dict:
    """Returns title, artist, genre for a specific song idx."""
    session = get_session()
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


def fetch_friend_list() -> list[dict]:
    """Returns list of friends with name, rating and idx."""
    session = get_session()
    resp = session.get(f"{BASE_URL}/friend/")
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