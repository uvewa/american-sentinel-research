# Adventist Pioneer Materials Transcription Project

## Purpose

This project involves extracting text from historical Seventh-day Adventist publications (periodicals, books, articles) for faithful reproduction in new layouts. The text itself must be preserved with complete accuracy while the visual layout will be redesigned.

## Core Principle

**ACCURACY IS THE HIGHEST PRIORITY.**

The original printed document is the authoritative source. Every word, every spelling, every punctuation mark in the original must be preserved exactly.

---

## Transcription Rules

### 1. EXACT TEXT REPRODUCTION

- Transcribe exactly what appears in the original printed document
- Preserve original spelling (including archaic spellings like "to-day" or "connexion")
- Preserve original punctuation exactly
- Preserve original capitalization patterns
- Never modernize language
- Never rephrase for clarity
- Never summarize
- Never omit text
- Never insert [sic]

### 2. PARAGRAPH STRUCTURE

- **Preserve paragraph breaks** - these represent the author's intended content structure
- **Line breaks within paragraphs may be ignored** - these are artifacts of column width, not content structure
- When text flows across columns or pages, join it as continuous paragraphs

### 3. HANDLING READING UNCERTAINTIES

When extracting text from scanned documents, there may be cases where:
- A letter or word is unclear
- The scan quality makes a character ambiguous
- A judgment call is required
- Library stamps, stains, or other marks obscure the text

**For every uncertainty or correction:**
- Make your best informed judgment for the main transcription
- Document the uncertainty in `uncertainties.md`
- Record: the location, what was unclear, what you transcribed, and why

**CRITICAL: Never add comments, placeholders, or notes inside the transcription text itself.** The transcription must remain clean and publication-ready. All notes, flags, and uncertainties go ONLY in the uncertainties.md file.

**When text is obscured (stamps, stains, damage) or uncertain:**

1. **Immediately do a focused second pass** on that specific area
   - Look more carefully at letter shapes
   - Consider context and grammar (does the sentence feel complete?)
   - Look for partial letters visible around/through obstructions
   - Ask: "Does this make full sense, or does it feel truncated?"

2. **Self-correct before finalizing** - resolve as many uncertainties as possible yourself

3. **Only after self-review**, if uncertainty remains:
   - Provide your best reading in the transcription
   - Flag it in uncertainties.md with LOW confidence
   - Note what is obscuring the text

Do NOT simply flag uncertain areas and move on. The second pass is your responsibility, not the reviewer's.

Example uncertainty log entry (after self-review):
```
Page 1, Column 3, Article "The Situation as It Is To-day"
- **Obstruction:** Library stamp overlays text
- **Second pass completed:** Yes
- **Transcribed as:** 'secure the "due observance" of Sunday as a day of "rest and worship"'
- **Confidence:** MEDIUM - resolved most uncertainties on second pass; "due" still slightly unclear
- **Reason:** Context and visible letter shapes confirm reading
```

### 4. WHAT TO PRESERVE VS. WHAT TO ADAPT

**PRESERVE EXACTLY:**
- All words and their spelling
- Punctuation (commas, semicolons, em-dashes, quotation marks, etc.)
- Paragraph breaks
- Article titles and headings
- Author attributions and bylines
- Scripture references
- Quoted material
- Italicized or emphasized text (note with *italics* or as appropriate for output format)

**MAY BE ADAPTED FOR NEW LAYOUT:**
- Line breaks within paragraphs
- Column structure
- Page breaks
- Header/footer placement
- Font choices and sizes

### 5. SPECIAL ELEMENTS

**Quotations and block quotes:**
- Preserve the quoted text exactly
- Note if text was indented/set apart in original

**Scripture references:**
- Preserve exactly as cited (e.g., "Acts 4:5-19" not "Acts 4:5-19, KJV")

**Names and titles:**
- Preserve exactly (e.g., "Col. Elliot F. Shepard" not "Colonel Elliott F. Shepard")

**Abbreviations:**
- Preserve as written (e.g., "Mr." "Rev." "etc.")

**Foreign words or phrases:**
- Preserve exactly as printed

**Small caps in original:**
- Note in output format (e.g., THE AMERICAN SENTINEL in small caps)

---

## File Organization

### Directory Structure

