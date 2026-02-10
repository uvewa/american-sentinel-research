#!/usr/bin/env python3
"""
Add attribution field to existing article frontmatter.

Scans all transcribed article .md files, detects attribution type
(explicit, reprint, editorial), and surgically inserts `attribution:`
(and `original_publication:` for reprints) into existing YAML frontmatter
without reformatting.

Classification order (first match wins):
  1. explicit  — author or author_short already present in frontmatter
  2. reprint   — last non-blank line of body matches —*Source Name* pattern
  3. editorial — everything else (unsigned content by editorial staff)

Edge case: If the article has 3+ substantive non-blockquote paragraphs AND
ends with a source-attributed quote, classify as editorial (it's editorial
content that ends with a supporting quote, not a reprint).

Usage:
    python add_attribution.py [--dry-run] [--year YYYY]
"""

import argparse
import re
import sys
from pathlib import Path


# --- Configuration ---

TRANSCRIBED_ROOT = (
    Path.home()
    / 'Documents/PUBLICAR/APL/English'
    / 'American Sentinel (Religious Freedom)'
    / '0. American Sentinel'
    / '2. Transcribed'
)

# Reprint source pattern: —*Source Name*.  (optionally followed by footnote ref)
REPRINT_RE = re.compile(r'—\*([^*]+)\*\.?\s*(\[\d+\])?\s*$')

# Editor lookup (not used in frontmatter yet — stored for future display/query)
EDITORS = {
    1886: {'editor': 'E. J. Waggoner', 'short': 'EJW', 'confidence': 'uncertain'},
    1891: {'editor': 'Alonzo T. Jones', 'short': 'ATJ', 'confidence': 'confirmed'},
}

# Files to skip
SKIP_FILENAMES = {'uncertainties.md'}
SKIP_PREFIXES = ('00_masthead',)


def parse_frontmatter_and_body(text: str) -> tuple[str, str] | None:
    """Split a file into frontmatter block and body.

    Returns (frontmatter_block, body) where frontmatter_block includes
    the --- delimiters, or None if no valid frontmatter found.
    """
    match = re.match(r'^(---\s*\n.*?\n---)\s*\n', text, re.DOTALL)
    if not match:
        return None
    fm_block = match.group(1)
    body = text[match.end():]
    return fm_block, body


def has_field(fm_block: str, field_name: str) -> bool:
    """Check if a YAML field exists in the frontmatter block."""
    return bool(re.search(rf'^{field_name}:', fm_block, re.MULTILINE))


def has_author(fm_block: str) -> bool:
    """Check if author or author_short is present in frontmatter."""
    return has_field(fm_block, 'author') or has_field(fm_block, 'author_short')


def get_last_nonblank_line(body: str) -> str:
    """Get the last non-blank line from the article body."""
    lines = body.rstrip().split('\n')
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return ''


def count_substantive_paragraphs(body: str) -> int:
    """Count non-blockquote, non-heading paragraphs with real content.

    A 'paragraph' here is a block of text separated by blank lines.
    We skip blockquotes (lines starting with >) and headings (# ...).
    """
    count = 0
    paragraphs = re.split(r'\n\s*\n', body.strip())
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Skip blockquotes
        if para.startswith('>'):
            continue
        # Skip headings
        if para.startswith('#'):
            continue
        # Skip horizontal rules
        if re.match(r'^-{3,}$', para):
            continue
        # Must have some substance (more than just a short attribution line)
        if len(para) > 40:
            count += 1
    return count


def detect_reprint_source(body: str) -> str | None:
    """Detect if the article body ends with a reprint source attribution.

    Returns the source name if found, None otherwise.
    """
    last_line = get_last_nonblank_line(body)
    # Strip leading > for blockquote lines
    check_line = last_line.lstrip('> ')
    m = REPRINT_RE.search(check_line)
    if m:
        return m.group(1).strip()
    return None


