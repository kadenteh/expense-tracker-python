"""A tiny PDF 1.4 writer: text, lines and filled rectangles on US Letter pages,
using the two standard Helvetica fonts every PDF reader ships with. It covers
exactly what the expense report needs, so the app stays free of dependencies."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0

Color = tuple[float, float, float]
BLACK: Color = (0.0, 0.0, 0.0)

# Glyph advance widths (1/1000 em) for characters 32..126, from the Adobe AFM files.
_HELVETICA_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_HELVETICA_BOLD_WIDTHS = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)
# The few non-ASCII glyphs the report itself uses (same width in both weights).
_EXTRA_WIDTHS = {"–": 556, "·": 278, "…": 1000}
_FALLBACK_WIDTH = 556

ELLIPSIS = "…"


def text_width(text: str, size: float, bold: bool = False) -> float:
    widths = _HELVETICA_BOLD_WIDTHS if bold else _HELVETICA_WIDTHS
    units = 0
    for ch in text:
        code = ord(ch)
        if 32 <= code <= 126:
            units += widths[code - 32]
        else:
            units += _EXTRA_WIDTHS.get(ch, _FALLBACK_WIDTH)
    return units * size / 1000


def fit_text(text: str, max_width: float, size: float, bold: bool = False) -> str:
    """Truncate `text` with an ellipsis so it fits within `max_width` points."""
    if text_width(text, size, bold) <= max_width:
        return text
    while text and text_width(text + ELLIPSIS, size, bold) > max_width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def _pdf_string(text: str) -> str:
    """A PDF literal string in WinAnsi encoding; unmappable characters become '?'."""
    out = []
    for byte in text.encode("cp1252", errors="replace"):
        if byte in b"\\()":
            out.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            out.append(chr(byte))
        else:
            out.append(f"\\{byte:03o}")
    return "(" + "".join(out) + ")"


def _rgb(color: Color) -> str:
    return " ".join(f"{c:.3f}" for c in color)


class PdfPage:
    def __init__(self) -> None:
        self._ops: list[str] = []

    def text(
        self, x: float, y: float, text: str, *, size: float = 10, bold: bool = False, color: Color = BLACK
    ) -> None:
        font = "F2" if bold else "F1"
        self._ops.append(
            f"BT /{font} {size:g} Tf {_rgb(color)} rg {x:.2f} {y:.2f} Td {_pdf_string(text)} Tj ET"
        )

    def text_right(
        self, right: float, y: float, text: str, *, size: float = 10, bold: bool = False, color: Color = BLACK
    ) -> None:
        self.text(right - text_width(text, size, bold), y, text, size=size, bold=bold, color=color)

    def line(
        self, x1: float, y1: float, x2: float, y2: float, *, width: float = 0.5, color: Color = BLACK
    ) -> None:
        self._ops.append(f"{width:g} w {_rgb(color)} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x: float, y: float, w: float, h: float, *, color: Color) -> None:
        self._ops.append(f"{_rgb(color)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def content(self) -> bytes:
        return "\n".join(self._ops).encode("ascii")


class PdfDocument:
    def __init__(self, title: str, created: Optional[datetime] = None) -> None:
        self.title = title
        self.created = created or datetime.now().astimezone()
        self.pages: list[PdfPage] = []

    def add_page(self) -> PdfPage:
        page = PdfPage()
        self.pages.append(page)
        return page

    def to_bytes(self) -> bytes:
        if not self.pages:
            self.add_page()

        # Object numbers: 1 catalog, 2 page tree, 3/4 fonts, 5 info, then a
        # (page, content stream) pair for every page.
        page_refs = [6 + 2 * i for i in range(len(self.pages))]
        kids = " ".join(f"{ref} 0 R" for ref in page_refs)
        objects: list[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>".encode("ascii"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            (
                f"<< /Title {_pdf_string(self.title)} /Producer (Expense Tracker)"
                f" /CreationDate ({_pdf_date(self.created)}) >>"
            ).encode("ascii"),
        ]
        for page, ref in zip(self.pages, page_refs):
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:g} {PAGE_HEIGHT:g}]"
                    f" /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {ref + 1} 0 R >>"
                ).encode("ascii")
            )
            stream = page.content()
            objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

        xref_offset = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1,
            xref_offset,
        )
        return bytes(out)


def _pdf_date(moment: datetime) -> str:
    stamp = moment.strftime("D:%Y%m%d%H%M%S")
    offset = moment.strftime("%z")  # e.g. +1000, or '' for naive datetimes
    return f"{stamp}{offset[:3]}'{offset[3:]}'" if offset else stamp
