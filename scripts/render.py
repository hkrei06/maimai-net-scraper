"""
HTML-to-image rendering via Jinja2 + Playwright.

Templates live in ``element/`` so they can be tweaked without touching code.
``render_score_card`` builds the /score image and returns raw PNG bytes.

A single Chromium browser is launched lazily and reused across renders.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent  # project root (scripts/ -> root)
ELEMENT_DIR = ROOT / "element"

_env = Environment(
    loader=FileSystemLoader(str(ELEMENT_DIR)),
    autoescape=select_autoescape(["html"]),
)

# Shared browser instance (Playwright is started once and kept alive).
_pw = None
_browser = None
_lock = asyncio.Lock()


async def _get_browser():
    global _pw, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(args=["--no-sandbox"])
    return _browser


async def warm() -> None:
    """Launch the shared browser ahead of time so it can overlap slow I/O.

    Cheap to call repeatedly: the browser is a shared singleton, so only the
    first triggered command actually pays the launch cost — every later command
    (and every other user) reuses the same instance.
    """
    await _get_browser()


async def close() -> None:
    """Tear down the shared browser (call on bot shutdown)."""
    global _pw, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _pw is not None:
        await _pw.stop()
        _pw = None


async def _html_to_png(html: str, selector: str = ".card") -> bytes:
    browser = await _get_browser()
    page = await browser.new_page(device_scale_factor=2)
    try:
        await page.set_content(html, wait_until="networkidle")
        element = await page.query_selector(selector)
        target = element or page
        return await target.screenshot(omit_background=True, type="png")
    finally:
        await page.close()


async def render_score_card(
    song: dict, difficulties: list[dict], search_query: str
) -> bytes:
    """Render the score card template to PNG bytes.

    ``song`` must include a ``jacket`` data URI (see songdb.jacket_data_uri).
    """
    template = _env.get_template("score_card.html")
    html = template.render(
        song=song, difficulties=difficulties, search_query=search_query
    )
    return await _html_to_png(html, selector=".card")


async def render_b50_card(payload: dict) -> bytes:
    """Render the b50 template to PNG bytes.

    ``payload`` is the context produced by ``scripts.b50`` and must contain
    ``total_rating``, ``new_charts`` and ``old_charts`` (see b50.html for the shape).
    """
    template = _env.get_template("b50.html")
    html = template.render(**payload)
    return await _html_to_png(html, selector=".card")
