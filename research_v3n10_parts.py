#!/usr/bin/env python3
"""
Research script: Investigate the two parts of Volume 3, Number 10 (October 1888).

This script:
1. Opens the IDML ZIP
2. Finds the two "Volume 3 Number 10" meta stories (Part 1 and Part 2)
3. Pairs each with its content story (by document order)
4. Extracts article titles from each part
5. Reports what articles are in Part 1 vs Part 2
"""

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# Reuse parsing logic from extract_idml.py
sys.path.insert(0, str(Path(__file__).parent))
from extract_idml import (
    get_story_order,
    parse_story,
    classify_story,
    extract_issue_meta,
    split_into_articles,
)


def main():
    idml_path = Path("/Users/apl/StudioProjects/ocr/_files/idml/1888/The American Sentinel EN 01-12 03g.idml")
    if not idml_path.exists():
        print(f"Error: {idml_path} not found")
        sys.exit(1)

    # Parse all stories with their document-order index
    meta_stories = []   # [(index, story_path, meta_dict, raw_vol_line)]
    content_stories = []  # [(index, story_path, paragraphs)]

    with zipfile.ZipFile(idml_path, 'r') as z:
        story_paths = get_story_order(z)

        for idx, story_path in enumerate(story_paths):
            if not story_path.startswith('Stories/'):
                continue

            xml_content = z.read(story_path).decode('utf-8')
            paragraphs = parse_story(xml_content)
            story_type = classify_story(paragraphs)

            if story_type == 'meta':
                meta = extract_issue_meta(paragraphs)
                # Get the raw "Volume and Number" line to detect Part 1/Part 2
                raw_vol_line = ''
                for p in paragraphs:
                    if p.style == 'Volume and Number' and not p.is_empty:
                        raw_vol_line = p.plain_text.strip()
                        break
                meta_stories.append((idx, story_path, meta, raw_vol_line))
            elif story_type == 'content':
                content_stories.append((idx, story_path, paragraphs))

    # Sort both by document order
    meta_stories.sort(key=lambda x: x[0])
    content_stories.sort(key=lambda x: x[0])

    # Show the full sorted pairing
    print("=" * 70)
    print("ALL META <-> CONTENT PAIRINGS (by document order)")
    print("=" * 70)
    for i, ((mi, mpath, meta, raw_vol), (ci, cpath, cparas)) in enumerate(
        zip(meta_stories, content_stories)
    ):
        vol = meta.get('volume', '?')
        num = meta.get('number', '?')
        date = meta.get('date_str', '?')
        # First heading from content
        first_heading = ''
        for p in cparas:
            if p.style in ('Heading 1', 'Heading 2', 'Heading 2 Subtitle') and not p.is_empty:
                first_heading = p.plain_text.strip()
                break
        marker = " <-- V3N10" if (vol == 3 and num == 10) else ""
        print(f"  Pair {i+1:2d}: meta[{mi:2d}] '{raw_vol}' ({date})  <->  content[{ci:2d}] '{first_heading}'{marker}")

    print()

    # Now focus on the two V3N10 pairs
    print("=" * 70)
    print("DETAILED ANALYSIS: Volume 3, Number 10 (October 1888)")
    print("=" * 70)

    # Find the two V3N10 meta stories
    v3n10_metas = [(mi, mpath, meta, raw_vol) for mi, mpath, meta, raw_vol in meta_stories
                   if meta.get('volume') == 3 and meta.get('number') == 10]

    print(f"\nFound {len(v3n10_metas)} meta stories for V3N10:")
    for mi, mpath, meta, raw_vol in v3n10_metas:
        print(f"  Index {mi}: '{raw_vol}' -> {mpath}")

    # Find which content stories they pair with
    # The pairing is positional: meta sorted by index pairs with content sorted by index
    meta_indices = [mi for mi, _, _, _ in meta_stories]
    content_indices = [ci for ci, _, _ in content_stories]

    for mi, mpath, meta, raw_vol in v3n10_metas:
        # Find position in sorted meta list
        meta_pos = meta_indices.index(mi)
        # The paired content is at the same position
        ci, cpath, cparas = content_stories[meta_pos]

        part_label = "Part 1" if "Part 1" in raw_vol else ("Part 2" if "Part 2" in raw_vol else "Unknown Part")

        print(f"\n{'─' * 60}")
        print(f"  {part_label}: meta index={mi}, content index={ci}")
        print(f"  Meta story: {mpath}")
        print(f"  Content story: {cpath}")
        print(f"  Raw volume line: '{raw_vol}'")
        print(f"  Date: {meta.get('date_str', '?')}")

        # Extract articles from this content story
        articles = split_into_articles(cparas)

        print(f"\n  ARTICLES ({len(articles)} total):")
        for j, article in enumerate(articles, 1):
            # Count substantive paragraphs
            body_paras = sum(1 for p in article.paragraphs if not p.is_empty)
            # Get attribution info
            attr_info = ""
            if article.author:
                attr_info = f" [{article.author_short or article.author}]"
            elif article.attribution == 'reprint' and article.original_publication:
                attr_info = f" [reprint from {article.original_publication}]"
            elif article.attribution:
                attr_info = f" [{article.attribution}]"
            print(f"    {j:2d}. {article.title}{attr_info}  ({body_paras} paragraphs)")

        # Also show the first few lines of the content to check for pre-article text
        print(f"\n  FIRST 10 NON-EMPTY PARAGRAPHS (raw content):")
        count = 0
        for p in cparas:
            if not p.is_empty:
                text = p.plain_text.strip()
                if len(text) > 80:
                    text = text[:80] + "..."
                print(f"    style='{p.style}': {text}")
                count += 1
                if count >= 10:
                    break

    # Summary comparison
    print(f"\n{'=' * 70}")
    print("SUMMARY: Is this a regular issue + supplement, or two halves?")
    print("=" * 70)

    for mi, mpath, meta, raw_vol in v3n10_metas:
        meta_pos = meta_indices.index(mi)
        ci, cpath, cparas = content_stories[meta_pos]
        articles = split_into_articles(cparas)
        part_label = "Part 1" if "Part 1" in raw_vol else "Part 2"

        total_paras = sum(1 for p in cparas if not p.is_empty)
        article_titles = [a.title for a in articles]

        print(f"\n  {part_label}:")
        print(f"    Total non-empty paragraphs: {total_paras}")
        print(f"    Number of articles: {len(articles)}")
        print(f"    Article titles:")
        for t in article_titles:
            print(f"      - {t}")


if __name__ == '__main__':
    main()
