# /// script
# requires-python = ">=3.11"
# dependencies = ["python-docx==1.2.0"]
# ///
"""Generate letterhead.docx (a docxtpl template) from code, so it is reproducible.

Never hand-edit letterhead.docx — change this script and re-run:
    uv run templates/letterhead/build_docx.py

Placeholders filled at runtime by app/docx_fill.py:
    {{ date }}, {{ memo }}, {{ title }}, {{p body }} (subdoc), {{ signature }} (image)
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
LOGO = HERE.parent.parent / "assets" / "logo.png"
INK = RGBColor(0x2F, 0x31, 0x93)

SCHOOL = dict(
    name="GANDHI COLONY MADHYAMIK VIDYALAYA",
    subtitle="Govt. Sponsored Higher Secondary School",
    medium="English and Bengali Medium",
    address="REGENT PARK, KOLKATA - 700 040",
    estd="ESTD - 1950",
    se_index="A3 - 033",
    hs_code="101117",
    dise="19170109815",
    phone="033 2412 0078",
)

# Fonts chosen to exist on Windows/Office; phones substitute their own (no tofu,
# because all Bengali is Unicode and tagged as complex script).
LATIN = "Arial"
HEADER = "Arial Black"
BENGALI = "Nirmala UI"


def set_fonts(rpr_parent, latin=LATIN, cs=BENGALI):
    """Set ascii/hAnsi/cs fonts and Bengali language on a style or run rPr."""
    rpr = rpr_parent.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for k in ("w:ascii", "w:hAnsi"):
        fonts.set(qn(k), latin)
    fonts.set(qn("w:cs"), cs)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "en-IN")
    lang.set(qn("w:bidi"), "bn-IN")


def run(par, text, *, bold=False, size=None, color=None, font=None, spacing=None):
    r = par.add_run(text)
    set_fonts(r._r, latin=font or LATIN)
    if bold:
        r.bold = True
        rpr = r._r.get_or_add_rPr()
        rpr.append(OxmlElement("w:bCs"))
    if size:
        r.font.size = Pt(size)
        szcs = OxmlElement("w:szCs")
        szcs.set(qn("w:val"), str(int(size * 2)))
        r._r.get_or_add_rPr().append(szcs)
    if color:
        r.font.color.rgb = color
    if spacing is not None:
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(spacing))
        r._r.get_or_add_rPr().append(sp)
    return r


def para(doc_or_cell, align=WD_ALIGN_PARAGRAPH.LEFT, after=0, before=0):
    p = doc_or_cell.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_after, pf.space_before = Pt(after), Pt(before)
    pf.line_spacing = 1.0
    return p


def bottom_border(p, color="2F3193", size=8):
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "1"), ("w:color", color)):
        b.set(qn(k), v)
    bdr.append(b)
    ppr.append(bdr)


def no_borders(table):
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "nil")
        borders.append(e)
    tblpr.append(borders)


doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(1.4), Cm(2)
sec.left_margin = sec.right_margin = Cm(2.2)

normal = doc.styles["Normal"]
normal.font.size = Pt(12)
set_fonts(normal.element)
normal.paragraph_format.space_after = Pt(6)

# Header: invisible 2-column table [crest | title block centred in the rest].
WIDTHS = (2.7, 13.9)  # cm; total = 16.6 cm usable width
head = doc.add_table(rows=1, cols=2)
head.alignment = WD_TABLE_ALIGNMENT.CENTER
head.autofit = False
no_borders(head)
for col, w in zip(head.columns, WIDTHS):
    col.width = Cm(w)
for cell, w in zip(head.rows[0].cells, WIDTHS):
    cell.width = Cm(w)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
lp = head.cell(0, 0).paragraphs[0]
lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
lp.paragraph_format.space_after = Pt(0)
lp.add_run().add_picture(str(LOGO), height=Cm(2.4))
mid = head.cell(0, 1)
p = mid.paragraphs[0]
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(0)
run(p, SCHOOL["name"], bold=True, size=14, color=INK, font=HEADER)
run(para(mid, WD_ALIGN_PARAGRAPH.CENTER), SCHOOL["subtitle"], size=12, color=INK)
run(para(mid, WD_ALIGN_PARAGRAPH.CENTER), SCHOOL["medium"], size=10.5, color=INK)
run(para(mid, WD_ALIGN_PARAGRAPH.CENTER), SCHOOL["address"], size=9.5, color=INK, spacing=16)
run(para(mid, WD_ALIGN_PARAGRAPH.CENTER), SCHOOL["estd"], size=9.5, color=INK, spacing=16)
para(doc, after=4)

rows = [
    (("S.E. INDEX NO.: ", SCHOOL["se_index"]), ("Phone: ", SCHOOL["phone"])),
    (("H.S. CODE NO: ", SCHOOL["hs_code"]), ("Date: ", "{{ date }}")),
    (("DISE Code: ", SCHOOL["dise"]), None),
]
t = doc.add_table(rows=len(rows), cols=2)
t.alignment = WD_TABLE_ALIGNMENT.CENTER
no_borders(t)
for i, (left, right) in enumerate(rows):
    for j, cell_val in enumerate((left, right)):
        cell = t.cell(i, j)
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.RIGHT
        cp.paragraph_format.space_after = Pt(0)
        if cell_val:
            run(cp, cell_val[0], bold=True, size=10, color=INK)
            run(cp, cell_val[1], size=10, color=INK)
t.columns[0].width = Cm(11)
t.columns[1].width = Cm(5.6)

rule = para(doc, after=6)
bottom_border(rule)

memo = para(doc)
run(memo, "{%p if memo %}")
memo_line = para(doc, after=4)
run(memo_line, "Memo No.: ", bold=True, size=10.5)
run(memo_line, "{{ memo }}", size=10.5)
run(para(doc), "{%p endif %}")

run(para(doc), "{%p if title %}")
run(para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=18, after=12), "{{ title }}", bold=True, size=18)
run(para(doc), "{%p endif %}")

run(para(doc), "{{p body }}")

run(para(doc), "{%p if signature %}")
run(para(doc, before=20), "{{ signature }}")
run(para(doc), "{%p endif %}")

doc.core_properties.author = "Gandhi Colony Madhyamik Vidyalaya"
out = HERE / "letterhead.docx"
doc.save(out)
print(f"wrote {out}")
