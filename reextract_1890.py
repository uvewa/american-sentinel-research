#!/usr/bin/env python3
"""
Re-extract 1890 articles from spread-based IDML dumps.

Reads /tmp/idml_1890_spread_based/issue_NN.txt files (which contain
correctly sequenced text based on IDML spread/page geography) and writes
properly formatted article .md files to the transcribed directory.

For stories that span two issues, page markers [NN] in the text are used
to determine which articles belong to which issue.
"""

import os
import re
import shutil
import sys

DUMP_DIR = '/tmp/idml_1890_spread_based'
OUTPUT_BASE = '/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/2. Transcribed/1890'

# Known author signatures found at end of articles
KNOWN_AUTHORS = {
    'A. T. J.': ('Alonzo T. Jones', 'ATJ'),
    'A. T. J': ('Alonzo T. Jones', 'ATJ'),
    'E. J. W.': ('Ellet J. Waggoner', 'EJW'),
    'C. P. B.': ('C. P. Bollman', 'CPB'),
    'W. H. M.': ('W. H. McKee', 'WHM'),
    'W. A. B.': ('W. A. Blakely', 'WAB'),
    'W. N. G.': ('W. N. Glenn', 'WNG'),
    'L. A. SMITH.': ('L. A. Smith', 'LAS'),
    'L. A. Smith.': ('L. A. Smith', 'LAS'),
    'L. A. S.': ('L. A. Smith', 'LAS'),
    'E. HILLIARD.': ('E. Hilliard', 'EH'),
    'C. H. B.': ('C. H. B.', 'CHB'),
    'W. A. C.': ('W. A. Colcord', 'WAC'),
    'A. F. B.': ('A. F. Ballenger', 'AFB'),
}


def parse_page_markers(text):
    """Extract page numbers from [NN] or [NN-MM] markers in text."""
    markers = []
    for m in re.finditer(r'\[(\d+)(?:-(\d+))?\]', text):
        page = int(m.group(1))
        markers.append(page)
        if m.group(2):
            markers.append(int(m.group(2)))
    return sorted(set(markers))


def clean_page_markers(text):
    """Remove IDML page markers like [34], [47-48] from article text.

    These markers appear at page break points in the IDML but are not
    part of the original published text. Only removes markers where the
    number is in a plausible page range (1-500) and the marker appears
    as standalone text (preceded by space/newline and followed by
    space/newline/punctuation).
    """
    # Match [N] or [N-M] where N,M are 1-500, at word boundaries
    cleaned = re.sub(r'\s*\[(\d{1,3})(?:-\d{1,3})?\]', _page_marker_replace, text)
    return cleaned


def _page_marker_replace(match):
    """Replace page marker only if the number is in page range 1-500."""
    num = int(match.group(1))
    if 1 <= num <= 500:
        return ''  # Remove the marker
    return match.group(0)  # Keep non-page-number brackets


def slugify(title):
    """Convert title to filename slug."""
    slug = title
    slug = re.sub(r'["\'.!?,;:\(\)\[\]]', '', slug)
    slug = slug.replace('—', '-').replace('–', '-').replace('"', '').replace('"', '')
    slug = slug.strip()
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def detect_author_from_text(text):
    """Detect author signature at end of article text.

    Checks the last several lines for author signatures, since the
    signature may be followed by a dateline, location, or other
    trailing content (e.g., "> *Washington, D. C., Jan.* 29.").

    Returns (full_name, initials, attribution, original_pub).
    """
    text_stripped = text.rstrip()
    if not text_stripped:
        return None, None, 'editorial', None

    # Check for reprint: ends with —*Source Name* or — *Source Name*
    # Check last few lines since source attribution may not be the very last line
    last_lines = text_stripped.split('\n')
    for line in last_lines[-5:]:
        reprint_match = re.search(r'[—–]\s*\*([^*]+)\*\.?\s*$', line.strip())
        if reprint_match:
            return None, None, 'reprint', reprint_match.group(1).strip()

    # Check for author initials in the last several lines
    # Signatures may be followed by datelines, locations, etc.
    for line in reversed(last_lines[-6:]):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        for sig, (full_name, initials) in KNOWN_AUTHORS.items():
            if line_stripped.endswith(sig):
                return full_name, initials, 'explicit', None
            # Check with period-glued pattern
            if line_stripped.endswith('.' + sig) or line_stripped.endswith('.' + sig.rstrip('.')):
                return full_name, initials, 'explicit', None

    return None, None, 'editorial', None


