# Editing a file he already has

The file he wants to change is in `original/` (see the first message for its name and where it came
from). It is shown to him on the document side as "Original". He may mark it with his pen.

If the app had made this file itself, it would have reopened that document directly — so this file
was **not made with this app** (or its sources are lost).

## 1. Read it first, before asking anything
- PDF: `pdftotext -layout original/<name> -` and look at the page images (`pdftoppm -r 100 -png
  original/<name> work_pages/p`, then Read the PNGs). `pdffonts` shows whether there is real text.
  If it is a scan (no text) or the text is garbage (old Bengali fonts), trust the images.
- Word (.docx): dump paragraphs, tables, headers/footers and text boxes with python-docx / lxml.
  `.doc` / `.odt`: `convert` it to docx first.
- Photo of a page: look at it.
Then tell him in one or two short lines what you see (kind of document, pages, main parts).

## 2. Word file → ask how to edit
Ask him (with a `why` line):
- **Change it in place** — keeps its exact look; best for small changes (dates, names, a line or two).
- **Remake it cleanly** on the school letterhead / a fresh layout — for bigger changes; the look changes.
In-place editing with python-docx: edit the text of existing runs to keep fonts; a phrase is often
split across several runs, so join and rewrite carefully; tables via `doc.tables`; headers/footers
via `section.header`; text boxes and shapes only through the XML (`w:txbxContent`). Insert a paragraph
by copying a neighbouring paragraph's XML. Save as `out/document.docx`, then `show_document`.

## 3. PDF or photo → it has to be remade
Tell him plainly, in one short message: this file was not made here, so to change it you will have
to remake it; the copy may not look exactly the same. Then interview him carefully (he is often
vague; be skeptical and confirm): what exactly does he want changed? Same look as the original, or
only the same content on the school letterhead? Keep the wording exactly? Signature? For printing or
for sending? PDF or Word? Is it a scan he wants retyped? Ask until you are confident; then remake it.

Layouts you can use (copies of the app's templates, with their own GUIDE.md):
- `lib/letterhead/` — school letterhead: in main.typ use `#import "lib/letterhead/letterhead.typ": *`
  For Word on the letterhead: write content.json as in `lib/letterhead/GUIDE.md` and call
  `render_docx` with `layout: "letterhead"` (or `"blank"` for a plain Word file).
- `lib/question_paper/` — question papers: `#import "lib/question_paper/template.typ": *`.
- `lib/blank/` — plain documents.
Build PDFs with `compile_pdf` (main.typ).

## 4. Saving
If the original came from his Nextcloud, ask: replace the original file (Nextcloud keeps the old
version), or save as a new copy (where, what name)? If it came from his device, ask where to save it.
