#!/usr/bin/env python3
"""
Detailed accuracy analysis: categorize the types of changes agents made.
"""

import os
import re
import difflib
import random

BASE = "/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/2. Transcribed"

# Smart quote pairs
SMART_QUOTES = {
    '\u201c': '"',  # left double
    '\u201d': '"',  # right double
    '\u2018': "'",  # left single
    '\u2019': "'",  # right single
    '\u2014': '—',  # em dash (same)
}

def strip_frontmatter(text):
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            return text[end + 3:].strip()
    return text.strip()

def strip_ocr_header(text):
    lines = text.split('\n')
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == '---':
            start = i + 1
            break
    content_lines = []
    for line in lines[start:]:
        if line.strip() == '---':
            continue
        content_lines.append(line)
    return '\n'.join(content_lines).strip()

def is_quote_change(ocr_word, art_word):
    """Check if the only difference is smart quotes vs straight quotes."""
    # Normalize both to straight quotes and compare
    normalized_ocr = ocr_word
    normalized_art = art_word
    for smart, straight in SMART_QUOTES.items():
        normalized_ocr = normalized_ocr.replace(smart, straight)
        normalized_art = normalized_art.replace(smart, straight)
    # Also normalize the other direction
    for smart, straight in SMART_QUOTES.items():
        normalized_ocr = normalized_ocr.replace(straight, straight)
        normalized_art = normalized_art.replace(straight, straight)
    return normalized_ocr == normalized_art

def is_page_marker(text):
    """Check if text is a PAGE marker from OCR."""
    return bool(re.match(r'=+\s*PAGE\s+\d+\s*=+', text.strip()))

def is_heading_marker(text):
    """Check if text is just a markdown heading marker."""
    return text.strip() in ('#', '##', '###', '####')

def classify_change(tag, ocr_words, art_words):
    """Classify a change into categories."""
    ocr_text = ' '.join(ocr_words)
    art_text = ' '.join(art_words)

    # Page markers removed
    if tag == 'delete' and is_page_marker(ocr_text):
        return 'page_marker_removed'

    # Heading markers added
    if tag == 'insert' and is_heading_marker(art_text):
        return 'heading_added'

    # Quote normalization
    if tag == 'replace' and len(ocr_words) == len(art_words):
        all_quote = True
        for ow, aw in zip(ocr_words, art_words):
            if not is_quote_change(ow, aw):
                all_quote = False
                break
        if all_quote:
            return 'quote_normalization'

    # Article reordering (large blocks)
    if tag in ('insert', 'delete') and len(ocr_words if tag == 'delete' else art_words) > 50:
        return 'article_reordering'

    # Title removal/reformatting
    if tag == 'delete' and ocr_text.startswith('#'):
        return 'title_reformatted'

    # Actual word changes
    if tag == 'replace':
        # Check for specific OCR corrections
        return 'word_change'

    if tag == 'insert':
        if len(art_words) <= 3:
            return 'minor_insertion'
        return 'content_added'

    if tag == 'delete':
        if len(ocr_words) <= 3:
            return 'minor_deletion'
        return 'content_removed'

    return 'other'


def get_article_text(issue_dir):
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
    with open(ocr_path, 'r') as fh:
        content = fh.read()
    return strip_ocr_header(content)


def find_issues(year):
    year_dir = os.path.join(BASE, str(year))
    ocr_dir = os.path.join(year_dir, 'ocr')
    if not os.path.isdir(ocr_dir):
        return []
    issues = []
    for d in sorted(os.listdir(year_dir)):
        full = os.path.join(year_dir, d)
        if not os.path.isdir(full) or d == 'ocr':
            continue
        parts = d.split('_')
        if len(parts) >= 2:
            date_part = parts[0]
            vol_part = parts[1]
            ocr_name = f"{vol_part}_{date_part}.md"
            ocr_path = os.path.join(ocr_dir, ocr_name)
            if os.path.isfile(ocr_path):
                issues.append((d, ocr_name))
    return issues


def analyze_issue(year, issue_dir_name, ocr_filename):
    issue_dir = os.path.join(BASE, str(year), issue_dir_name)
    ocr_path = os.path.join(BASE, str(year), 'ocr', ocr_filename)

    article_text = get_article_text(issue_dir)
    ocr_text = get_ocr_text(ocr_path)

    article_words = article_text.split()
    ocr_words = ocr_text.split()

    sm = difflib.SequenceMatcher(None, ocr_words, article_words)

    categories = {}
    word_changes = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue

        cat = classify_change(tag, ocr_words[i1:i2], article_words[j1:j2])
        categories[cat] = categories.get(cat, 0) + 1

        if cat == 'word_change':
            ocr_snippet = ' '.join(ocr_words[i1:i2])
            art_snippet = ' '.join(article_words[j1:j2])
            # Filter out pure quote changes that slipped through
            if ocr_snippet.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'") != \
               art_snippet.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'"):
                if len(ocr_snippet) < 200:
                    word_changes.append((ocr_snippet, art_snippet))

    return categories, word_changes


def main():
    sample_years = [1891, 1893, 1894, 1895, 1896, 1897, 1898, 1899, 1900]
    random.seed(42)

    print("=" * 80)
    print("DETAILED ACCURACY ANALYSIS: Types of Changes Made by Splitting Agents")
    print("=" * 80)
    print()

    total_categories = {}
    all_word_changes = []

    for year in sample_years:
        issues = find_issues(year)
        if not issues:
            continue
        sample = random.sample(issues, min(2, len(issues)))

        for issue_dir, ocr_file in sample:
            print(f"Analyzing {year} {issue_dir}...")
            cats, wchanges = analyze_issue(year, issue_dir, ocr_file)
            for k, v in cats.items():
                total_categories[k] = total_categories.get(k, 0) + v
            for wc in wchanges:
                all_word_changes.append((year, issue_dir, wc[0], wc[1]))

    print()
    print("=" * 80)
    print("CHANGE CATEGORIES (across all sampled issues)")
    print("=" * 80)
    for cat, count in sorted(total_categories.items(), key=lambda x: -x[1]):
        print(f"  {cat:<30} {count:>6}")

    print()
    print("=" * 80)
    print(f"ACTUAL WORD CHANGES (not quote/formatting): {len(all_word_changes)} found")
    print("These are cases where the agent changed actual words, not just formatting.")
    print("=" * 80)
    for year, issue, ocr_w, art_w in all_word_changes[:50]:
        print(f"\n  {year} {issue}")
        print(f"    OCR:     {ocr_w}")
        print(f"    Article: {art_w}")

    if len(all_word_changes) > 50:
        print(f"\n  ... and {len(all_word_changes) - 50} more")


if __name__ == '__main__':
    main()
