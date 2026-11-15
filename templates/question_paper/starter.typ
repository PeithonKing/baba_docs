// =============================================================================
// STARTER QUESTION PAPER TEMPLATE
// A ready-to-copy boilerplate for creating school & board question papers.
// =============================================================================

#import "template.typ": *

#show: question-paper.with(
  // School & Examination Identity
  school-name: "YOUR SCHOOL NAME (HS)",
  school-short: "YSN (HS)",
  exam-name: "ANNUAL EXAMINATION -- 2026",
  subject: "ENGLISH (SECOND LANGUAGE)",
  subject-short: "English",
  class: "Class X",
  paper-code: none,              // Optional, e.g. "Paper I" or "Code: 101"
  time: "3 Hours 15 Minutes",
  full-marks: 90,

  // Running Header & Footer (optional overrides)
  running-header-left: "Annual Examination -- 2026",
  running-header-right: "English (Second Language)",

  // First-page Candidate Box (set show-candidate-box: false to disable)
  show-candidate-box: true,
  candidate-fields: ([*Name:* ], [*Sec:*], [*Roll No:*]),

  // Top Corner Labels (set show-*: false to disable)
  show-marks-box: true,
  show-invigilator-box: true,
)

// =============================================================================
// SECTION A: READING COMPREHENSION
// =============================================================================
#section-header("SECTION A: READING COMPREHENSION (SEEN)", marks: 20)

*1. Read the following passage carefully and answer the questions that follow:*

#passage-block[
  Replace this text with your prose reading passage. The template automatically applies
  a clean left border, justified alignment, and comfortable line spacing suitable
  for official exam papers.
]

#v(0.3em)
*A. Choose the correct alternatives to complete the following sentences:* #marks("1 x 2 = 2")

#set enum(indent: 0pt, body-indent: 5pt, spacing: 0.45em)

+ The main theme of the given passage is:
  #choices(
    cols: 2,
    "First option",
    "Second option",
    "Third option",
    "Fourth option"
  )

+ The narrator was feeling:
  #choices(
    cols: 4,
    "Happy",
    "Sad",
    "Nervous",
    "Excited"
  )

#v(0.4em)
*B. Complete the following table:* #marks("1 x 2 = 2")

#table(
  columns: (1fr, 1fr),
  stroke: 0.5pt + black,
  inset: (x: 8pt, y: 6pt),
  align: (left + horizon),
  table.header([*Cause*], [*Effect*]),
  [The bell rang suddenly.], [],
  [], [The students entered their classrooms.]
)

#v(0.4em)
*C. Answer the following questions in complete sentences:*

+ What did the teacher advise the students to do? #marks(2)
  #ans-lines(count: 2)

+ Why was the boy reluctant to speak? #marks(2)
  #ans-lines(count: 2)

// -----------------------------------------------------------------------------
// POEM COMPREHENSION
// -----------------------------------------------------------------------------
#v(0.5em)
*2. Read the poem and answer the questions that follow:*

#poem-block[
  The woods are lovely, dark and deep, \
  But I have promises to keep, \
  And miles to go before I sleep, \
  And miles to go before I sleep.
]

#v(0.3em)
*A. Fill in the blanks with information from the poem:* #marks("1 x 2 = 2")

+ The woods are described as dark, lovely, and #blank(40%).
+ The speaker has promises to keep before #blank(45%).

#v(0.4em)
*B. State whether the following statements are True or False:* #marks("1 x 2 = 2")

#tf-row[1. The speaker stopped in the woods to take a long rest.]
#tf-row[2. The journey of the traveler is far from over.]

#v(0.4em)
*C. Write 'T' for True and 'F' for False, and provide supporting phrases:* #marks("2 x 1 = 2")

#tf-supporting[1. The traveler wanted to stay longer in the woods.]


// =============================================================================
// SECTION B: GRAMMAR AND VOCABULARY
// =============================================================================
#section-header("SECTION B: GRAMMAR AND VOCABULARY", marks: 20)

*3. Fill in the blanks with appropriate Articles and Prepositions:* #marks("1 x 3 = 3")

Knowledge is #blank(50pt) great power, and diligence is the key #blank(50pt) success #blank(50pt) life.

#v(0.4em)
*4. Do as directed:* #marks("1 x 2 = 2")

+ The teacher solved the difficult puzzle. _(Change the voice)_
  #ans-lines(count: 1)

+ He said to me, "Are you joining the picnic?" _(Change into indirect speech)_
  #ans-lines(count: 1)

#v(0.4em)
*5. Replace the underlined words with suitable phrasal verbs from the list:* #marks("1 x 2 = 2")

#word-bank("look into", "give up", "call off")

+ The police will #underline[investigate] the incident. #h(1fr) #blank(110pt)
+ The committee decided to #underline[cancel] the annual meet. #h(1fr) #blank(110pt)


// =============================================================================
// SECTION C: WRITING SKILL
// =============================================================================
#section-header("SECTION C: WRITING SKILL", marks: 20)

*6. Write a paragraph on "The Importance of Tree Plantation" within 100 words using the hints below:* #marks(10)

#hints-box[
  *Hints:* _Trees produce oxygen --- prevent soil erosion --- maintain ecological balance --- provide fruits and shade --- need for mass tree plantation drives._
]

#v(0.8em)
*7. Answer any one of the following writing tasks:* #marks(10)

#hints-box(inset: (x: 10pt, y: 6pt))[
  *A.* Write a letter to your friend describing a recent science exhibition organized in your school.

  #or-divider()

  *B.* Write a notice as the Cultural Secretary inviting students to participate in the upcoming Inter-School Debate Competition.
]
