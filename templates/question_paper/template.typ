// =============================================================================
// TYPST QUESTION PAPER TEMPLATE
// A reusable, production-ready template for school examinations, summative tests,
// and board evaluations (Madhyamik / WBBSE / CBSE / ICSE style).
// =============================================================================

/// Renders a right-aligned bold marks indicator.
/// Automatically transforms ASCII 'x', 'X', and '*' to standard multiplication symbol '×'.
///
/// Examples:
///   `#marks([1 x 4 = 4])`   => 1 × 4 = 4
///   `#marks("1 x 4 = 4")`   => 1 × 4 = 4
///   `#marks(2)`             => 2
///   `#marks([2])`           => 2
///   `#marks(10)`            => 10
///   `#marks([1 + 1 = 2])`   => 1 + 1 = 2
#let marks(m) = {
  h(1fr)
  text(weight: "bold")[
    #show " x ": " × "
    #show " X ": " × "
    #show " * ": " × "
    #show regex("(?i)(\d+)\s*[xX*]\s*(\d+)"): it => {
      let parts = it.text.split(regex("(?i)[xX*]"))
      [#(parts.at(0).trim()) × #(parts.at(1).trim())]
    }
    #m
  ]
}

/// Alias used where a `marks` parameter shadows the helper.
#let marks-fn = marks

/// Inline dotted blank line for fill-in-the-blanks.
///
/// Parameters:
/// - `w`: Width of the blank line (e.g. `50pt` or `60%`).
/// - `thickness`: Stroke thickness (default: `0.75pt`).
#let ans-inline(w, thickness: 0.75pt) = {
  box(
    width: w,
    baseline: -1pt,
    line(length: 100%, stroke: (paint: black, dash: "dotted", thickness: thickness))
  )
}

/// Shorthand alias for ans-inline.
#let blank = ans-inline

/// Block-level dotted answer line for student written responses.
///
/// Parameters:
/// - `len`: Length of the dotted line (default: `100%`).
/// - `thickness`: Stroke thickness (default: `0.7pt`).
#let ans-line(len: 100%, thickness: 0.7pt) = {
  v(1pt)
  line(length: len, stroke: (paint: black, dash: "dotted", thickness: thickness))
  v(1pt)
}

/// Generates multiple dotted answer lines with comfortable spacing for student handwriting.
///
/// Parameters:
/// - `count`: Number of answer lines to generate (default: `2`).
/// - `len`: Length of each answer line (default: `100%`).
/// - `spacing`: Vertical spacing before each line (default: `1em`).
/// - `thickness`: Stroke thickness (default: `0.7pt`).
#let ans-lines(count: 2, len: 100%, spacing: 1em, thickness: 0.7pt) = {
  for i in range(count) {
    v(spacing)
    ans-line(len: len, thickness: thickness)
  }
}

/// Standard rectangular answer box for True / False or Yes / No entry.
#let tf-box = box(
  stroke: 0.75pt + black,
  width: 50pt,
  height: 15pt,
  baseline: 20%,
)

/// Creates a customizable True / False or Yes / No box with custom dimensions.
#let tf-box-custom(width: 50pt, height: 15pt, stroke: 0.75pt + black) = box(
  stroke: stroke,
  width: width,
  height: height,
  baseline: 20%,
)

/// Lays out a question statement with an answer box aligned to the right margin.
#let tf-row(statement, box: tf-box) = {
  grid(
    columns: (1fr, auto),
    align: (left + horizon, right + horizon),
    statement,
    box
  )
}

/// Lays out a True/False statement with a right-aligned box and a supporting
/// evidence / quotation blank line underneath.
#let tf-supporting(statement, label: [Supporting Words/Phrases:], blank: 72%, box: tf-box) = {
  tf-row(statement, box: box)
  v(1pt)
  text(style: "italic", size: 9pt)[#label]
  [ ]
  ans-inline(blank)
}

