#!/usr/bin/env python3
"""
Extract issue text from IDML files.

IDML files are ZIP archives containing XML (Adobe InDesign Markup Language).
This script reads the text content from Stories/*.xml, identifies issue
boundaries from metadata stories, and outputs one markdown text file per
issue. Agents then process each issue file into individual articles.

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


@dataclass
class Issue:
    """An issue of the publication."""
    volume: int = 0
    number: int = 0
    date_str: str = ''
    year: int = 0
    month: int = 0
    day: int = 0
    location: str = ''
    motto: str = ''
    paragraphs: list[Paragraph] = field(default_factory=list)


MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


# --- IDML Parsing ---

def get_spread_order(idml_zip: zipfile.ZipFile) -> list[str]:
    """Get spread file paths in document order from designmap.xml."""
    dm_content = idml_zip.read('designmap.xml').decode('utf-8')
    root = ET.fromstring(dm_content)

    ns = 'http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging'
    spread_paths = []
    for elem in root:
        if elem.tag == f'{{{ns}}}Spread':
            src = elem.get('src')
            if src:
                spread_paths.append(src)

    return spread_paths


def get_story_order_from_spreads(idml_zip: zipfile.ZipFile) -> list[str]:
    """Get story IDs in physical page order by walking Spreads.

    Spreads represent physical pages in document order. Each Spread
    contains TextFrames that reference Stories via ParentStory.
    Walking Spreads in designmap order gives the correct physical
    sequence of all content.
    """
    spread_paths = get_spread_order(idml_zip)
    seen = set()
    ordered_story_ids = []

    for spread_path in spread_paths:
        try:
            spread_xml = idml_zip.read(spread_path).decode('utf-8')
        except KeyError:
            continue
        sroot = ET.fromstring(spread_xml)
        for elem in sroot.iter():
            if 'TextFrame' in elem.tag:
                story_id = elem.get('ParentStory')
                if story_id and story_id not in seen:
                    seen.add(story_id)
                    ordered_story_ids.append(story_id)

    # Convert story IDs to file paths
    return [f'Stories/Story_{sid}.xml' for sid in ordered_story_ids]


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
                        text = child.text
                        text = text.replace('\ufeff', '')  # BOM
                        text = text.replace('\u2028', '\n')  # line separator
                        text = text.replace('\u2029', '\n')  # paragraph separator
                        text = text.replace('\u00ad', '')  # soft hyphen
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
                        if current_runs:
                            paragraphs.append(Paragraph(style=style, runs=list(current_runs)))
                            current_runs = []
                        else:
                            paragraphs.append(Paragraph(style=style, runs=[]))

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
    if styles & heading_styles:
        return 'content'
    if non_empty_count > 20:
        return 'content'
    return 'other'


def extract_stories(idml_path: Path) -> list[tuple[str, str, list[Paragraph]]]:
    """Extract all stories from IDML in physical page order.

    Uses Spread sequence from designmap.xml to determine the correct
    order of stories. This is the ONLY reliable way to map content
    to issues — never use story index or arbitrary pairing.
    """
    stories = []

    with zipfile.ZipFile(idml_path, 'r') as z:
        story_paths = get_story_order_from_spreads(z)

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


# --- Issue Identification ---

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
    """Assign content stories to issues using Spread-based sequential walk.

    Stories are already in physical page order (from Spread sequence).
    Walk through them sequentially: when a meta story appears, it starts
    a new issue. All subsequent content stories belong to that issue
    until the next meta story.

    This is the ONLY correct approach — never pair or sort independently.
    """
    current_issue = None
    issues = []

    for path, stype, paras in stories:
        if stype == 'meta':
            meta = extract_issue_meta(paras)
            if 'volume' in meta and 'number' in meta:
                current_issue = Issue(
                    volume=meta['volume'],
                    number=meta['number'],
                    year=meta.get('year', 0),
                    month=meta.get('month', 0),
                    day=meta.get('day', 0),
                    date_str=meta.get('date_str', ''),
                    location=meta.get('location', ''),
                    motto=meta.get('motto', ''),
                )
                issues.append(current_issue)
        elif stype == 'content' and current_issue is not None:
            has_text = any(not p.is_empty for p in paras)
            if has_text:
                current_issue.paragraphs.extend(paras)

    # Merge issues with the same volume+number (consecutive duplicates)
    merged = []
    for issue in issues:
        if merged and merged[-1].volume == issue.volume and merged[-1].number == issue.number:
            merged[-1].paragraphs.extend(issue.paragraphs)
        else:
            merged.append(issue)

    # Fix year typos (e.g., one issue has wrong year in metadata)
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

    if style in ('Heading 1', 'Heading 2', 'Heading 2 Subtitle'):
        return f'# {text}'
    elif style in ('Heading 3',):
        return f'## {text}'
    elif style.startswith('Quotation'):
        lines = text.split('\n')
        return '\n'.join(f'> {line}' for line in lines)
    elif style in ('Poem', 'Poem Noindent'):
        return f'> {text}'
    elif style in ('Normal Center',):
        if re.match(r'^[_*\-=~]{3,}$', text):
            return '---'
        return text
    elif style in ('SEPARATOR', 'Thoughtbreak'):
        if re.match(r'^[_*\-=~]{3,}$', text):
            return '---'
        return text
    elif style in ('Reference Right', 'Reference Left', 'Reference Center', 'Author'):
        return text
    else:
        return text


def issue_to_markdown(issue: Issue) -> str:
    """Convert an issue's full text to a single markdown file."""
    lines = []

    prev_was_quote = False
    for para in issue.paragraphs:
        formatted = format_paragraph(para)
        if not formatted:
            continue

        is_quote = formatted.startswith('>')
        if prev_was_quote and is_quote:
            lines.append(formatted)
        else:
            lines.append(formatted)
            lines.append('')

        prev_was_quote = is_quote

    return '\n'.join(lines)


