# /// script
# requires-python = ">=3.11"
# dependencies = ["python-docx==1.2.0"]
# ///
"""Generate blank.docx: a plain A4 docxtpl template (no letterhead, no signature).

Never hand-edit blank.docx — change this script and re-run:
    uv run templates/blank/build_docx.py

Placeholders filled by app/docx_fill.py: {{ title }}, {{p body }}.
"""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = Path(__file__).parent
LATIN, BENGALI = "Arial", "Nirmala UI"


def set_fonts(el):
    rpr = el.get_or_add_rPr()
    fonts = OxmlElement("w:rFonts")
    for k, v in (("w:ascii", LATIN), ("w:hAnsi", LATIN), ("w:cs", BENGALI)):
        fonts.set(qn(k), v)
    rpr.insert(0, fonts)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "en-IN")
    lang.set(qn("w:bidi"), "bn-IN")
    rpr.append(lang)


def line(doc, text, *, align=WD_ALIGN_PARAGRAPH.LEFT, bold=False, size=None, before=0, after=0):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(before), Pt(after)
    r = p.add_run(text)
    set_fonts(r._r)
    if bold:
        r.bold = True
        r._r.get_or_add_rPr().append(OxmlElement("w:bCs"))
    if size:
        r.font.size = Pt(size)
    return p


doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin = sec.bottom_margin = Cm(2)
sec.left_margin = sec.right_margin = Cm(2)

normal = doc.styles["Normal"]
normal.font.size = Pt(12)
set_fonts(normal.element)
normal.paragraph_format.space_after = Pt(6)
for name in ("List Bullet", "List Number"):
    set_fonts(doc.styles[name].element)

line(doc, "{%p if title %}")
line(doc, "{{ title }}", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=18, after=12)
line(doc, "{%p endif %}")
line(doc, "{{p body }}")

doc.core_properties.author = "Gandhi Colony Madhyamik Vidyalaya"
out = HERE / "blank.docx"
doc.save(out)
print(f"wrote {out}")
