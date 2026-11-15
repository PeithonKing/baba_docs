# Letterhead template (notices, circulars, letters)

## PDF output
- Write `main.typ` in the job folder. Start from `example.typ`:
  `#import "letterhead.typ": *` then `#show: letterhead.with(date: ..., title: ..., memo: ..., signature: true)`.
- Never edit `letterhead.typ` (the school header layout). Only write the body in `main.typ`.
- Parameters: `date` (e.g. "2 Jan 2026"), `title` (e.g. "Notice", "Circular", or none for a letter),
  `memo` (memo/reference number or none), `signature` (true = headmaster's signature, false = none),
  `lang` ("bn" if mainly Bengali).
- Body is plain typst markup: paragraphs separated by a blank line, `\` for a line break,
  `*bold*`, `_italic_`, `#set text(style: "italic")` for an all-italic body, `#table(...)` for tables,
  `#align(center)[...]`, `#v(1em)` for space. Bengali text works directly (Unicode).
- Then call the `compile_pdf` tool with `main.typ`.

## Word (.docx) output
- Write `content.json` in the job folder (see `example_content.json`):
  `date`, `memo`, `title`, `signature` (bool) and `blocks`. Block types (para, heading, list,
  table, space, page_break) are listed in `WORD_BLOCKS.md`.
- Usable width on the page is 16.6 cm (keep table `widths` within that).
- Then call the `render_docx` tool with `content.json`.

## Conventions seen in his notices
- Title "Notice" centred and bold; body often italic; closing line like "Your active cooperation is solicited."
- Date format like "2 Jan 2026". Use today's date unless he gives one.
