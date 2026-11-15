#import "letterhead.typ": *
#set page(paper: "a4", margin: (top: 1.2cm, bottom: 1cm, x: 2.2cm))
#set text(font: body-fonts, size: 10pt)

#for (f, label) in (
  ("Montserrat", "1. Montserrat ExtraBold"),
  ("Archivo", "2. Archivo Black"),
  ("Poppins", "3. Poppins Bold"),
  ("Liberation Sans", "4. Arial-like (Liberation Sans Bold) — same as Word fallback"),
) {
  text(size: 8pt, fill: gray)[#label]
  letterhead-header(header-font: f, date: "2 Jan 2026")
  v(1.6em)
}