Transcribed files go in a `2. Transcribed/` folder parallel to `1. Originals/`:

```
[Publication] (Category)/
└── 0. [Publication]/
    ├── 1. Originals/
    │   └── [Year]/
    │       └── [Original PDF files]
    │
    └── 2. Transcribed/
        └── [Year]/
            └── [YYYY-MM-DD]_v[VV]n[NN]/
                ├── [Publication Name] (YYYY-MM-DD).md
                └── uncertainties.md
```

### Example

For `American Sentinel (1891-01-01) Volume 06, Number 01.pdf`:

```
American Sentinel (Religious Freedom)/
└── 0. American Sentinel/
    ├── 1. Originals/
    │   └── New Scan/
    │       └── 1891/
    │           └── American Sentinel (1891-01-01) Volume 06, Number 01.pdf
    │
    └── 2. Transcribed/
        └── 1891/
            └── 1891-01-01_v06n01/
                ├── American Sentinel (1891-01-01).md
                └── uncertainties.md
```

### Naming Conventions

- **Year folder**: `YYYY` (e.g., `1891`)
- **Issue folder**: `YYYY-MM-DD_vVVnNN` (e.g., `1891-01-01_v06n01`)
- **Transcription file**: `[Publication Name] (YYYY-MM-DD).md`
- **Uncertainties file**: Always `uncertainties.md` (context clear from folder)

### Output Files

For each source document (periodical issue), produce:

1. **Individual article files** (`.md`) - one file per article/item
2. **Masthead file** (`00_masthead.md`) - publication info, editors, volume/number
3. **Uncertainties file** (`uncertainties.md`) - log of any unclear readings and decisions made

### Article File Naming

Pattern: `[##]_[Article-Title]_[Author-Initials].md`

- **##** - Two-digit number preserving order in original issue (01, 02, 03...)
- **Article-Title** - Slugified title (spaces become hyphens, remove special characters)
- **Author-Initials** - When known/attributed (omit if anonymous or unclear)

Examples:
```
00_masthead.md
01_The-Situation-as-It-Is-To-day_ATJ.md
02_Sunday-Law-Doctrine_ATJ.md
03_The-Rights-of-Conscience_CPB.md
04_What-It-Involves.md
05_Archbishop-Irelands-Two-Proposals.md
```

### Common Author Initials (American Sentinel)

- **ATJ** - Alonzo T. Jones (Editor)
- **CPB** - C. P. Bollman (Associate Editor)
- **WHM** - W. H. McKee (Associate Editor)
- **WAB** - W. A. Blakely
- **WNG** - W. N. Glenn

Add to this list as authors are identified across issues.

---

## Quality Standard

The transcribed text should be suitable for republication. A reader of the new publication should receive exactly the same words the original readers received in the 19th century. The only difference should be the visual presentation, not the content.

---

## Remember

We are preserving the words of Adventist pioneers for future generations. Accuracy honors their work and serves readers who depend on faithful reproduction. When in doubt, document the uncertainty rather than guess silently.

---

## Article Categorization

### Purpose

Each article receives YAML frontmatter that enables:
- Searching by timeless principles (not just historical topics)
- Connecting 100+ year old writings to modern challenges
- Building a searchable catalog for research and advocacy

### YAML Frontmatter Schema

Every article file (except masthead, short items, and publication info) should have frontmatter at the top:

```yaml
---
title: "The Situation as It Is To-day"
author: "Alonzo T. Jones"
author_short: "ATJ"
date: 1891-01-01
publication: "American Sentinel"
volume: 6
issue: 1
attribution: "explicit"
original_publication: "N. Y. Tribune"  # for reprints only

principles:
  - "Church and State"
  - "Limits of Civil Authority"

applications:
  - "Religious Legislation"
  - "Sunday Laws"

keywords:
  - Blair Bill
  - National Reform Association
  - American Sabbath Union
---
```

### Field Definitions

**Required metadata:**
- `title` - Article title exactly as it appears
- `date` - Publication date (YYYY-MM-DD)
- `publication` - Publication name
- `volume` - Volume number
- `issue` - Issue number

**Author (when known):**
- `author` - Full name
- `author_short` - Initials used in file naming

**Attribution:**
- `attribution` - How authorship is determined (see values below)
- `original_publication` - Source publication name (reprints only)