/// Formal Section Header with clean double horizontal rules.
/// Accepts positional or named marks argument:
///   `#section-header("SECTION A", "[20 Marks]")`
///   `#section-header("SECTION A", marks: 20)`
///   `#section-header("SECTION A", marks: "[20 Marks]")`
#let section-header(title, marks: none, ..args) = {
  let m = if marks != none {
    marks
  } else if args.pos().len() > 0 {
    args.pos().first()
  } else {
    none
  }

  let marks-rendered = if m != none {
    if type(m) == int or type(m) == float {
      "[" + str(m) + " Marks]"
    } else if type(m) == str {
      if not m.starts-with("[") and not m.ends-with("]") {
        if m.ends-with("Marks") {
          "[" + m + "]"
        } else {
          "[" + m + " Marks]"
        }
      } else {
        m
      }
    } else {
      m
    }
  } else {
    none
  }

  v(0.5em)
  block(
    width: 100%,
    stroke: (top: 0.8pt + black, bottom: 0.8pt + black),
    inset: (y: 4pt),
    [
      #grid(
        columns: (1fr, auto),
        align: (left + horizon, right + horizon),
        text(weight: "bold", size: 10pt)[#title],
        if marks-rendered != none [ #text(weight: "bold", size: 9.5pt)[#marks-rendered] ]
      )
    ]
  )
  v(0.25em)
}

/// Formal prose passage container with a neat left vertical bar.
#let passage-block(body) = {
  block(
    width: 100%,
    stroke: (left: 1.2pt + black),
    inset: (left: 10pt, top: 4pt, bottom: 4pt),
    [
      #set par(justify: true, leading: 0.52em, spacing: 0.42em)
      #body
    ]
  )
}

/// Formal poem container with left vertical bar and italicized verses.
#let poem-block(body) = {
  block(
    width: 100%,
    stroke: (left: 1.2pt + black),
    inset: (left: 12pt, top: 4pt, bottom: 4pt),
    [
      #set text(style: "italic")
      #set par(justify: false, leading: 0.56em, spacing: 0.4em)
      #body
    ]
  )
}

/// Clean framed container for writing hints, composition prompts, or instructions.
#let hints-box(body, title: none, inset: (x: 9pt, y: 5pt)) = {
  rect(
    width: 100%,
    stroke: 0.6pt + black,
    inset: inset,
  )[
    #if title != none [ #title #h(4pt) ]
    #body
  ]
}

/// Framed centered box to display choices (e.g. phrasal verbs, word banks).
#let word-bank-box(body, title: none) = {
  align(center)[
    #rect(
      stroke: 0.6pt + black,
      inset: (x: 14pt, y: 4pt),
    )[
      #if title != none [ #title #h(8pt) ]
      #body
    ]
  ]
}

/// Streamlined Word Bank helper: takes words and formats them into a neat centered box.
///
/// Example:
///   `#word-bank("break out", "run after", "make out")`
#let word-bank(..words, title: [*List of Phrasal Verbs:*]) = {
  let word-items = words.pos().map(w => text(style: "italic")[#w])
  align(center)[
    #rect(
      stroke: 0.6pt + black,
      inset: (x: 14pt, y: 4pt),
    )[
      #if title != none [ #title #h(8pt) ]
      #word-items.join([, #h(10pt) ])
    ]
  ]
}

/// Centered divider between alternative questions (e.g. — OR —).
#let or-divider(label: [--- OR ---]) = {
  align(center)[
    #text(weight: "bold", size: 9.5pt)[#label]
  ]
}

/// Helper to detect if an item already begins with an option label like (a), (i), etc.
#let _has-label(itm) = {
  if type(itm) == str {
    return itm.starts-with(regex("^\([a-zA-Z0-9]+\)"))
  }
  if type(itm) == content {
    if itm.has("text") {
      return itm.text.starts-with(regex("^\([a-zA-Z0-9]+\)"))
    }
    if itm.has("children") and itm.children.len() > 0 {
      return _has-label(itm.children.first())
    }
  }
  return false
}

