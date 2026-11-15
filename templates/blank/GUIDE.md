# Other document (no letterhead)

For forms, lists, timetables, routines, notes — anything that is not a notice/letter or a question paper.
If it is really an official notice or letter that belongs on the school letterhead, tell him to start
again with "Notice or letter" (the letterhead is not available here).
Keep the design plain and print-friendly: black text, A4.

## PDF output
- Write `main.typ` from scratch: `#set page(paper: "a4", margin: 2cm)`,
  `#set text(font: ("Liberation Sans", "Noto Sans Bengali"), size: 12pt)`.
- Use `#table(...)`, `#grid(...)`, lists (`- item`, `+ item`), `#align(center)[...]`, `#pagebreak()` as needed.
- Then call `compile_pdf` with `main.typ`.

## Word (.docx) output
- Write `content.json` (see `example_content.json`) with `title` (or null) and `blocks`.
  Block types are listed in `WORD_BLOCKS.md`.
- Usable width on the page is 17 cm (keep table `widths` within that).
- Then call `render_docx` with `content.json`.