def format_date(issue: Issue) -> str:
    """Format issue date as YYYY-MM-DD."""
    if issue.year and issue.month and issue.day:
        return f'{issue.year}-{issue.month:02d}-{issue.day:02d}'
    elif issue.year and issue.month:
        return f'{issue.year}-{issue.month:02d}'
    elif issue.year:
        return f'{issue.year}'
    return 'unknown'


def write_issue_dump(issue: Issue, output_dir: Path, dry_run: bool = False):
    """Write a single text file for an issue."""
    date = format_date(issue)
    filename = f'v{issue.volume:02d}n{issue.number:02d}_{date}.md'
    output_path = output_dir / filename

    # Count non-empty paragraphs and headings for summary
    non_empty = sum(1 for p in issue.paragraphs if not p.is_empty)
    headings = [p.plain_text.strip() for p in issue.paragraphs
                if p.style in ('Heading 1', 'Heading 2', 'Heading 2 Subtitle') and not p.is_empty]

    if dry_run:
        print(f'  v{issue.volume:02d}n{issue.number:02d} ({issue.date_str}): '
              f'{non_empty} paragraphs, {len(headings)} headings → {filename}')
        for h in headings:
            print(f'    - {h}')
        return

    # Build header with issue metadata
    header = []
    header.append(f'ISSUE: Volume {issue.volume}, Number {issue.number}')
    header.append(f'DATE: {date}')
    header.append(f'DATE_STR: {issue.date_str}')
    if issue.location:
        header.append(f'LOCATION: {issue.location}')
    if issue.motto:
        header.append(f'MOTTO: {issue.motto}')
    header.append('')
    header.append('---')
    header.append('')

    body = issue_to_markdown(issue)
    content = '\n'.join(header) + body

    output_path.write_text(content, encoding='utf-8')
    print(f'  v{issue.volume:02d}n{issue.number:02d}: {non_empty} paragraphs, '
          f'{len(headings)} headings → {filename}')


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description='Extract issue text from IDML files'
    )
    parser.add_argument(
        'idml_file',
        type=Path,
        help='Path to IDML file'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Output directory for issue text files (default: /tmp/idml_issues/<year>)'
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

    if not issues:
        print('No issues found.')
        sys.exit(1)

    # Determine output directory
    year = issues[0].year
    output_dir = args.output_dir or Path(f'/tmp/idml_issues/{year}')

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    print(f'\nOutput: {output_dir}')
    print(f'Writing issue dumps:')

    for issue in issues:
        write_issue_dump(issue, output_dir, dry_run=args.dry_run)

    print(f'\nDone! {len(issues)} issue files.')


if __name__ == '__main__':
    main()