/// Lays out Multiple Choice Question (MCQ) options in a balanced grid.
/// Automatically prefixes options with labels like (a), (b), (c)... or (i), (ii)...
/// if labels are not already present.
///
/// Parameters:
/// - `cols`: Number of columns (1, 2, 3, or 4; default: 2).
/// - `gutter`: Gap between options (default: 3pt).
/// - `label-style`: Label prefix style: `"a"` for `(a)`, `"i"` for `(i)`, `"1"` for `(1)`, `"A"` for `(A)`, or `none`. An array of strings is used as custom labels, e.g. `("ক)", "খ)", ...)`.
/// - `..items`: Option strings or content blocks.
#let choices(
  cols: 2,
  gutter: 3pt,
  label-style: "a",
  ..items
) = {
  let labels-a = ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)")
  let labels-A = ("(A)", "(B)", "(C)", "(D)", "(E)", "(F)", "(G)", "(H)")
  let labels-i = ("(i)", "(ii)", "(iii)", "(iv)", "(v)", "(vi)", "(vii)", "(viii)")
  let labels-I = ("(I)", "(II)", "(III)", "(IV)", "(V)", "(VI)", "(VII)", "(VIII)")
  let labels-1 = ("(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)")

  let label-set = if label-style == "a" {
    labels-a
  } else if label-style == "A" {
    labels-A
  } else if label-style == "i" {
    labels-i
  } else if label-style == "I" {
    labels-I
  } else if label-style == "1" {
    labels-1
  } else if type(label-style) == array {
    label-style
  } else {
    ()
  }

  let formatted = ()
  for (idx, itm) in items.pos().enumerate() {
    let already = _has-label(itm)
    if already or label-set.len() <= idx {
      formatted.push([#itm])
    } else {
      let lbl = label-set.at(idx)
      formatted.push([#lbl #itm])
    }
  }

  grid(
    columns: (1fr,) * cols,
    gutter: gutter,
    ..formatted
  )
}

/// Alias for choices grid.
#let mcq-grid = choices
#let mcq-choices = choices

/// All-in-one MCQ question helper.
///
/// Example:
///   `#mcq([The word 'loaf' means:], ("to move around...", "to play..."), cols: 2)`
#let mcq(
  statement,
  options,
  cols: 2,
  marks: none,
  label-style: "a",
  gutter: 3pt,
) = {
  grid(
    columns: (1fr, auto),
    statement,
    if marks != none [ #marks-fn(marks) ]
  )
  v(0.2em)
  choices(cols: cols, gutter: gutter, label-style: label-style, ..options)
}

/// Cause & Effect Table helper.
#let cause-effect-table(..rows) = {
  table(
    columns: (1fr, 1fr),
    stroke: 0.5pt + black,
    inset: (x: 8pt, y: 6pt),
    align: (left + horizon),
    table.header([*Cause*], [*Effect*]),
    ..rows.pos().flatten()
  )
}

/// Candidate identification box rendered at the top of the question paper.
#let candidate-box(
  fields: ([*Name:* ], [*Sec:*], [*Roll No:*]),
  columns: (4.2fr, 1.2fr, 1.2fr, 1.5fr),
) = {
  rect(
    width: 100%,
    stroke: 0.6pt + black,
    inset: (x: 9pt, y: 8pt),
  )[
    #grid(
      columns: columns,
      gutter: 8pt,
      align: horizon,
      ..fields
    )
  ]
}

