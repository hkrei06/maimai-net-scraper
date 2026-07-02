"""Live-preview the element/*.html templates with sample data.

Renders a template with realistic mock context to ``element/_preview.html`` and
opens it in your browser, so you can design the card without running the bot.
Uses the SAME Jinja env as render.py, so the output matches what Playwright
screenshots. Open ``element/_preview.html`` with VS Code's "Live Preview"
extension (or just refresh a browser tab); with ``--watch`` it re-renders on
every save and Live Preview auto-refreshes.

    python scripts/preview.py                 # score_card.html (default)
    python scripts/preview.py b50.html        # preview a different template
    python scripts/preview.py --watch         # re-render whenever you save
"""

from __future__ import annotations

import sys
import time
import webbrowser

from render import _env, ELEMENT_DIR  # same loader/autoescape as the real renderer

OUT = ELEMENT_DIR / "_preview.html"

# A plain rounded placeholder so the jacket slot is visible without a real song.
# %23 is a literal '#' (hex color) inside the data URI.
_JACKET = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='132' height='132'>"
    "<rect width='132' height='132' rx='16' fill='%233a4466'/></svg>"
)

# Mock context per template. Mirrors the contract documented in each .html.
SAMPLE = {
    "score_card.html": dict(
        song={
            "title": "PANDORA PARADOXXX",
            "artist": "削","genre": "maimai", "bpm": 240, "jacket": _JACKET,
        },
        search_query="pandora",
        difficulties=[
            {"diff": "BASIC", "css": "basic", "level": "7", "constant": "7.0", "score": "99.5421%", "playcount": 12},
            {"diff": "ADVANCED", "css": "advanced", "level": "10", "constant": "10.2", "score": "98.1003%", "playcount": 8},
            {"diff": "EXPERT", "css": "expert", "level": "13", "constant": "13.4", "score": "100.2841%", "playcount": 40},
            {"diff": "MASTER", "css": "master", "level": "14+", "constant": "14.9", "score": "99.7612%", "playcount": 73},
            {"diff": "Re:MASTER", "css": "remaster", "level": "15", "constant": "15.0", "score": None, "playcount": None},
        ],
    ),
}


def render_once(template_name: str) -> None:
    ctx = SAMPLE.get(template_name)
    if ctx is None:
        sys.exit(f"No sample data for {template_name}. Add it to SAMPLE in preview.py "
                 f"(available: {', '.join(SAMPLE)}).")
    html = _env.get_template(template_name).render(**ctx)
    OUT.write_text(html, encoding="utf-8")
    print(f"[preview] wrote {OUT}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--watch"]
    watch = "--watch" in sys.argv
    template_name = args[0] if args else "score_card.html"
    src = ELEMENT_DIR / template_name

    render_once(template_name)
    webbrowser.open(OUT.as_uri())

    if not watch:
        return
    print(f"[preview] watching {src} (Ctrl+C to stop)")
    last = src.stat().st_mtime
    try:
        while True:
            time.sleep(0.5)
            mtime = src.stat().st_mtime
            if mtime != last:
                last = mtime
                render_once(template_name)
    except KeyboardInterrupt:
        print("\n[preview] stopped")


if __name__ == "__main__":
    main()
