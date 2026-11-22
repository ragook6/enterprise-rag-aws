#!/usr/bin/env python3
"""Generate the synthetic HRL enterprise PDFs into data/documents/ using ReportLab."""
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

sys.path.insert(0, str(Path(__file__).parent))
from content import DISCLAIMER, DOCUMENTS, ORG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "documents"

NAVY = colors.HexColor("#1F3A5F")
LIGHT = colors.HexColor("#E8EEF5")
GRID = colors.HexColor("#9AAAC0")

base = getSampleStyleSheet()
STYLES = {
    "title": ParagraphStyle("title", parent=base["Title"], fontSize=22, leading=27, textColor=NAVY,
                            alignment=0, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=13, leading=17,
                               textColor=colors.HexColor("#4A5A70"), spaceAfter=10),
    "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=13.5, leading=17, textColor=NAVY,
                         spaceBefore=12, spaceAfter=5),
    "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5, leading=14, textColor=NAVY,
                         spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", parent=base["Normal"], fontSize=10, leading=13.5, alignment=TA_JUSTIFY,
                        spaceAfter=6),
    "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.8, leading=11),
    "cellh": ParagraphStyle("cellh", parent=base["Normal"], fontSize=8.8, leading=11,
                            fontName="Helvetica-Bold", textColor=colors.white),
    "code": ParagraphStyle("code", parent=base["Code"], fontSize=8.3, leading=10.5,
                           backColor=colors.HexColor("#F4F6F8"), borderColor=GRID, borderWidth=0.5,
                           borderPadding=6, leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=10),
    "note": ParagraphStyle("note", parent=base["Normal"], fontSize=8.5, leading=11,
                           textColor=colors.HexColor("#7A2E00"), backColor=colors.HexColor("#FFF4E5"),
                           borderColor=colors.HexColor("#E0A060"), borderWidth=0.5, borderPadding=6,
                           spaceBefore=6, spaceAfter=10),
}


def markup(text: str) -> str:
    """Escape XML special characters, then convert **bold** to <b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def make_table(rows, widths):
    data = []
    for r, row in enumerate(rows):
        style = STYLES["cellh"] if r == 0 else STYLES["cell"]
        data.append([Paragraph(markup(str(c)), style) for c in row])
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_story(doc):
    story = [
        Paragraph(escape(ORG).upper(), ParagraphStyle("org", parent=STYLES["p"], fontSize=9,
                                                      textColor=colors.HexColor("#6B7A90"))),
        Paragraph(markup(doc["title"]), STYLES["title"]),
        Paragraph(markup(doc["subtitle"]), STYLES["subtitle"]),
        make_table([["Document ID", "Version", "Date", "Owner"],
                    [doc["doc_id"], doc["version"], doc["date"], doc["owner"]]],
                   [1.5, 1.1, 1.0, 3.1]),
        Paragraph(markup(DISCLAIMER), STYLES["note"]),
    ]
    section = 0
    for block in doc["body"]:
        kind = block[0]
        if kind == "h1":
            section += 1
            story.append(Paragraph(f"{section}. {markup(block[1])}", STYLES["h1"]))
        elif kind == "h2":
            story.append(Paragraph(markup(block[1]), STYLES["h2"]))
        elif kind == "p":
            story.append(Paragraph(markup(block[1]), STYLES["p"]))
        elif kind in ("bullets", "steps"):
            items = [ListItem(Paragraph(markup(t), STYLES["p"]), leftIndent=14) for t in block[1]]
            kw = {"bulletType": "1", "bulletFormat": "%s."} if kind == "steps" else \
                 {"bulletType": "bullet", "start": "•"}
            story.append(ListFlowable(items, leftIndent=14, bulletFontSize=9, **kw))
            story.append(Spacer(1, 4))
        elif kind == "table":
            story.append(make_table(block[1], block[2]))
            story.append(Spacer(1, 8))
        elif kind == "code":
            story.append(KeepTogether(Preformatted(block[1], STYLES["code"])))
        elif kind == "note":
            story.append(Paragraph(markup(block[1]), STYLES["note"]))
        elif kind == "pagebreak":
            story.append(PageBreak())
        else:
            raise ValueError(f"Unknown block type: {kind}")
    return story


def numbered_canvas_factory(doc):
    """Canvas that draws header/footer with 'Page X of Y' (needs total page count, so defer drawing)."""

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._draw_chrome(total)
                super().showPage()
            super().save()

        def _draw_chrome(self, total):
            w, h = letter
            self.saveState()
            self.setStrokeColor(NAVY)
            self.setLineWidth(0.6)
            self.line(0.75 * inch, h - 0.6 * inch, w - 0.75 * inch, h - 0.6 * inch)
            self.line(0.75 * inch, 0.65 * inch, w - 0.75 * inch, 0.65 * inch)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#4A5A70"))
            self.drawString(0.75 * inch, h - 0.52 * inch, f"{doc['doc_id']}  |  {doc['title']}")
            self.drawRightString(w - 0.75 * inch, h - 0.52 * inch, "HRL Internal - Synthetic Test Data")
            self.drawString(0.75 * inch, 0.48 * inch, f"Version {doc['version']}  |  {doc['date']}")
            self.drawRightString(w - 0.75 * inch, 0.48 * inch,
                                 f"Page {self._pageNumber} of {total}")
            self.restoreState()

    return NumberedCanvas


def generate(doc) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / doc["filename"]
    template = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.85 * inch, bottomMargin=0.9 * inch,
        title=doc["title"], author=f"{ORG} (fictional)", subject=doc["doc_id"],
        creator="enterprise-rag-aws/scripts/generate_pdfs.py",
    )
    template.build(build_story(doc), canvasmaker=numbered_canvas_factory(doc))
    return path


if __name__ == "__main__":
    for d in DOCUMENTS:
        print(f"generated {generate(d).relative_to(ROOT)}")
