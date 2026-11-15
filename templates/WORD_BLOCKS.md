# Word document blocks (`content.json` → `blocks`)

Each block is one JSON object. Inside any `text` / item / table cell: `**bold**`, `*italic*`, `\n` = line break.
Bengali text is fine anywhere (Unicode only).

| type | fields |
|---|---|
| `para` | `text`, `align` (left/center/right/justify), `bold`, `italic`, `size` (pt, default 12), `space_after` (pt) |
| `heading` | `text`, `level` (1 = 16pt, 2 = 14pt, 3 = 12.5pt), `align` |
| `list` | `items` (list of strings), `numbered` (true = 1. 2. 3., false = bullets), `size` |
| `table` | `rows` (list of lists), `header` (bold first row, default true), `widths` (cm per column), `border` (default true), `align`, `size` (default 11) |
| `space` | an empty line |
| `page_break` | start a new page |

Word has no "fill-in-the-blank line" helper: for blanks use underscores (`__________`) or a table with empty cells.