**Categorization:**
- `principles` - Broad, timeless categories (1-3 typically)
- `applications` - Specific applications of those principles (1-4 typically)
- `keywords` - Specific names, bills, events, organizations mentioned

### Attribution Values

- **`explicit`** — Author is explicitly stated (initials at end of article or byline). The `author` and `author_short` fields are populated.
- **`reprint`** — Article reprinted from another publication. Identified by `—*Source Name*` pattern at end of body. The `original_publication` field names the source. No `author` field — the original author is part of the article text, not the Sentinel's attribution.
- **`editorial`** — Unsigned content by the editorial staff. No `author` field in frontmatter; the editor is inferred from the publication year at display time.

The `author` field is only populated for `explicit` attribution. For `editorial` articles, the responsible editor is looked up by year at display time rather than stored in each file.

### Seed Categories

#### Principles (Broad, Timeless)

1. **Religious Liberty** - Freedom of conscience, worship, belief
2. **Church and State** - Separation, establishment, entanglement
3. **Limits of Civil Authority** - What government can/cannot legislate
4. **Persecution** - Religious intolerance, legal penalties for belief
5. **Constitutional Principles** - First Amendment, religious tests, rights
6. **Religion and Education** - Schools, funding, curricula
7. **The Sabbath Question** - Sunday laws as a case study

#### Applications (Specific, Emerging)

Applications are specific subcategories under each principle. Use ONLY values from this list (do not invent new ones without adding them here first):

Under **Religious Liberty:**
- Freedom of Conscience
- Freedom of Worship
- Right to Dissent
- Voluntary vs Coerced Religion
- Minority Religious Rights

Under **Church and State:**
- Separation of Church and State
- State Establishment of Religion
- Government Favoritism toward Religion
- Religious Institutions and Civil Power
- Protestant-Catholic Alliance
- Christian Nation Claims

Under **Limits of Civil Authority:**
- Proper Role of Government
- Religious vs Civil Law
- Legislating Morality
- Enforced Religious Observance
- Civil vs Religious Arguments
- Religious Legislation

Under **Persecution:**
- Legal Persecution
- Religious Intolerance
- Historical Parallels
- Fines and Imprisonment
- Equal Protection

Under **Constitutional Principles:**
- First Amendment Protections
- No Religious Tests
- Rights of Conscience
- Founding Fathers' Intent

Under **Religion and Education:**
- State Schools and Religious Instruction
- Sectarian Education
- Public Funding of Religious Schools
- Bible Reading in Schools
- Parental Rights

Under **The Sabbath Question:**
- Sunday Legislation
- Sabbath Observance and Enforcement
- Day of Rest / Labor Arguments

### Categorization Guidelines

**Focus on TIMELESS PRINCIPLES, not historical specifics:**
- The Blair Bill is a keyword; "Religious Legislation" is the application
- Colonel Shepard is a keyword; "Persecution" is the principle
- The Inquisition is a keyword; "Historical Parallels" is the application

**Ask: "What modern situation would this article help someone facing?"**
- Someone facing workplace religious discrimination → Freedom of Conscience
- Someone opposing a local Sunday ordinance → Sunday Legislation, Limits of Civil Authority
- Someone arguing against state funding for religious schools → Religion and Education

**Multiple principles are normal:**
- An article about Sunday laws often touches Church and State AND Limits of Civil Authority AND The Sabbath Question

**Let taxonomy evolve:**
- If a new application pattern emerges repeatedly, add it to the list
- The goal is discoverability, not rigid classification

### Files That Get Frontmatter

**YES - Add frontmatter:**
- Articles with substantive content
- Editorial pieces
- Reprinted articles (from other publications)
- Letters with substantive arguments

**NO - Skip frontmatter:**
- `00_masthead.md` - Publication metadata only
- `uncertainties.md` - Process documentation
- Short items/notes without substantive argument
- Pure advertisements or subscription info

### Workflow Integration

When transcribing an article:

1. Extract text faithfully (existing workflow)
2. Read and understand the article's arguments
3. Identify the timeless principles being discussed
4. Assign 1-3 broad principles
5. Note 1-4 specific applications
6. Add relevant keywords (names, bills, organizations, events)
7. Write the complete file with frontmatter at top

The categorization happens DURING transcription, not as a separate pass
