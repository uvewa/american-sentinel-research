#!/usr/bin/env python3
"""
Verify accuracy of article splitting: compare split article text against OCR source.
Strips YAML frontmatter from articles and compares body text against OCR source.
Reports any words/sentences that were changed, added, or removed by splitting agents.
"""

import os
import re
import sys
import difflib
import random

BASE = "/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/2. Transcribed"


def strip_frontmatter(text):
    """Remove YAML frontmatter (--- block at top) from article text."""
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            return text[end + 3:].strip()
    return text.strip()


def strip_ocr_header(text):
    """Remove the masthead header from OCR dump (everything before first ---)."""
    # The OCR dump starts with ISSUE:, DATE:, etc. then first ---
    # Find first --- that's on its own line
    lines = text.split('\n')
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == '---':
            start = i + 1
            break
    # Now join all remaining content, removing --- dividers
    content_lines = []
    for line in lines[start:]:
        if line.strip() == '---':
            continue  # skip dividers
        content_lines.append(line)
    return '\n'.join(content_lines).strip()


def normalize_whitespace(text):
    """Normalize whitespace for comparison: collapse multiple spaces/newlines."""
    # Remove leading/trailing whitespace per line, collapse blank lines
    lines = [l.strip() for l in text.split('\n')]
    # Remove empty lines at start/end
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def get_article_text(issue_dir):
    """Read all article files in an issue dir, strip frontmatter, return concatenated text."""
    files = sorted(os.listdir(issue_dir))
    parts = []
    for f in files:
        if f == '00_masthead.md' or f == 'uncertainties.md':
            continue
        if not f.endswith('.md'):
            continue
        path = os.path.join(issue_dir, f)
        with open(path, 'r') as fh:
            content = fh.read()
        body = strip_frontmatter(content)
        if body:
            parts.append(body)
    return '\n\n'.join(parts)


def get_ocr_text(ocr_path):
    """Read OCR source, strip header and dividers, return body text."""
    with open(ocr_path, 'r') as fh:
        content = fh.read()
    return strip_ocr_header(content)


def word_tokenize(text):
    """Split text into words for comparison."""
    return text.split()


def compare_issue(year, issue_dir_name, ocr_filename):
    """Compare one issue's split articles against its OCR source."""
    issue_dir = os.path.join(BASE, str(year), issue_dir_name)
    ocr_path = os.path.join(BASE, str(year), 'ocr', ocr_filename)

    if not os.path.isdir(issue_dir):
        return None, f"Issue dir not found: {issue_dir}"
    if not os.path.isfile(ocr_path):
        return None, f"OCR file not found: {ocr_path}"

    article_text = get_article_text(issue_dir)
    ocr_text = get_ocr_text(ocr_path)

    # Normalize
    article_norm = normalize_whitespace(article_text)
    ocr_norm = normalize_whitespace(ocr_text)

    # Word-level comparison
    article_words = word_tokenize(article_norm)
    ocr_words = word_tokenize(ocr_norm)

    # Use SequenceMatcher for similarity ratio
    sm = difflib.SequenceMatcher(None, ocr_words, article_words)
    ratio = sm.ratio()

    # Get opcodes for detailed diff
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        ocr_snippet = ' '.join(ocr_words[i1:i2])
        art_snippet = ' '.join(article_words[j1:j2])
        # Truncate long snippets
        if len(ocr_snippet) > 120:
            ocr_snippet = ocr_snippet[:120] + '...'
        if len(art_snippet) > 120:
            art_snippet = art_snippet[:120] + '...'
        changes.append({
            'type': tag,
            'ocr': ocr_snippet,
            'article': art_snippet,
            'ocr_pos': f'words {i1}-{i2}',
            'art_pos': f'words {j1}-{j2}',
        })

    return {
        'year': year,
        'issue': issue_dir_name,
        'ocr_file': ocr_filename,
        'ocr_words': len(ocr_words),
        'article_words': len(article_words),
        'similarity': ratio,
        'num_changes': len(changes),
        'changes': changes,
    }, None


def find_issues(year):
    """Find all issue directories and their corresponding OCR files for a year."""
    year_dir = os.path.join(BASE, str(year))
    ocr_dir = os.path.join(year_dir, 'ocr')
    if not os.path.isdir(ocr_dir):
        return []

    issues = []
    for d in sorted(os.listdir(year_dir)):
        full = os.path.join(year_dir, d)
        if not os.path.isdir(full) or d == 'ocr':
            continue
        # Try to find matching OCR file
        # Issue dir format: YYYY-MM-DD_vVVnNN
        # OCR file format: vVVnNN_YYYY-MM-DD.md
        parts = d.split('_')
        if len(parts) >= 2:
            date_part = parts[0]
            vol_part = parts[1]
            ocr_name = f"{vol_part}_{date_part}.md"
            ocr_path = os.path.join(ocr_dir, ocr_name)
            if os.path.isfile(ocr_path):
                issues.append((d, ocr_name))
    return issues


def main():
    # Sample: pick 2 random issues from each of 5 years spread across the range
    sample_years = [1891, 1894, 1896, 1898, 1900]
    sample_size_per_year = 2

    if len(sys.argv) > 1 and sys.argv[1] == '--all-years':
        sample_years = list(range(1891, 1901))
        sample_size_per_year = 1

    random.seed(42)  # Reproducible

    print("=" * 80)
    print("ACCURACY VERIFICATION: OCR Source vs Split Articles")
    print("=" * 80)
    print()

    all_results = []
    for year in sample_years:
        issues = find_issues(year)
        if not issues:
            print(f"  {year}: No issues found with OCR sources")
            continue

        sample = random.sample(issues, min(sample_size_per_year, len(issues)))
        for issue_dir, ocr_file in sample:
            result, err = compare_issue(year, issue_dir, ocr_file)
            if err:
                print(f"  ERROR: {err}")
                continue
            all_results.append(result)

    # Print results
    print(f"{'Year':<6} {'Issue':<28} {'OCR Words':<11} {'Art Words':<11} {'Similarity':<12} {'Changes'}")
    print("-" * 90)

    for r in all_results:
        sim_pct = f"{r['similarity']*100:.2f}%"
        print(f"{r['year']:<6} {r['issue']:<28} {r['ocr_words']:<11} {r['article_words']:<11} {sim_pct:<12} {r['num_changes']}")

    # Summary
    print()
    print("=" * 80)
    avg_sim = sum(r['similarity'] for r in all_results) / len(all_results) if all_results else 0
    total_changes = sum(r['num_changes'] for r in all_results)
    print(f"Average similarity: {avg_sim*100:.2f}%")
    print(f"Total change regions across all samples: {total_changes}")
    print()

    # Show detailed changes for issues with differences
    for r in all_results:
        if r['num_changes'] > 0:
            print(f"\n--- {r['year']} {r['issue']} ({r['num_changes']} changes) ---")
            for i, c in enumerate(r['changes'][:15]):  # Show first 15 changes
                print(f"  [{c['type']}] {c['ocr_pos']} / {c['art_pos']}")
                if c['ocr']:
                    print(f"    OCR:     {c['ocr']}")
                if c['article']:
                    print(f"    Article: {c['article']}")
            if r['num_changes'] > 15:
                print(f"  ... and {r['num_changes'] - 15} more changes")


if __name__ == '__main__':
    main()