def parse_dump(filepath):
    """Parse a spread-based issue dump file.

    Returns (issue_info, articles) where articles is a list of dicts.
    """
    with open(filepath, 'r') as f:
        content = f.read()

    lines = content.split('\n')

    # Parse header
    info = {}
    for line in lines[:10]:
        if line.startswith('ISSUE:'):
            m = re.search(r'Volume (\d+), Number (\d+)', line)
            if m:
                info['volume'] = int(m.group(1))
                info['number'] = int(m.group(2))
        elif line.startswith('DATE:'):
            info['date'] = line.split(':', 1)[1].strip()
        elif line.startswith('DATE_STR:'):
            info['date_str'] = line.split(':', 1)[1].strip()
        elif line.startswith('PAGES:'):
            pages_str = line.split(':', 1)[1].strip()
            m = re.match(r'(\d+)-(\d+)', pages_str)
            if m:
                info['page_start'] = int(m.group(1))
                info['page_end'] = int(m.group(2))

    # Parse story blocks and articles
    # First, identify story block boundaries
    story_blocks = []
    current_block_type = None
    current_block_lines = []

    for line in lines:
        # Detect story block start
        if line.startswith('=== STORY (entirely'):
            if current_block_type is not None:
                story_blocks.append((current_block_type, '\n'.join(current_block_lines)))
            current_block_type = 'entire'
            current_block_lines = []
            continue
        elif line.startswith('=== NEW STORY'):
            if current_block_type is not None:
                story_blocks.append((current_block_type, '\n'.join(current_block_lines)))
            current_block_type = 'new'
            current_block_lines = []
            continue
        elif line.startswith('=== CONTINUING STORY'):
            if current_block_type is not None:
                story_blocks.append((current_block_type, '\n'.join(current_block_lines)))
            current_block_type = 'continuing'
            current_block_lines = []
            continue
        elif line.startswith('=== '):
            # Skip annotation lines (This story has, The EARLIER/LATER)
            continue

        if current_block_type is not None:
            current_block_lines.append(line)

    # Don't forget the last block
    if current_block_type is not None:
        story_blocks.append((current_block_type, '\n'.join(current_block_lines)))

    # Parse articles from each story block
    page_start = info.get('page_start', 0)
    page_end = info.get('page_end', 999)

    all_articles = []

    for block_type, block_text in story_blocks:
        articles_in_block = parse_articles_from_block(block_text)

        if block_type == 'entire':
            all_articles.extend(articles_in_block)
        elif block_type == 'new':
            # Include EARLIER articles (up to page boundary)
            filtered = filter_new_story(articles_in_block, page_end)
            all_articles.extend(filtered)
        elif block_type == 'continuing':
            # Include LATER articles (from page boundary)
            filtered = filter_continuing_story(articles_in_block, page_start)
            all_articles.extend(filtered)

    return info, all_articles


def parse_articles_from_block(block_text):
    """Parse individual articles from a story block's text."""
    articles = []

    # Split by article headers
    parts = re.split(r'(--- Article \d+ of \d+: ".*?"\.?\s*---)', block_text)

    current_title = None
    current_num = None
    current_total = None
    current_explicit_author = None

    for part in parts:
        header_match = re.match(r'--- Article (\d+) of (\d+): "(.*?)"\.?\s*---', part)
        if header_match:
            current_num = int(header_match.group(1))
            current_total = int(header_match.group(2))
            current_title = header_match.group(3)
            current_explicit_author = None
            continue

        if current_title is None:
            continue

        # Parse the article text — skip leading blank lines, then
        # consume Attribution:/Author: metadata before the body
        text_lines = part.split('\n')
        body_lines = []
        attribution_from_dump = None
        in_metadata = True  # True until first non-metadata, non-blank line

        for line in text_lines:
            if in_metadata:
                if line.strip() == '':
                    continue  # Skip leading blank lines
                if line.startswith('Attribution:'):
                    attribution_from_dump = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('Author:'):
                    current_explicit_author = line.split(':', 1)[1].strip()
                    continue
                in_metadata = False  # First real content line
            body_lines.append(line)

        body = '\n'.join(body_lines).strip()

        if body or current_title:  # Include even if body is empty (shouldn't happen)
            articles.append({
                'title': current_title,
                'text': body,
                'article_num': current_num,
                'total_in_story': current_total,
                'explicit_author': current_explicit_author,
            })

        current_title = None

    return articles


