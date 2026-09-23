"""QR codes for share links, as inline SVG."""

from __future__ import annotations

import segno


def qr_svg(url: str) -> str:
    # Always dark-on-white, whatever the page theme, so phone cameras can read it.
    return segno.make(url, error="m").svg_inline(scale=5, border=2, dark="#111111", light="#ffffff")
