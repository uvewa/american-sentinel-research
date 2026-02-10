#!/usr/bin/env python3
"""
Extract articles from IDML files into individual markdown files.

IDML files are ZIP archives containing XML (Adobe InDesign Markup Language).
This script reads the text content from Stories/*.xml, identifies issue
and article boundaries by paragraph styles, and outputs individual .md
files with YAML frontmatter.

Usage:
    python extract_idml.py <idml_file> [--output-dir PATH] [--dry-run]
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# --- Data Structures ---

@dataclass
class TextRun:
    """A run of text with character-level formatting."""
    text: str
    italic: bool = False
    bold: bool = False
    small_caps: bool = False
    superscript: bool = False


@dataclass
class Paragraph:
    """A paragraph with its style and text runs."""
    style: str
    runs: list[TextRun] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return ''.join(r.text for r in self.runs)

    @property
    def is_empty(self) -> bool:
        return not self.plain_text.strip()

    @property
    def is_separator(self) -> bool:
        text = self.plain_text.strip()
        return (
            self.style in ('Normal Center', 'Thoughtbreak')
            and bool(re.match(r'^[_*\-=~]{3,}$', text))
        )


@dataclass
class Article:
    """An extracted article."""
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    author: str = ''
    author_short: str = ''
    attribution: str = ''  # explicit | reprint | editorial
    original_publication: str = ''  # for reprints only


@dataclass
class Issue:
    """An issue of the publication."""
    volume: int = 0
    number: int = 0
    date_str: str = ''  # e.g., "January, 1886" or "January 1, 1889"
    year: int = 0
    month: int = 0
    day: int = 0
    location: str = ''
    motto: str = ''
    articles: list[Article] = field(default_factory=list)


# --- Known author initials ---

KNOWN_AUTHORS = {
    'A. T. J.': ('Alonzo T. Jones', 'ATJ'),
    'E. J. W.': ('Ellet J. Waggoner', 'EJW'),
    'C. P. B.': ('C. P. Bollman', 'CPB'),
    'W. H. M.': ('W. H. McKee', 'WHM'),
    'W. A. B.': ('W. A. Blakely', 'WAB'),
    'W. N. G.': ('W. N. Glenn', 'WNG'),
    'J. H. W.': ('James H. Waggoner', 'JHW'),
    'G. I. B.': ('George I. Butler', 'GIB'),
    'U. S.': ('Uriah Smith', 'US'),
    'S. N. H.': ('Stephen N. Haskell', 'SNH'),
}

# Reprint source pattern: —*Source Name*.  (optionally followed by footnote ref)
REPRINT_RE = re.compile(r'—\*([^*]+)\*\.?\s*(\[\d+\])?\s*$')

MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


# --- IDML Parsing ---

def get_story_order(idml_zip: zipfile.ZipFile) -> list[str]:
    """Get story file paths in document order from designmap.xml."""
    dm_content = idml_zip.read('designmap.xml').decode('utf-8')
    root = ET.fromstring(dm_content)

    ns = 'http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging'
    story_paths = []
    for elem in root:
        if elem.tag == f'{{{ns}}}Story':
            src = elem.get('src')
            if src:
                story_paths.append(src)

    return story_paths


def parse_story(xml_content: str) -> list[Paragraph]:
    """Parse a Story XML into a list of Paragraphs."""
    root = ET.fromstring(xml_content)
    paragraphs = []

    for story in root.iter('Story'):
        current_runs = []

        for psr in story:
            if psr.tag != 'ParagraphStyleRange':
                continue

            style = psr.get('AppliedParagraphStyle', '')
            style = style.replace('ParagraphStyle/', '').replace('$ID/', '')

            for csr in psr:
                if csr.tag != 'CharacterStyleRange':
                    continue

                char_style = csr.get('AppliedCharacterStyle', '')
                char_style = char_style.replace('CharacterStyle/', '').replace('$ID/', '')

                is_italic = 'Italic' in char_style or csr.get('FontStyle', '') == 'Italic'
                is_bold = 'Bold' in char_style or csr.get('FontStyle', '') == 'Bold'
                is_small_caps = 'Small Caps' in char_style or csr.get('Capitalization', '') == 'SmallCaps'
                is_super = 'Superscript' in char_style or csr.get('Position', '') == 'Superscript'

                for child in csr:
                    if child.tag == 'Content' and child.text:
                        # Clean up InDesign special characters
                        text = child.text
                        text = text.replace('\ufeff', '')  # BOM
                        text = text.replace('\u2028', '\n')  # line separator
                        text = text.replace('\u2029', '\n')  # paragraph separator
                        # Remove soft hyphens used for line-break hints
                        text = text.replace('\u00ad', '')
                        text = text.replace('\u200b', '')  # zero-width space

                        if text:
                            current_runs.append(TextRun(
                                text=text,
                                italic=is_italic,
                                bold=is_bold,
                                small_caps=is_small_caps,
                                superscript=is_super,
                            ))

                    elif child.tag == 'Br':
                        # Line break = end of this paragraph, start a new one
                        if current_runs:
                            paragraphs.append(Paragraph(style=style, runs=list(current_runs)))
                            current_runs = []
                        else:
                            paragraphs.append(Paragraph(style=style, runs=[]))

            # End of ParagraphStyleRange — if runs remain, they belong to this paragraph
            # But don't flush yet; they might continue in the next CSR of the same PSR
            # Actually, end of PSR means new paragraph style starts
            if current_runs:
                paragraphs.append(Paragraph(style=style, runs=list(current_runs)))
                current_runs = []

    return paragraphs


def classify_story(paragraphs: list[Paragraph]) -> str:
    """Classify a story as 'meta', 'content', or 'other'."""
    styles = {p.style for p in paragraphs if not p.is_empty}
    non_empty_count = sum(1 for p in paragraphs if not p.is_empty)
    if 'Volume and Number' in styles:
        return 'meta'
    heading_styles = {'Heading 1', 'Heading 2', 'Heading 2 Subtitle'}
    if styles & heading_styles and non_empty_count > 5:
        return 'content'
    # Large stories with Normal text are likely content too
    if non_empty_count > 20:
        return 'content'
    return 'other'


def extract_stories(idml_path: Path) -> list[tuple[str, str, list[Paragraph]]]:
    """Extract all stories from IDML, returning (path, type, paragraphs) tuples."""
    stories = []

    with zipfile.ZipFile(idml_path, 'r') as z:
        story_paths = get_story_order(z)

        for story_path in story_paths:
            if not story_path.startswith('Stories/'):
                continue
            try:
                xml_content = z.read(story_path).decode('utf-8')
                paragraphs = parse_story(xml_content)
                story_type = classify_story(paragraphs)
                stories.append((story_path, story_type, paragraphs))
            except (KeyError, ET.ParseError) as e:
                print(f"  Warning: Could not parse {story_path}: {e}")

    return stories


# --- Issue & Article Identification ---

def parse_volume_number(text: str) -> tuple[int, int]:
    """Parse 'Volume 1 — Number 12' into (1, 12)."""
    m = re.search(r'Volume\s+(\d+)\s*[—\-]\s*Number\s+(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def parse_date(text: str) -> tuple[int, int, int]:
    """Parse 'January, 1886' into (1886, 1, 0) or 'January 1, 1889' into (1889, 1, 1)."""
    text_lower = text.strip().lower()
    month_num = 0
    day = 0
    year = 0

    for month_name, mnum in MONTH_NAMES.items():
        if month_name in text_lower:
            month_num = mnum
            break

    year_match = re.search(r'(\d{4})', text_lower)
    if year_match:
        year = int(year_match.group(1))

    # Try to extract day: "January 1, 1889" or "October 16, 1889"
    day_match = re.search(r'(\w+)\s+(\d{1,2}),?\s+\d{4}', text.strip())
    if day_match:
        day = int(day_match.group(2))

    return year, month_num, day


def extract_issue_meta(paragraphs: list[Paragraph]) -> dict:
    """Extract issue metadata from a metadata story."""
    meta = {}
    for para in paragraphs:
        if para.style == 'Volume and Number' and not para.is_empty:
            vol, num = parse_volume_number(para.plain_text)
            if vol > 0:
                meta['volume'] = vol
                meta['number'] = num
        elif para.style == 'Date' and not para.is_empty:
            year, month, day = parse_date(para.plain_text)
            if year > 0:
                meta['year'] = year
                meta['month'] = month
                meta['day'] = day
                meta['date_str'] = para.plain_text.strip()
        elif para.style == 'Normal Center Small' and not para.is_empty:
            meta['location'] = para.plain_text.strip()
        elif para.style == 'Normal Center' and not para.is_empty:
            meta['motto'] = para.plain_text.strip()
    return meta


def identify_issues(stories: list[tuple[str, str, list[Paragraph]]]) -> list[Issue]:
    """Pair metadata and content stories into issues.

    Both meta and content stories appear in the same document order (reverse
    chronological in the IDML). Sorting each group by index and pairing 1:1
    gives the correct assignment regardless of distance between them.
    """
    # Collect meta stories with indices
    meta_list = []  # [(index, meta_dict)]
    for i, (path, stype, paras) in enumerate(stories):
        if stype == 'meta':
            meta = extract_issue_meta(paras)
            if 'volume' in meta and 'number' in meta:
                meta_list.append((i, meta))

    # Collect content stories with indices
    content_list = []  # [(index, paragraphs)]
    for i, (path, stype, paras) in enumerate(stories):
        if stype == 'content':
            content_list.append((i, paras))

    # Sort both by document order (index)
    meta_list.sort(key=lambda x: x[0])
    content_list.sort(key=lambda x: x[0])

    if len(meta_list) != len(content_list):
        print(f'  Warning: {len(meta_list)} meta stories vs {len(content_list)} content stories')

    # Pair 1:1 in document order
    issues = []
    for (mi, meta), (ci, paras) in zip(meta_list, content_list):
        issue = Issue(
            volume=meta['volume'],
            number=meta['number'],
            year=meta.get('year', 0),
            month=meta.get('month', 0),
            day=meta.get('day', 0),
            date_str=meta.get('date_str', ''),
            location=meta.get('location', ''),
            motto=meta.get('motto', ''),
        )
        issue.articles = split_into_articles(paras)
        issues.append(issue)

    issues.sort(key=lambda i: (i.volume, i.number))

    # Merge issues with the same volume+number (e.g., Part 1 / Part 2 splits)
    merged = []
    for issue in issues:
        if merged and merged[-1].volume == issue.volume and merged[-1].number == issue.number:
            merged[-1].articles.extend(issue.articles)
        else:
            merged.append(issue)

    # Fix year typos: if most issues share the same year, correct outliers
    if len(merged) > 2:
        from collections import Counter
        year_counts = Counter(iss.year for iss in merged if iss.year > 0)
        if year_counts:
            dominant_year = year_counts.most_common(1)[0][0]
            for iss in merged:
                if iss.year > 0 and iss.year != dominant_year:
                    print(f'  Warning: fixing year {iss.year} -> {dominant_year} '
                          f'for Volume {iss.volume}, Number {iss.number} '
                          f'(date_str: "{iss.date_str}")')
                    iss.date_str = iss.date_str.replace(str(iss.year), str(dominant_year))
                    iss.year = dominant_year

    return merged


def split_into_articles(paragraphs: list[Paragraph]) -> list[Article]:
    """Split paragraphs into articles at Heading boundaries."""
    articles = []
    current_article = None

    # Styles that indicate a new article
    heading_styles = {'Heading 1', 'Heading 2', 'Heading 2 Subtitle'}

    for para in paragraphs:
        if para.style in heading_styles and not para.is_empty:
            # Start a new article
            if current_article:
                finalize_article(current_article)
                articles.append(current_article)

            title = para.plain_text.strip()
            # Remove surrounding quotes if present
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1]
            elif title.startswith('\u201c') and title.endswith('\u201d'):
                title = title[1:-1]

            current_article = Article(title=title)

        elif current_article is not None:
            # Skip separators between articles
            if para.is_separator:
                continue
            # Skip empty paragraphs at the start of an article
            if not current_article.paragraphs and para.is_empty:
                continue
            current_article.paragraphs.append(para)

        # If no article started yet, these are pre-article content (quotes, mottos)
        # We skip those since they're part of the issue decoration

    # Finalize last article
    if current_article:
        finalize_article(current_article)
        articles.append(current_article)

    return articles


def finalize_article(article: Article):
    """Detect author, attribution type, and clean up trailing empty paragraphs."""
    # Remove trailing empty paragraphs
    while article.paragraphs and article.paragraphs[-1].is_empty:
        article.paragraphs.pop()

    # Remove trailing separators
    while article.paragraphs and article.paragraphs[-1].is_separator:
        article.paragraphs.pop()

    # Check last few paragraphs for author attribution
    for i in range(min(3, len(article.paragraphs)), 0, -1):
        para = article.paragraphs[-i]
        text = para.plain_text.strip()

        # Check if it's a known author initials pattern
        if para.style in ('Reference Right', 'Reference Left', 'Reference Center', 'Author'):
            article.author_short = text.rstrip('.')
            if text in KNOWN_AUTHORS:
                article.author, article.author_short = KNOWN_AUTHORS[text]
            article.paragraphs = article.paragraphs[:-i]
            break

        # Check for initials-like patterns at end (e.g., "A. T. J." or "E. J. W.")
        if len(text) < 30 and re.match(r'^[A-Z]\.\s*[A-Z]\.\s*[A-Z]\.?$', text):
            if text in KNOWN_AUTHORS:
                article.author, article.author_short = KNOWN_AUTHORS[text]
            else:
                initials = text.replace('.', '').replace(' ', '')
                article.author_short = initials
            article.paragraphs = article.paragraphs[:-i]
            break

        # Also check for author names as last line of Normal style
        if para.style == 'Normal' and len(text) < 50 and not text.endswith('.'):
            # Could be an author name - check if it looks like one
            if re.match(r'^[A-Z][a-z]+(\s+[A-Z]\.?\s*)+[A-Za-z]+$', text):
                article.author = text
                article.paragraphs = article.paragraphs[:-i]
                break

    # Detect attribution type
    _detect_attribution(article)


def _detect_attribution(article: Article):
    """Set attribution type based on author and body content."""
    # 1. Explicit — author detected
    if article.author or article.author_short:
        article.attribution = 'explicit'
        return

    # 2. Check for reprint pattern on last non-empty paragraph
    for para in reversed(article.paragraphs):
        text = para.plain_text.strip()
        if not text:
            continue
        m = REPRINT_RE.search(text)
        if m:
            # Edge case: if 3+ substantive paragraphs, it's editorial
            substantive = sum(
                1 for p in article.paragraphs
                if p.plain_text.strip()
                and not p.plain_text.strip().startswith('#')
                and p.style not in ('Quotation', 'Quotation Noindent',
                                    'Poem', 'Poem Noindent')
                and len(p.plain_text.strip()) > 40
            )
            if substantive >= 3:
                article.attribution = 'editorial'
            else:
                article.attribution = 'reprint'
                article.original_publication = m.group(1).strip()
        else:
            article.attribution = 'editorial'
        return

    # 3. Fallback
    article.attribution = 'editorial'


# --- Markdown Formatting ---

def format_text_run(run: TextRun) -> str:
    """Format a text run with markdown emphasis."""
    text = run.text
    if not text:
        return ''

    if run.small_caps:
        text = text.upper()

    if run.bold and run.italic:
        text = f'***{text}***'
    elif run.bold:
        text = f'**{text}**'
    elif run.italic:
        text = f'*{text}*'

    return text


def format_paragraph(para: Paragraph) -> str:
    """Format a paragraph as markdown."""
    text = ''.join(format_text_run(r) for r in para.runs).strip()

    if not text:
        return ''

    style = para.style

    if style in ('Heading 1',):
        return f'# {text}'
    elif style in ('Heading 2', 'Heading 2 Subtitle'):
        return f'# {text}'  # Article titles are H1 in individual files
    elif style in ('Heading 3',):
        return f'## {text}'
    elif style.startswith('Quotation'):
        # Split multi-line quotes
        lines = text.split('\n')
        return '\n'.join(f'> {line}' for line in lines)
    elif style in ('Poem', 'Poem Noindent'):
        return f'> {text}'
    elif style in ('Normal Center',):
        if re.match(r'^[_*\-=~]{3,}$', text):
            return '---'
        return text
    elif style in ('SEPARATOR',):
        return '---'
    else:
        return text


def article_to_markdown(article: Article, issue: Issue) -> str:
    """Convert an article to a complete markdown file with frontmatter."""
    lines = []

    # YAML frontmatter
    lines.append('---')
    lines.append(f'title: "{article.title}"')
    if article.author:
        lines.append(f'author: "{article.author}"')
    if article.author_short:
        lines.append(f'author_short: "{article.author_short}"')

    # Date
    if issue.year and issue.month and issue.day:
        lines.append(f'date: {issue.year}-{issue.month:02d}-{issue.day:02d}')
    elif issue.year and issue.month:
        lines.append(f'date: {issue.year}-{issue.month:02d}-01')
    elif issue.year:
        lines.append(f'date: {issue.year}-01-01')

    lines.append(f'publication: "American Sentinel"')
    lines.append(f'volume: {issue.volume}')
    lines.append(f'issue: {issue.number}')
    if article.attribution:
        lines.append(f'attribution: "{article.attribution}"')
    if article.original_publication:
        lines.append(f'original_publication: "{article.original_publication}"')
    lines.append('---')
    lines.append('')

    # Article title
    lines.append(f'# {article.title}')
    lines.append('')

    # Body
    prev_was_quote = False
    for para in article.paragraphs:
        formatted = format_paragraph(para)
        if not formatted:
            continue

        is_quote = formatted.startswith('>')
        # Add blank line between paragraphs, but not between consecutive blockquotes
        if prev_was_quote and is_quote:
            lines.append(formatted)
        else:
            lines.append(formatted)
            lines.append('')

        prev_was_quote = is_quote

    # Author attribution at end
    if article.author_short and not article.author:
        lines.append(f'{article.author_short}')
        lines.append('')
    elif article.author:
        lines.append(f'{article.author_short or article.author}')
        lines.append('')

    return '\n'.join(lines)


def slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    # Remove quotes and special chars
    text = re.sub(r'["\'\u201c\u201d\u2018\u2019]', '', text)
    # Replace spaces and special chars with hyphens
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text)
    # Clean up
    text = text.strip('-')
    # Truncate to reasonable length
    if len(text) > 60:
        text = text[:60].rstrip('-')
    return text


def write_issue_files(issue: Issue, output_dir: Path, dry_run: bool = False):
    """Write all article files for an issue."""
    # Build folder name
    if issue.month and issue.day:
        folder_name = f'{issue.year}-{issue.month:02d}-{issue.day:02d}_v{issue.volume:02d}n{issue.number:02d}'
    elif issue.month:
        folder_name = f'{issue.year}-{issue.month:02d}_v{issue.volume:02d}n{issue.number:02d}'
    else:
        folder_name = f'{issue.year}_v{issue.volume:02d}n{issue.number:02d}'

    issue_dir = output_dir / str(issue.year) / folder_name

    if dry_run:
        print(f'\n  Issue: Volume {issue.volume}, Number {issue.number} ({issue.date_str})')
        print(f'  Output: {issue_dir}')
        print(f'  Articles: {len(issue.articles)}')
        for i, article in enumerate(issue.articles, 1):
            author_str = f' [{article.author_short or article.author}]' if (article.author_short or article.author) else ''
            print(f'    {i:02d}. {article.title}{author_str}')
        return

    issue_dir.mkdir(parents=True, exist_ok=True)

    # Write masthead
    masthead_content = f'# The American Sentinel.\n\n'
    masthead_content += f'VOLUME {issue.volume}. | {issue.location}, {issue.date_str.upper()} | NUMBER {issue.number}.\n'
    (issue_dir / '00_masthead.md').write_text(masthead_content, encoding='utf-8')

    # Write articles
    for i, article in enumerate(issue.articles, 1):
        slug = slugify(article.title)
        author_suffix = f'_{article.author_short}' if article.author_short else ''
        filename = f'{i:02d}_{slug}{author_suffix}.md'

        content = article_to_markdown(article, issue)
        (issue_dir / filename).write_text(content, encoding='utf-8')

    print(f'  Volume {issue.volume}, Number {issue.number}: {len(issue.articles)} articles -> {issue_dir}')


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description='Extract articles from IDML files into markdown'
    )
    parser.add_argument(
        'idml_file',
        type=Path,
        help='Path to IDML file'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path.home() / 'Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/2. Transcribed',
        help='Output directory for transcribed files'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be extracted without writing files'
    )

    args = parser.parse_args()

    if not args.idml_file.exists():
        print(f'Error: File not found: {args.idml_file}')
        sys.exit(1)

    print(f'Extracting from: {args.idml_file.name}')
    print(f'Output to: {args.output_dir}')
    if args.dry_run:
        print('(DRY RUN - no files will be written)')

    # Extract all stories
    print('\nParsing IDML...')
    stories = extract_stories(args.idml_file)
    meta_count = sum(1 for _, t, _ in stories if t == 'meta')
    content_count = sum(1 for _, t, _ in stories if t == 'content')
    print(f'  Total stories: {len(stories)} ({meta_count} meta, {content_count} content)')

    # Identify issues
    print('\nIdentifying issues...')
    issues = identify_issues(stories)
    print(f'  Found {len(issues)} issues')

    # Write output
    print('\nExtracting articles:')
    total_articles = 0
    for issue in issues:
        write_issue_files(issue, args.output_dir, dry_run=args.dry_run)
        total_articles += len(issue.articles)

    print(f'\nDone! {total_articles} articles from {len(issues)} issues.')


if __name__ == '__main__':
    main()
