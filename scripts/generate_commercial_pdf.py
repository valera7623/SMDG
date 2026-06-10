#!/usr/bin/env python3
"""Generate ARCHITECTURE_FOR_IB.pdf from markdown source (commercial pack)."""

from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/locales/ru/commercial/ARCHITECTURE_FOR_IB.md"
OUTPUT = ROOT / "docs/locales/ru/commercial/ARCHITECTURE_FOR_IB.pdf"

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
)


def register_font() -> str:
    for path in FONT_CANDIDATES:
        if path.is_file():
            pdfmetrics.registerFont(TTFont("DejaVu", str(path)))
            return "DejaVu"
    raise FileNotFoundError("DejaVuSans.ttf not found; install fonts-dejavu-core")


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def parse_table(lines: list[str]) -> Table | None:
    rows: list[list[str]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", " "} for c in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return None
    col_count = max(len(r) for r in rows)
    normalized = [r + [""] * (col_count - len(r)) for r in rows]
    usable_width = A4[0] - 36 * mm
    col_w = usable_width / col_count
    table = Table(normalized, colWidths=[col_w] * col_count, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_story(md_text: str, styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    lines = md_text.splitlines()
    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[str] = []

    def flush_table() -> None:
        nonlocal table_buf
        if table_buf:
            tbl = parse_table(table_buf)
            if tbl:
                story.append(tbl)
                story.append(Spacer(1, 4 * mm))
            table_buf = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                in_code = False
                body = "<br/>".join(escape_xml(x) for x in code_buf)
                story.append(Paragraph(f'<font name="Courier">{body}</font>', styles["Code"]))
                story.append(Spacer(1, 3 * mm))
                code_buf = []
            else:
                flush_table()
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if stripped.startswith("|"):
            table_buf.append(line)
            i += 1
            continue
        flush_table()

        if stripped.startswith("> "):
            story.append(Paragraph(escape_xml(stripped[2:]), styles["Quote"]))
            story.append(Spacer(1, 2 * mm))
        elif stripped.startswith("# "):
            story.append(Paragraph(escape_xml(stripped[2:]), styles["Title"]))
            story.append(Spacer(1, 4 * mm))
        elif stripped.startswith("## "):
            story.append(Paragraph(escape_xml(stripped[3:]), styles["Heading2"]))
            story.append(Spacer(1, 3 * mm))
        elif stripped.startswith("### "):
            story.append(Paragraph(escape_xml(stripped[4:]), styles["Heading3"]))
            story.append(Spacer(1, 2 * mm))
        elif stripped.startswith("- "):
            story.append(Paragraph(f"• {escape_xml(stripped[2:])}", styles["Body"]))
        elif stripped == "---":
            story.append(Spacer(1, 4 * mm))
        elif stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            story.append(Paragraph(f"<i>{escape_xml(stripped.strip('*'))}</i>", styles["Body"]))
        elif stripped:
            text = escape_xml(stripped)
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            text = text.replace("`", "")
            story.append(Paragraph(text, styles["Body"]))
        i += 1

    flush_table()
    return story


def main() -> int:
    register_font()
    if not SOURCE.is_file():
        print(f"Source not found: {SOURCE}", file=sys.stderr)
        return 1

    md_text = SOURCE.read_text(encoding="utf-8")
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "TitleRu",
            parent=base["Title"],
            fontName="DejaVu",
            fontSize=16,
            leading=20,
            spaceAfter=6,
        ),
        "Heading2": ParagraphStyle(
            "H2Ru",
            parent=base["Heading2"],
            fontName="DejaVu",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1a3a5c"),
            spaceBefore=6,
        ),
        "Heading3": ParagraphStyle(
            "H3Ru",
            parent=base["Heading3"],
            fontName="DejaVu",
            fontSize=10,
            leading=13,
        ),
        "Body": ParagraphStyle(
            "BodyRu",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
        ),
        "Quote": ParagraphStyle(
            "QuoteRu",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#555555"),
            leftIndent=8,
        ),
        "Code": ParagraphStyle(
            "CodeRu",
            parent=base["Code"],
            fontName="DejaVu",
            fontSize=7,
            leading=9,
            backColor=colors.HexColor("#f4f4f4"),
            leftIndent=6,
        ),
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="SMDG — Архитектура для службы ИБ",
        author="Valeriy Popov",
    )
    doc.build(build_story(md_text, styles))
    OUTPUT.write_bytes(buffer.getvalue())
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
