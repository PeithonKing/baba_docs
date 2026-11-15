# Question paper template (PDF only)

- Write `main.typ` in the job folder. Start from `starter.typ` (it shows every question format),
  and look at `examples/*.typ` (when present: real papers, kept out of git) to copy the style from.
- Change the import to `#import "template.typ": *` (template.typ sits next to main.typ in the job folder).
- Never edit `template.typ`. Only write `main.typ`.
- Header fields in `question-paper.with(...)`: school-name (keep "GANDHI COLONY MADHYAMIK VIDYALAYA (HS)"),
  school-short "GCMV (HS)", exam-name, subject, subject-short, class, time, full-marks,
  running-header-left/right.
- Bengali paper: copy the setup from `examples/Bengali_10_2026.typ`
  (`lang: "bn"`, `font: ("Liberation Serif", "Noto Serif Bengali")`, the `bn()` / `bl()` digit helpers).
- Helpers: `section-header`, `marks`, `choices` / `mcq`, `passage-block`, `poem-block`, `hints-box`,
  `word-bank`, `or-divider`, `tf-row`, `ans-lines`, `blank`, `cause-effect-table`.
- Check that the marks add up to full marks; tell him if they don't.
- Then call the `compile_pdf` tool with `main.typ`.