def filter_new_story(articles, page_end):
    """For a NEW STORY that continues into the next issue,
    include articles whose content falls within this issue's pages.

    Strategy: walk articles in order. Track the highest page marker seen.
    Once we encounter an article whose FIRST page marker exceeds page_end,
    stop — that article and everything after belongs to the next issue.
    """
    result = []
    highest_page_seen = 0

    for art in articles:
        markers = parse_page_markers(art['text'])

        if markers:
            first_marker = min(markers)
            if first_marker > page_end:
                # This article starts beyond our page range
                break
            highest_page_seen = max(markers)
            result.append(art)
        else:
            # No markers — include if we haven't gone past our range yet
            if highest_page_seen <= page_end:
                result.append(art)
            else:
                break

    return result


def filter_continuing_story(articles, page_start):
    """For a CONTINUING STORY from a previous issue,
    include articles whose content falls within this issue's pages.

    Strategy: skip articles until we find one whose FIRST page marker
    (min) is >= page_start — meaning it starts in this issue.
    Then include everything from that point on.

    Using min(markers) ensures that articles which start in the previous
    issue but extend into this one are assigned to the previous issue
    (where they start), avoiding duplicates.
    """
    result = []
    started = False

    for art in articles:
        if started:
            result.append(art)
            continue

        markers = parse_page_markers(art['text'])
        if markers and min(markers) >= page_start:
            started = True
            result.append(art)

    return result


def build_frontmatter(title, date, volume, issue, author_name, author_short, attribution, original_pub=None):
    """Build YAML frontmatter string."""
    lines = ['---']
    lines.append(f'title: "{title}"')

    if author_name and attribution == 'explicit':
        lines.append(f'author: "{author_name}"')
        lines.append(f'author_short: "{author_short}"')

    lines.append(f'date: {date}')
    lines.append(f'publication: "American Sentinel"')
    lines.append(f'volume: {volume}')
    lines.append(f'issue: {issue}')
    lines.append(f'attribution: "{attribution}"')

    if original_pub:
        lines.append(f'original_publication: "{original_pub}"')

    lines.append('---')
    return '\n'.join(lines)


def build_masthead(info):
    """Build masthead markdown content."""
    vol = info['volume']
    num = info['number']
    date_str = info.get('date_str', info['date'])

    # The American Sentinel moved from Oakland to New York in early 1890
    # Issues 1-4 from Oakland, issues 5+ from New York
    if num <= 4:
        location = 'OAKLAND, CALIFORNIA'
        lines = [
            '# The American Sentinel.',
            '',
            f'VOLUME {vol}. | {location}, {date_str.upper()} | NUMBER {num}.',
            '',
        ]
    else:
        location = 'NEW YORK'
        lines = [
            '# The American Sentinel.',
            '',
            f'VOLUME {vol}. | {location}, {date_str.upper()} | NUMBER {num}.',
            '',
            'PACIFIC PRESS PUBLISHING COMPANY,',
            'No. 43 Bond St., New York.',
            '',
            'Editors: E. J. WAGGONER, ALONZO T. JONES.',
            '',
            '> Equal and exact justice to all men, of whatever state or persuasion, religious or political.—*Thomas Jefferson.*',
            '',
        ]

    return '\n'.join(lines)


