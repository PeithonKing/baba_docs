"""Fill a docxtpl template (e.g. templates/letterhead/letterhead.docx) with structured content.

Content JSON (written by the agent as content.json in the job folder):
{
  "date": "2 Jan 2026", "memo": null, "title": "Notice", "signature": true,
  "blocks": [
    {"type": "para", "text": "All are **requested** to *submit*", "align": "left", "italic": false, "bold": false, "size": 12},
    {"type": "heading", "text": "Section A", "level": 1},
    {"type": "list", "items": ["first", "second"], "numbered": false},
    {"type": "table", "rows": [["Class", "Date"], ["IX", "5 Jan"]], "header": true, "widths": [4, 6], "border": true},
    {"type": "space"}, {"type": "page_break"}
  ]
}
Inline: **bold**, *italic*. Bengali text is fine anywhere (Unicode only).
"""
import json
import re
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docxtpl import DocxTemplate, InlineImage

ROOT = Path(__file__).resolve().parent.parent
LATIN, BENGALI = "Arial", "Nirmala UI"
ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
INLINE = re.compile(r"(\*\*.+?\*\*|\*.+?\*)")


def _rpr_extra(r, *, bold, italic, size):
    """Latin + complex-script (Bengali) fonts, and the *Cs twins so Bengali is bold/italic too."""
    rpr = r._r.get_or_add_rPr()
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), LATIN)
    fonts.set(qn("w:hAnsi"), LATIN)
    fonts.set(qn("w:cs"), BENGALI)
    rpr.insert(0, fonts)
    if bold:
        rpr.append(OxmlElement("w:bCs"))
    if italic:
        rpr.append(OxmlElement("w:iCs"))
    if size:
        szcs = OxmlElement("w:szCs")
        szcs.set(qn("w:val"), str(int(size * 2)))
        rpr.append(szcs)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "en-IN")
    lang.set(qn("w:bidi"), "bn-IN")
    rpr.append(lang)


def _add_inline(par, text, *, bold=False, italic=False, size=None):
    for piece in INLINE.split(text):
        if not piece:
            continue
        b, i = bold, italic
        if piece.startswith("**") and piece.endswith("**"):
            piece, b = piece[2:-2], True
        elif piece.startswith("*") and piece.endswith("*"):
            piece, i = piece[1:-1], True
        # keep explicit line breaks inside one paragraph
        for n, line in enumerate(piece.split("\n")):
            if n:
                par.add_run().add_break()
            r = par.add_run(line)
            r.bold, r.italic = b or None, i or None
            if size:
                r.font.size = Pt(size)
            _rpr_extra(r, bold=b, italic=i, size=size)


HEADING_SIZE = {1: 16, 2: 14, 3: 12.5}


def _table(sd, blk):
    rows = blk["rows"]
    ncols = max(len(r) for r in rows)
    t = sd.add_table(rows=len(rows), cols=ncols)
    if blk.get("border", True):
        t.style = "Table Grid"
    widths = blk.get("widths")  # in cm, one per column
    if widths:
        t.autofit = False
        for j, col in enumerate(t.columns):
            if j < len(widths):
                col.width = Cm(widths[j])  # sets <w:gridCol>, which Word/LibreOffice honour
    for i, row in enumerate(rows):
        for j in range(ncols):
            cell = t.cell(i, j)
            if widths and j < len(widths):
                cell.width = Cm(widths[j])
            val = row[j] if j < len(row) else ""
            p = cell.paragraphs[0]
            if blk.get("align"):
                p.alignment = ALIGN.get(blk["align"], WD_ALIGN_PARAGRAPH.LEFT)
            _add_inline(p, str(val), bold=blk.get("header", True) and i == 0, size=blk.get("size", 11))
    sd.add_paragraph()


def _build_body(tpl, blocks):
    sd = tpl.new_subdoc()
    for blk in blocks:
        kind = blk.get("type", "para")
        if kind == "space":
            sd.add_paragraph()
        elif kind == "page_break":
            sd.add_page_break()
        elif kind == "table":
            _table(sd, blk)
        elif kind == "heading":
            lvl = int(blk.get("level", 1))
            p = sd.add_paragraph()
            p.alignment = ALIGN.get(blk.get("align", "left"), WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.space_before = Pt(10 if lvl == 1 else 6)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            _add_inline(p, blk.get("text", ""), bold=True, size=HEADING_SIZE.get(lvl, 12.5))
        elif kind == "list":
            style = "List Number" if blk.get("numbered") else "List Bullet"
            for item in blk.get("items", []):
                p = sd.add_paragraph(style=style)
                p.paragraph_format.space_after = Pt(2)
                _add_inline(p, str(item), size=blk.get("size", 12))
            sd.add_paragraph().paragraph_format.space_after = Pt(0)
        else:
            p = sd.add_paragraph()
            p.alignment = ALIGN.get(blk.get("align", "left"), WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.space_after = Pt(blk.get("space_after", 4))
            _add_inline(p, blk.get("text", ""), bold=blk.get("bold", False),
                        italic=blk.get("italic", False), size=blk.get("size", 12))
    return sd


def _signature(template: Path) -> Path:
    """The job folder's copy (refreshed from Nextcloud); the repo copy when run standalone."""
    p = Path(template).parent / "assets" / "signature.png"
    return p if p.exists() else ROOT / "assets" / "signature.png"


def render(template: Path, content: dict, out: Path, job_id: str | None = None) -> Path:
    tpl = DocxTemplate(str(template))
    sig = content.get("signature", True)
    ctx = {
        "date": content.get("date") or "",
        "memo": content.get("memo"),
        "title": content.get("title"),
        "body": _build_body(tpl, content.get("blocks", [])),
        "signature": InlineImage(tpl, str(_signature(template)), width=Cm(5.5)) if sig else None,
    }
    tpl.render(ctx, autoescape=True)
    if job_id:
        tpl.docx.core_properties.identifier = f"gcmv-job:{job_id}"
    if content.get("title"):
        tpl.docx.core_properties.title = content["title"]
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(out))
    return out


if __name__ == "__main__":
    import sys
    tpl_path, content_path, out_path = map(Path, sys.argv[1:4])
    render(tpl_path, json.loads(content_path.read_text()), out_path, job_id="selftest")
    print(out_path)
