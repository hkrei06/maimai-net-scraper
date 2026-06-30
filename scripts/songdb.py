"""
Static song database for maimai.

Loads the bundled static data (``maimai data/data/music-ex.json``) once at import
time and exposes a fuzzy ("semantic") search over song titles / artists plus
helpers to resolve a song's jacket image.

This is the single source of truth for *static* song data (title, artist, genre,
difficulty levels, chart constants, jacket). Per-user data (achievements, play
counts) is NOT here -- that still comes from the live site via ``scrapv2``.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent  # project root (scripts/ -> root)
DATA_DIR = ROOT / "maimai data" / "data"
JACKET_DIR = ROOT / "maimai data" / "jacket"
SONGS_FILE = DATA_DIR / "music-ex-intl.json"  # richest static source (levels + constants)

# Ordered difficulty definitions: (json key prefix, display name, css class)
DIFFICULTIES = [
    ("lev_bas",   "BASIC",     "basic"),
    ("lev_adv",   "ADVANCED",  "advanced"),
    ("lev_exp",   "EXPERT",    "expert"),
    ("lev_mas",   "MASTER",    "master"),
    ("lev_remas", "Re:MASTER", "remaster"),
]


# ──────────────────────────────────────────────
# LOADING
# ──────────────────────────────────────────────
def _load_songs() -> list[dict]:
    with open(SONGS_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    songs = []
    for entry in raw:
        difficulties = []
        for prefix, name, css in DIFFICULTIES:
            # Prefer the standard chart; fall back to the DX chart (``dx_*``)
            # for the many songs that only exist as DX.
            p = prefix if entry.get(prefix) else f"dx_{prefix}"
            level = entry.get(p)
            if not level:  # chart doesn't exist for this song
                continue
            difficulties.append({
                "diff":     name,
                "css":      css,
                "level":    level,
                "constant": entry.get(f"{p}_i") or "",
                "designer": entry.get(f"{p}_designer") or "",
            })

        songs.append({
            "title":      entry.get("title", "Unknown"),
            "title_kana": entry.get("title_kana", ""),
            "artist":     entry.get("artist", "Unknown"),
            "genre":      entry.get("catcode", "Unknown"),
            "bpm":        entry.get("bpm", ""),
            "version":    entry.get("version", ""),
            "image_url":  entry.get("image_url", ""),
            "difficulties": difficulties,
        })
    return songs


SONGS: list[dict] = _load_songs()

# Search corpus: index -> searchable string (title + kana + artist).
# Kept parallel to SONGS so a match maps straight back to a song dict.
_CHOICES: dict[int, str] = {
    i: f"{s['title']} {s['title_kana']} {s['artist']}"
    for i, s in enumerate(SONGS)
}


# ──────────────────────────────────────────────
# SEARCH
# ──────────────────────────────────────────────
def search(query: str, limit: int = 5) -> list[dict]:
    """Fuzzy-search the static song database.

    Returns up to ``limit`` song dicts ordered best-match first. An exact
    (case-insensitive) title match is always promoted to the top.
    """
    query = query.strip()
    if not query:
        return []

    matches = process.extract(
        query,
        _CHOICES,
        scorer=fuzz.WRatio,
        limit=limit,
        processor=lambda s: s.lower(),
    )
    # process.extract over a dict yields (choice, score, key) tuples.
    results = [SONGS[key] for _choice, _score, key in matches]

    # Promote an exact title hit to the front if one exists.
    ql = query.lower()
    for i, song in enumerate(results):
        if song["title"].lower() == ql:
            if i:
                results.insert(0, results.pop(i))
            break
    return results


def best_match(query: str) -> dict | None:
    """Return the single best-matching song, or None."""
    results = search(query, limit=1)
    return results[0] if results else None


# ──────────────────────────────────────────────
# JACKETS
# ──────────────────────────────────────────────
def jacket_path(image_url: str) -> Path | None:
    """Resolve a song's ``image_url`` to a local jacket file, if present."""
    if not image_url:
        return None
    path = JACKET_DIR / image_url
    return path if path.is_file() else None


@lru_cache(maxsize=512)
def jacket_data_uri(image_url: str) -> str:
    """Return the jacket as a base64 ``data:`` URI for embedding in HTML.

    Falls back to an empty string when the jacket is missing so the template
    can degrade gracefully.
    """
    path = jacket_path(image_url)
    if path is None:
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
