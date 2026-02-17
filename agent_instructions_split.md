# Agent Instructions: Split Mistral OCR into Individual Articles

This is the reusable prompt template for article-splitting agents.
Replace `{OCR_FILE}`, `{OUTPUT_DIR}`, `{VOLUME}`, `{ISSUE}`, `{DATE}`, and `{YEAR}` with actual values.

---

You are splitting a Mistral OCR transcription of a single issue of the American Sentinel into individual article files with YAML frontmatter.

Do NOT write any scripts, code, or programs. Do ALL work by reading, thinking, and writing files directly.

## YOUR ISSUE

- OCR file: `{OCR_FILE}`
- Output directory: `{OUTPUT_DIR}`
- Volume: {VOLUME}, Issue: {ISSUE}, Date: {DATE}

## STEP 1: Read the OCR file

Read the entire OCR file. It contains page-by-page OCR output with `PAGE N` headers and image references. Ignore the page headers, page numbers, running titles ("THE AMERICAN SENTINEL"), and image references — these are OCR artifacts, not article content.

## STEP 2: Identify articles

Split the content into individual articles. Each article is one of:
- A titled article (heading followed by body text)
- A short editorial note (a paragraph or two without a heading)
- A reprint from another publication (ends with "—*Source Name*")

Every article — no matter how short — gets its OWN file. Do NOT bundle multiple short items into one file. Each short editorial note is its own article.

SKIP these (do NOT create files for):
- Advertisements, subscription info, price lists
- "Terms" / subscription terms blocks
- Boilerplate publisher info that repeats every issue

## STEP 3: Create the masthead file

Create `00_masthead.md` with NO YAML frontmatter. Extract from Page 1:
- Publication name, motto, volume, number, date
- Publisher info, editor, associate editors

Example format:
```
AMERICAN SENTINEL

"If any Man Hear My Words, and Believe not, I Judge him not: for I Came not to Judge the World, but to Save the World."

VOLUME 6.

NEW YORK, JANUARY 1, 1891.

NUMBER 1.

# American Sentinel.

PUBLISHED WEEKLY BY THE

PACIFIC PRESS PUBLISHING COMPANY.

No. 43 BOND STREET, NEW YORK.

Entered at the New York Post-Office.

EDITOR, ALONZO T. JONES.

ASSOCIATE EDITORS, CALVIN P. BOLLMAN.

WILLIAM H. MCKEE.
```

## STEP 4: Create individual article files

### File naming

Pattern: `[##]_[Article-Title]_[Author-Initials].md`
- `##` = two-digit sequence number (01, 02, 03...)
- `Article-Title` = slugified title (spaces→hyphens, remove special chars)
- `Author-Initials` = only for `attribution: "explicit"` (omit otherwise)
- For untitled short notes, derive a brief descriptive title from the content

### YAML frontmatter

Every article file (except masthead) MUST have YAML frontmatter:

**For articles with author initials at the end** (`attribution: "explicit"`):
```yaml
---
title: "The Situation as It Is To-day"
author: "Alonzo T. Jones"
author_short: "ATJ"
date: 1891-XX-XX
publication: "American Sentinel"
volume: 6
issue: XX
attribution: "explicit"

principles:
  - "Church and State"

applications:
  - "Religious Legislation"

keywords:
  - Blair Bill
---
```

**For unsigned editorial content** (`attribution: "editorial"`):
```yaml
---
title: "Pope Complains to Czar"
date: 1891-XX-XX
publication: "American Sentinel"
volume: 6
issue: XX
attribution: "editorial"

principles:
  - "Persecution"

applications:
  - "Religious Intolerance"

keywords:
  - pope
  - czar
---
```

**For reprints from other publications** (`attribution: "reprint"`):
```yaml
---
title: "Religion and the Public Schools"
date: 1891-XX-XX
publication: "American Sentinel"
volume: 6
issue: XX
attribution: "reprint"
original_publication: "New York Sun"

principles:
  - "Religion and Education"

applications:
  - "State Schools and Religious Instruction"

keywords:
  - public schools
---
```

### Attribution rules

- **explicit**: Author initials appear at the END of the article (e.g., "A. T. J." on last line). Remove the initials from the body text — they go in the YAML only.
- **editorial**: No author indicated. Unsigned content by editorial staff. Do NOT put an author field in frontmatter.
- **reprint**: Article ends with "—*Source Name*" pattern. The `original_publication` field names the source. Keep the source attribution line at the end of the body text. No `author` field in frontmatter.

### Known author initials for 1891

- ATJ = Alonzo T. Jones (editor)
- CPB = C. P. Bollman (associate editor)
- WHM = W. H. McKee (associate editor)
- WAB = W. A. Blakely
- WNG = W. N. Glenn
- AOT = A. O. Tait
- AFB = A. F. Ballenger
- WAC = W. A. Colcord
- RFC = R. F. Cottrell
- GEF = G. E. Fifield

If you see initials NOT in this list, use them as-is and note them in uncertainties.md.

### CAUTIONS

- Datelines like "New York, January 5" are NOT authors
- Join text that flows across page/column breaks into continuous paragraphs
- Remove page headers (page numbers, "THE AMERICAN SENTINEL" running title)
- Preserve original spelling exactly (e.g., "to-day", "connexion")
- Preserve original punctuation and capitalization
- Do NOT insert [sic] or inline notes
- Preserve italics as *italics*
- Block quotes use `>` markdown syntax

## STEP 5: Categorization

For principles, choose 1-3 from ONLY this list:
- Religious Liberty
- Church and State
- Limits of Civil Authority
- Persecution
- Constitutional Principles
- Religion and Education
- The Sabbath Question

For applications, choose 1-4 from ONLY this list:
- Freedom of Conscience, Freedom of Worship, Right to Dissent, Voluntary vs Coerced Religion, Minority Religious Rights
- Separation of Church and State, State Establishment of Religion, Government Favoritism toward Religion, Religious Institutions and Civil Power, Protestant-Catholic Alliance, Christian Nation Claims
- Proper Role of Government, Religious vs Civil Law, Legislating Morality, Enforced Religious Observance, Civil vs Religious Arguments, Religious Legislation
- Legal Persecution, Religious Intolerance, Historical Parallels, Fines and Imprisonment, Equal Protection
- First Amendment Protections, No Religious Tests, Rights of Conscience, Founding Fathers' Intent
- State Schools and Religious Instruction, Sectarian Education, Public Funding of Religious Schools, Bible Reading in Schools, Parental Rights
- Sunday Legislation, Sabbath Observance and Enforcement, Day of Rest / Labor Arguments

For keywords: specific names, bills, organizations, events mentioned.

## STEP 6: Create uncertainties.md

If there are any OCR quality issues or unclear readings, document them in `uncertainties.md` in the output directory. If there are none, still create the file with "No uncertainties noted."

## OUTPUT

When finished, return ONLY a single line:
`DONE: [issue identifier] — [number] articles created`

Do NOT list or summarize individual articles.
