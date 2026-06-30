import os
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maimaidx-eng.com/maimai-mobile"
AUTH_URL = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ──────────────────────────────────────────────
# AUTH AND SESSION
# ──────────────────────────────────────────────

_session: aiohttp.ClientSession | None = None

async def reset_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        lng_raw = os.getenv("LNGCOOKIE", "")

        jar = aiohttp.CookieJar()
        jar.update_cookies({"clal": lng_raw}, response_url=aiohttp.client.URL("https://lng-tgk-aime-gw.am-all.net"))

        s = aiohttp.ClientSession(headers=HEADERS, cookie_jar=jar)
        async with s.get(AUTH_URL, allow_redirects=True) as resp:
            print(f"[auth] final URL: {resp.url}")
            print(f"[auth] status: {resp.status}")
        _session = s
    return _session

async def _get(url: str) -> str:
    """Fetch a URL, reset session and raise if Sega kicked us."""
    session = await get_session()
    async with session.get(url, allow_redirects=True) as resp:
        resp.raise_for_status()
        text = await resp.text()
        if str(resp.url) != url:
            await reset_session()
            raise Exception("Session expired, please try the command again.")
        return text

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
async def fetch_recent_scores(limit: int = 20) -> list[dict]:
    """Returns list of recent plays from the playlog page."""
    soup = BeautifulSoup(await _get(f"{BASE_URL}/record/"), "html.parser")

    plays = []
    for entry in soup.select("div.p_10.t_l.f_0.v_b"):
        play = {}

        top = entry.select_one(".playlog_top_container")
        if top:
            diff_img = top.select_one(".playlog_diff")
            if diff_img:
                play["difficulty"] = diff_img["src"].split("diff_")[1].replace(".png", "").upper()
            track_span = top.select_one(".red.f_b")
            date_span  = top.select_one(".sub_title .v_b")
            play["track"] = track_span.text.strip() if track_span else None
            play["date"]  = date_span.text.strip()  if date_span  else None

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


async def fetch_songs_by_level(level: str) -> list[dict]:
    """Returns list of songs for a given level key (e.g. '21' = LEVEL 14)."""
    soup = BeautifulSoup(await _get(f"{BASE_URL}/record/musicLevel/search/?level={level}"), "html.parser")

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


async def fetch_song_by_name(name: str) -> list[dict]:
    """Search songs using a single request (diff=3), return name + idx matches."""
    soup = BeautifulSoup(await _get(f"{BASE_URL}/record/musicGenre/search/?genre=99&diff=3"), "html.parser")

    results = []
    for name_div in soup.select("div.music_name_block"):
        title = name_div.get_text(strip=True)
        if name.lower() not in title.lower():
            continue

        idx_input = name_div.find_parent("form").find("input", {"name": "idx"})
        if not idx_input:
            continue

        results.append({
            "title": title,
            "idx":   idx_input["value"],
        })

    return results


async def fetch_song_detail(idx: str) -> dict:
    """Returns title, artist, genre, and all difficulty scores for a song idx."""
    html = await _get(f"{BASE_URL}/record/musicDetail/?idx={idx}")
    print(f"[detail] html snippet: {html[:300]}")
    soup = BeautifulSoup(html, "html.parser")

    title  = soup.select_one(".m_5.f_15.break")
    artist = soup.select_one(".m_5.f_12.break")
    genre  = soup.select_one(".m_10.m_t_5.t_r.f_12.blue")

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
        if not block:
            continue

        lv_tag    = block.select_one(".music_lv_back")
        score_tag = block.select_one(".music_score_block.w_120")

        difficulties.append({
            "diff":  diff_name,
            "level": lv_tag.get_text(strip=True)    if lv_tag    else "?",
            "score": score_tag.get_text(strip=True) if score_tag else None,
        })

    return {
        "title":        title.get_text(strip=True)  if title  else "Unknown",
        "artist":       artist.get_text(strip=True) if artist else "Unknown",
        "genre":        genre.get_text(strip=True)  if genre  else "Unknown",
        "difficulties": difficulties,
    }


async def fetch_friend_list() -> list[dict]:
    """Returns list of friends with name, rating and idx."""
    soup = BeautifulSoup(await _get(f"{BASE_URL}/friend/"), "html.parser")

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