def classify_article(fm_block: str, body: str) -> tuple[str, str | None]:
    """Classify an article's attribution type.

    Returns (attribution_type, original_publication_or_None).
    """
    # 1. Explicit — author already present
    if has_author(fm_block):
        return 'explicit', None

    # 2. Check for reprint pattern
    source = detect_reprint_source(body)
    if source:
        # Edge case: if 3+ substantive non-blockquote paragraphs exist,
        # this is editorial content that happens to end with a source quote
        substantive_count = count_substantive_paragraphs(body)
        if substantive_count >= 3:
            return 'editorial', None
        return 'reprint', source

    # 3. Everything else is editorial
    return 'editorial', None


def insert_attribution(fm_block: str, attribution: str,
                       original_pub: str | None) -> str:
    """Insert attribution field(s) into frontmatter after the issue: line.

    Does NOT use yaml.dump — surgically inserts text lines to preserve
    existing formatting exactly.
    """
    lines = fm_block.split('\n')
    insert_after = None

    # Find the issue: line to insert after
    for i, line in enumerate(lines):
        if line.startswith('issue:'):
            insert_after = i
            break

    # Fallback: insert before the closing ---
    if insert_after is None:
        for i, line in enumerate(lines):
            if line.strip() == '---' and i > 0:
                insert_after = i - 1
                break

    if insert_after is None:
        return fm_block  # shouldn't happen

    new_lines = [f'attribution: "{attribution}"']
    if original_pub:
        new_lines.append(f'original_publication: "{original_pub}"')

    result = lines[:insert_after + 1] + new_lines + lines[insert_after + 1:]
    return '\n'.join(result)


def process_file(file_path: Path, dry_run: bool = False) -> dict | None:
    """Process a single article file.

    Returns a dict with classification info, or None if skipped.
    """
    text = file_path.read_text(encoding='utf-8')

    parsed = parse_frontmatter_and_body(text)
    if parsed is None:
        return None

    fm_block, body = parsed

    # Skip if attribution already present (idempotent)
    if has_field(fm_block, 'attribution'):
        return None

    attribution, original_pub = classify_article(fm_block, body)

    result = {
        'file': file_path,
        'attribution': attribution,
        'original_publication': original_pub,
    }

    if not dry_run:
        new_fm = insert_attribution(fm_block, attribution, original_pub)
        new_text = text.replace(fm_block, new_fm, 1)
        file_path.write_text(new_text, encoding='utf-8')

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Add attribution field to article frontmatter'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--year',
        type=int,
        help='Only process files for a specific year'
    )
    parser.add_argument(
        '--content-dir',
        type=Path,
        default=TRANSCRIBED_ROOT,
        help='Root directory of transcribed files'
    )

    args = parser.parse_args()

    if not args.content_dir.exists():
        print(f'Error: Directory not found: {args.content_dir}')
        sys.exit(1)

    if args.dry_run:
        print('DRY RUN — no files will be modified\n')

    # Find all article .md files
    if args.year:
        search_dir = args.content_dir / str(args.year)
        if not search_dir.exists():
            print(f'Error: Year directory not found: {search_dir}')
            sys.exit(1)
    else:
        search_dir = args.content_dir

    md_files = sorted(search_dir.rglob('*.md'))

    counts = {'explicit': 0, 'reprint': 0, 'editorial': 0, 'skipped': 0}

    for file_path in md_files:
        # Skip non-article files
        if file_path.name in SKIP_FILENAMES:
            continue
        if any(file_path.name.startswith(p) for p in SKIP_PREFIXES):
            continue
        if file_path.name.endswith('_Publication-Info.md'):
            continue

        result = process_file(file_path, dry_run=args.dry_run)

        if result is None:
            counts['skipped'] += 1
            continue

        attr = result['attribution']
        counts[attr] += 1

        rel_path = file_path.relative_to(args.content_dir)
        if attr == 'reprint':
            print(f'  {attr:10s}  {rel_path}  <- {result["original_publication"]}')
        else:
            print(f'  {attr:10s}  {rel_path}')

    print(f'\n--- Summary ---')
    print(f'  Explicit:  {counts["explicit"]}')
    print(f'  Reprint:   {counts["reprint"]}')
    print(f'  Editorial: {counts["editorial"]}')
    print(f'  Skipped:   {counts["skipped"]} (already has attribution or no frontmatter)')
    total = counts['explicit'] + counts['reprint'] + counts['editorial']
    print(f'  Total:     {total} articles updated')


if __name__ == '__main__':
    main()
