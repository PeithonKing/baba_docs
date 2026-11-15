// =============================================================================
// GCMV letterhead — layout library. Do NOT edit per document.
// A document imports this and calls `#show: letterhead.with(...)`.
// =============================================================================

#let school = (
  name: "GANDHI COLONY MADHYAMIK VIDYALAYA",
  subtitle: "Govt. Sponsored Higher Secondary School",
  medium: "English and Bengali Medium",
  address: "REGENT PARK, KOLKATA - 700 040",
  estd: "ESTD - 1950",
  se-index: "A3 - 033",
  hs-code: "101117",
  dise: "19170109815",
  phone: "033 2412 0078",
)

#let ink = rgb("#2f3193")

// Body: Liberation Sans has Arial's exact metrics, so PDF and Word line up.
#let body-fonts = ("Liberation Sans", "Noto Sans Bengali")

#let _detail(label, value) = [#text(weight: "bold")[#label] #value]

#let logo-size = 2.5cm

#let letterhead-header(header-font: "Poppins", date: none) = {
  set text(fill: ink)
  // Crest on the left; the title block is centred in the space to its right.
  grid(
    columns: (auto, 1fr),
    column-gutter: 0.5cm,
    align: (left + horizon, center + horizon),
    image("/assets/logo.svg", height: logo-size),
    [
      #text(font: (header-font, "Noto Sans Bengali"), weight: "extrabold", size: 16pt, tracking: 0.2pt)[#school.name]
      #v(-0.55em)
      #text(font: body-fonts, size: 12pt)[#school.subtitle]
      #v(-0.6em)
      #text(font: body-fonts, size: 10.5pt)[#school.medium]
      #v(-0.6em)
      #text(font: body-fonts, size: 9.5pt, tracking: 0.8pt)[#school.address]
      #v(-0.6em)
      #text(font: body-fonts, size: 9.5pt, tracking: 0.8pt)[#school.estd]
    ],
  )
  v(0.4em)
  set text(font: body-fonts, size: 10pt)
  grid(
    columns: (1fr, auto),
    row-gutter: 0.45em,
    _detail("S.E. INDEX NO.:", school.se-index), _detail("Phone:", school.phone),
    _detail("H.S. CODE NO:", school.hs-code), if date != none { _detail("Date:", date) },
    _detail("DISE Code:", school.dise), [],
  )
  v(-0.2em)
  line(length: 100%, stroke: 1pt + ink)
}

/// signature: true → default headmaster signature; a path string → that image; false → none.
#let letterhead(
  header-font: "Poppins",
  date: none,
  memo: none,
  title: none,
  signature: true,
  lang: "en",
  body,
) = {
  set document(title: if title != none { title } else { "Letter" }, author: "Gandhi Colony Madhyamik Vidyalaya")
  set page(paper: "a4", margin: (top: 1.4cm, bottom: 2cm, x: 2.2cm))
  set text(font: body-fonts, size: 12pt, lang: lang)
  set par(justify: false, leading: 0.75em)

  letterhead-header(header-font: header-font, date: date)

  if memo != none {
    v(0.3em)
    text(size: 10.5pt)[#text(weight: "bold")[Memo No.:] #memo]
  }
  v(1.6em)
  if title != none {
    align(center, text(size: 18pt, weight: "bold")[#title])
    v(0.9em)
  }
  body

  if signature != false {
    v(1.8em)
    let src = if type(signature) == str { signature } else { "/assets/signature.png" }
    image(src, width: 5.5cm)
  }
}