/// Main Question Paper Document Template.
#let question-paper(
  // Paper identity
  school-name: "GANDHI COLONY MADHYAMIK VIDYALAYA (HS)",
  school-short: none,
  exam-name: "MADHYAMIK THIRD SUMMATIVE TEST -- 2026",
  subject: "ENGLISH (SECOND LANGUAGE)",
  subject-short: none,
  class: "Class X",
  paper-code: none,
  time: "3 Hours 15 Minutes",
  full-marks: 90,
  time-label: "Time:",
  full-marks-label: "Full Marks:",
  page-label: "Page",
  of-label: "of",
  page-numbering: "1",

  // Metadata
  title: none,
  author: "West Bengal Board of Secondary Education",

  // Page & typography settings
  paper: "a4",
  margin: (top: 1.25cm, bottom: 1.25cm, left: 1.4cm, right: 1.4cm),
  font: ("Liberation Serif", "Noto Serif Bengali"),
  font-size: 9.3pt,
  lang: "en",
  leading: 0.58em,
  spacing: 105%,

  // First-page header blocks
  show-marks-box: true,
  marks-box-label: [Marks Obtained:],
  show-invigilator-box: true,
  invigilator-box-label: [Invigilator's Signature],
  show-candidate-box: true,
  candidate-fields: ([*Name:* ], [*Sec:*], [*Roll No:*]),
  candidate-columns: (4.2fr, 1.2fr, 1.2fr, 1.5fr),

  // Running header and footer custom text
  running-header-left: none,
  running-header-right: none,
  running-footer-left: none,
  turn-over-text: [ _Turn Over $arrow.r$_ ],
  end-of-paper-text: [ _[ End of Question Paper ]_ ],

  body
) = {
  let doc-title = if title != none {
    title
  } else {
    exam-name + " - " + subject
  }

  set document(
    title: doc-title,
    author: author,
  )

  let header-left = if running-header-left != none {
    running-header-left
  } else {
    exam-name
  }

  let header-right = if running-header-right != none {
    running-header-right
  } else {
    subject
  }

  let effective-school-short = if school-short != none {
    school-short
  } else {
    school-name
  }

  let effective-subj-short = if subject-short != none {
    subject-short
  } else {
    subject
  }

  let footer-left = if running-footer-left != none {
    running-footer-left
  } else {
    [#effective-school-short -- #effective-subj-short -- #class]
  }

  set page(
    paper: paper,
    margin: margin,
    header: context {
      let page_number = counter(page).get().first()
      if page_number > 1 [
        #set text(size: 8.5pt, font: font)
        #grid(
          columns: (1fr, 1fr),
          align: (left, right),
          smallcaps[#header-left],
          smallcaps[#header-right]
        )
        #v(-4pt)
        #line(length: 100%, stroke: 0.4pt + black)
      ]
    },
    footer: context {
      let page_number = counter(page).get().first()
      let total_pages = counter(page).final().first()
      set text(size: 8.5pt, font: font)
      line(length: 100%, stroke: 0.4pt + black)
      v(1pt)
      grid(
        columns: (1.5fr, 1fr, 1fr),
        align: (left, center, right),
        [#footer-left],
        [#page-label #numbering(page-numbering, page_number) #of-label #numbering(page-numbering, total_pages)],
        if page_number < total_pages [ #turn-over-text ] else [ #end-of-paper-text ]
      )
    }
  )

  set text(
    font: font,
    size: font-size,
    lang: lang,
    spacing: spacing,
  )

  set par(
    justify: true,
    leading: leading,
  )

  // Top Title Block
  align(center)[
    #text(size: 16pt, weight: "bold")[#school-name] \
    #text(size: 13.5pt, weight: "bold")[#exam-name] \
    #text(size: 11pt, weight: "bold")[#subject]
    #if paper-code != none [ \ #text(size: 10pt, weight: "bold")[#paper-code] ]
  ]

  v(1pt)

  // Examination Metadata Bar
  grid(
    columns: (1fr, auto, 1fr),
    align: (left + horizon, center + horizon, right + horizon),
    if show-marks-box [
      #set par(leading: 0.5em)
      #text(size: 8.3pt, weight: "bold")[#marks-box-label]
    ] else [],
    [
      #text(size: 9.5pt)[
        *#time-label* #time #h(18pt) | #h(18pt) *#full-marks-label* #full-marks
      ]
    ],
    if show-invigilator-box [
      #set par(leading: 0.5em)
      #text(size: 8.3pt, weight: "bold")[#invigilator-box-label]
    ] else []
  )

  v(4pt)

  // Candidate Information Box
  if show-candidate-box [
    #candidate-box(fields: candidate-fields, columns: candidate-columns)
    #v(0.25em)
  ]

  body
}