def process_issue(issue_num, dry_run=False):
    """Process one issue dump and write article files.

    Returns (issue_num, article_count, issue_dir_name).
    """
    dump_path = os.path.join(DUMP_DIR, f'issue_{issue_num:02d}.txt')
    if not os.path.exists(dump_path):
        return issue_num, 0, None

    info, articles = parse_dump(dump_path)

    if not info.get('date'):
        print(f"  WARNING: issue {issue_num} has no date in dump")
        return issue_num, 0, None

    vol = info['volume']
    num = info['number']
    date = info['date']

    # Build directory name
    dir_name = f'{date}_v{vol:02d}n{num:02d}'
    dir_path = os.path.join(OUTPUT_BASE, dir_name)

    if dry_run:
        print(f"  Issue {issue_num}: v{vol:02d}n{num:02d} ({date}) — {len(articles)} articles → {dir_name}/")
        for i, art in enumerate(articles, 1):
            author_name, author_short, attribution, orig_pub = detect_author_from_text(art['text'])
            if art.get('explicit_author'):
                author_name = art['explicit_author']
                # Try to find initials
                for sig, (fn, ini) in KNOWN_AUTHORS.items():
                    if fn == author_name or fn.lower() == author_name.lower():
                        author_short = ini
                        break
                attribution = 'explicit'
            suffix = f'_{author_short}' if author_short else ''
            fname = f'{i:02d}_{slugify(art["title"])}{suffix}.md'
            print(f"    {fname}")
        return issue_num, len(articles), dir_name

    # Create directory (clear if exists)
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)
    os.makedirs(dir_path, exist_ok=True)

    # Write masthead
    masthead_path = os.path.join(dir_path, '00_masthead.md')
    with open(masthead_path, 'w') as f:
        f.write(build_masthead(info))

    # Write articles
    for i, art in enumerate(articles, 1):
        # Detect author
        author_name, author_short, attribution, orig_pub = detect_author_from_text(art['text'])

        # Override with explicit author from dump if present
        if art.get('explicit_author'):
            author_name = art['explicit_author']
            for sig, (fn, ini) in KNOWN_AUTHORS.items():
                if fn == author_name or fn.lower() == author_name.lower():
                    author_short = ini
                    break
            else:
                # Unknown author — use initials from name
                parts = author_name.split()
                author_short = ''.join(p[0] for p in parts if p[0].isupper())
            attribution = 'explicit'

        # Build filename
        suffix = f'_{author_short}' if author_short else ''
        fname = f'{i:02d}_{slugify(art["title"])}{suffix}.md'

        # Build frontmatter
        fm = build_frontmatter(
            title=art['title'],
            date=date,
            volume=vol,
            issue=num,
            author_name=author_name,
            author_short=author_short,
            attribution=attribution,
            original_pub=orig_pub,
        )

        # Build article content (strip IDML page markers from text)
        clean_text = clean_page_markers(art['text'])
        content = f'{fm}\n\n# {art["title"]}\n\n{clean_text}\n'

        article_path = os.path.join(dir_path, fname)
        with open(article_path, 'w') as f:
            f.write(content)

    # Write uncertainties file
    unc_path = os.path.join(dir_path, 'uncertainties.md')
    with open(unc_path, 'w') as f:
        f.write(f'# Uncertainties — Volume {vol}, Number {num} ({date})\n\n')
        f.write('Re-extracted from IDML spread-based dumps. Text is from IDML (not OCR).\n')
        f.write('No uncertainties expected for IDML-sourced text.\n')

    return issue_num, len(articles), dir_name


def main():
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("=== DRY RUN — no files will be written ===\n")
    else:
        print("=== Re-extracting 1890 articles from spread-based IDML dumps ===\n")

    total_articles = 0
    results = []

    for issue_num in range(1, 51):
        num, count, dir_name = process_issue(issue_num, dry_run=dry_run)
        total_articles += count
        results.append((num, count, dir_name))

    print(f"\n{'='*60}")
    print(f"Total: {total_articles} articles across {len([r for r in results if r[1] > 0])} issues")

    if not dry_run:
        print(f"\nFiles written to: {OUTPUT_BASE}")


if __name__ == '__main__':
    main()
