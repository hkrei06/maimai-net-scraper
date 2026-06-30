"""
b50 generator — standalone CLI prototype.

Fetches the player's DX-rating component from maimai-net's ratingTargetMusic page,
enriches it with chart constants + jackets from the local song DB, computes each
chart's single rating, and renders a b50 image (best 15 "new" + best 35 "old").

Auth + session + page fetching are shared via ``scrap`` (clal cookie).

Usage:
  set MAIMAI_CLAL in .env (or env)
  python scripts/b50.py            # writes b50.png + prints a summary
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import unicodedata

from bs4 import BeautifulSoup

# Allow `import scrap` / `import songdb` / `import render` whether run as a script
# or a module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrap  # noqa: E402
import songdb  # noqa: E402
import render  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────

RATING_URL = f"{scrap.MOBILE}/home/ratingTargetMusic/"
BASE_URL = scrap.BASE_URL

OUT_FILE = "b50.png"

# diff_css -> music-ex.json level/constant key suffix
_DIFF_SUFFIX = {
    "basic": "bas",
    "advanced": "adv",
    "expert": "exp",
    "master": "mas",
    "remaster": "remas",
}
# diff_css -> display name
_DIFF_NAME = {
    "basic": "BASIC",
    "advanced": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "remaster": "Re:MASTER",
}
# rank icon filename token -> display
_RANK = {
    "sssp": "SSS+", "sss": "SSS", "ssp": "SS+", "ss": "SS",
    "sp": "S+", "s": "S", "aaa": "AAA", "aa": "AA", "a": "A",
    "bbb": "BBB", "bb": "BB", "b": "B", "c": "C", "d": "D",
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def normalize_name(text: str) -> str:
    """NFKC normalize + strip (same as testauth's normalizeName)."""
    return unicodedata.normalize("NFKC", text).strip()


def single_rating(constant: float, achievement: float, is_ap: bool = False) -> int:
    """maimai DX single-chart rating: floor(constant * min(achv, 100.5) * coef).

    An All Perfect (AP) play earns +1 rating. AP status is NOT available on the
    ratingTargetMusic page, so callers currently always pass ``is_ap=False``;
    wire it up once an AP source is added.
    """
    rate = min(achievement, 100.5)
    if achievement >= 100.5:
        coef = 0.224
    elif achievement >= 100.0:
        coef = 0.216
    elif achievement >= 99.5:
        coef = 0.211
    elif achievement >= 99.0:
        coef = 0.208
    elif achievement >= 98.0:
        coef = 0.203
    elif achievement >= 97.0:
        coef = 0.200
    elif achievement >= 94.0:
        coef = 0.168
    elif achievement >= 90.0:
        coef = 0.152
    elif achievement >= 80.0:
        coef = 0.136
    elif achievement >= 75.0:
        coef = 0.120
    elif achievement >= 70.0:
        coef = 0.112
    elif achievement >= 60.0:
        coef = 0.096
    elif achievement >= 50.0:
        coef = 0.080
    else:
        coef = 0.0
    return math.floor(constant * rate * coef) + (1 if is_ap else 0)


# ── Parse ────────────────────────────────────────────────────────────────────

def _diff_css_from_classes(classes: list[str]) -> str:
    for cls in classes:
        m = re.match(r"music_(\w+)_score_back", cls)
        if m and m.group(1) in _DIFF_SUFFIX:
            return m.group(1)
    return "master"


def _parse_block(block) -> dict | None:
    name_el = block.select_one(".music_name_block")
    score_el = block.select_one(".music_score_block")
    if not name_el or not score_el:
        return None

    title = normalize_name(name_el.get_text())
    ach_text = score_el.get_text()
    m = re.search(r"(\d+\.\d+)\s*%", ach_text)
    if not m:
        return None
    achievement = float(m.group(1))

    diff_css = _diff_css_from_classes(block.get("class", []))

    icon = block.select_one(".music_kind_icon")
    icon_src = icon.get("src", "") if icon else ""
    type_ = "DX" if "music_dx" in icon_src else "STD"

    lv_el = block.select_one(".music_lv_block")
    level = lv_el.get_text().strip() if lv_el else ""

    rank = ""
    rank_img = block.select_one(".ratingtarget_scorerank_block img")
    if rank_img:
        rm = re.search(r"music_icon_(\w+)\.png", rank_img.get("src", ""))
        if rm:
            rank = _RANK.get(rm.group(1), rm.group(1).upper())

    idx_el = block.select_one("input[name='idx']")
    idx = idx_el.get("value", "") if idx_el else ""

    return {
        "title": title,
        "diff_css": diff_css,
        "diff_name": _DIFF_NAME.get(diff_css, diff_css.upper()),
        "type": type_,
        "level": level,
        "achievement": achievement,
        "achievement_text": f"{achievement:.4f}%",
        "rank": rank,
        "idx": idx,
    }


def parse_rating_target(html: str) -> tuple[list[dict], list[dict]]:
    """Return (new_charts, old_charts) from the two non-Selection sections."""
    soup = BeautifulSoup(html, "html.parser")
    new: list[dict] = []
    old: list[dict] = []
    current: list[dict] | None = None

    for node in soup.select('.screw_block, div[class*="_score_back"]'):
        classes = node.get("class", [])
        if "screw_block" in classes:
            text = node.get_text()
            if "Selection" in text:
                current = None              # candidate pool, not part of b50
            elif "(New)" in text:
                current = new
            elif "(Others)" in text:
                current = old
            else:
                current = None
            continue
        if current is None:
            continue
        parsed = _parse_block(node)
        if parsed:
            current.append(parsed)

    return new, old


# ── Enrich (constant + jacket from local song DB) ─────────────────────────────

def _build_index() -> dict[str, list[dict]]:
    with open(songdb.SONGS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    index: dict[str, list[dict]] = {}
    for entry in raw:
        key = normalize_name(entry.get("title", ""))
        index.setdefault(key, []).append(entry)
    return index


def enrich(charts: list[dict], index: dict[str, list[dict]], unmatched: list[str]) -> None:
    for c in charts:
        suffix = _DIFF_SUFFIX.get(c["diff_css"], "mas")
        const_key = ("dx_" if c["type"] == "DX" else "") + f"lev_{suffix}_i"
        entries = index.get(c["title"], [])
        constant = ""
        image_url = ""
        for entry in entries:
            val = entry.get(const_key)
            if val:
                constant = str(val)
                image_url = entry.get("image_url", "")
                break
        if not constant and entries:                 # fall back to any jacket
            image_url = entries[0].get("image_url", "")

        c["constant"] = constant
        c["jacket"] = songdb.jacket_data_uri(image_url) if image_url else ""
        c["rating"] = single_rating(float(constant), c["achievement"]) if constant else 0
        if not constant:
            unmatched.append(f"{c['title']} [{c['type']} {c['diff_name']}]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not scrap.CLAL:
        print("Error: set MAIMAI_CLAL in .env (your clal cookie value)")
        return

    print("Fetching ratingTargetMusic page...")
    html = scrap.fetch_html(RATING_URL, referer=f"{scrap.MOBILE}/home/")

    new, old = parse_rating_target(html)
    index = _build_index()
    unmatched: list[str] = []
    enrich(new, index, unmatched)
    enrich(old, index, unmatched)

    total_rating = sum(c["rating"] for c in new) + sum(c["rating"] for c in old)
    payload = {"total_rating": total_rating, "new_charts": new, "old_charts": old}

    print("Rendering b50 image...")
    png = asyncio.run(_render(payload))
    with open(OUT_FILE, "wb") as f:
        f.write(png)

    print(f"\n{'='*60}")
    print(f"Total rating: {total_rating}   (new: {len(new)}, old: {len(old)})")
    print(f"Wrote {OUT_FILE} ({len(png)} bytes)")
    if unmatched:
        print(f"\n{len(unmatched)} chart(s) with no constant match (rating=0):")
        for u in unmatched:
            print(f"  - {u}")
    print(f"{'='*60}")


async def _render(payload: dict) -> bytes:
    try:
        return await render.render_b50_card(payload)
    finally:
        await render.close()


if __name__ == "__main__":
    main()
