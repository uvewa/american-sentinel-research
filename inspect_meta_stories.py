#!/usr/bin/env python3
"""
Inspect all meta stories in an IDML file to identify each issue's metadata.
Prints volume, number, date, location, motto, and the raw paragraph text
for every story classified as 'meta'.
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
)


def inspect_meta_stories(idml_path: Path):
    meta_stories = []
    content_stories = []

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
                meta_stories.append((idx, story_path, meta, paragraphs))
            elif story_type == 'content':
                content_stories.append((idx, story_path, paragraphs))

    print(f"IDML file: {idml_path.name}")
    print(f"Total meta stories: {len(meta_stories)}")
    print(f"Total content stories: {len(content_stories)}")
    print()

    for i, (idx, path, meta, paragraphs) in enumerate(meta_stories):
        print(f"{'='*70}")
        print(f"META STORY #{i+1}  (document order index: {idx})")
        print(f"  Story file: {path}")
        print(f"  Volume:     {meta.get('volume', '???')}")
        print(f"  Number:     {meta.get('number', '???')}")
        print(f"  Year:       {meta.get('year', '???')}")
        print(f"  Month:      {meta.get('month', '???')}")
        print(f"  Date str:   {meta.get('date_str', '???')}")
        print(f"  Location:   {meta.get('location', '???')}")
        print(f"  Motto:      {meta.get('motto', '???')}")
        print()
        print(f"  --- All paragraphs in this story ---")
        for j, para in enumerate(paragraphs):
            text = para.plain_text.strip()
            if text:
                print(f"    [{j:02d}] style='{para.style}' -> {repr(text)}")
            else:
                print(f"    [{j:02d}] style='{para.style}' -> (empty)")
        print()

    # Also show content stories briefly for pairing context
    print(f"\n{'='*70}")
    print(f"CONTENT STORIES (for pairing reference):")
    for i, (idx, path, paragraphs) in enumerate(content_stories):
        # Find the first heading to identify the issue content
        first_heading = ""
        for p in paragraphs:
            if p.style in ('Heading 1', 'Heading 2', 'Heading 2 Subtitle') and not p.is_empty:
                first_heading = p.plain_text.strip()
                break
        non_empty = sum(1 for p in paragraphs if not p.is_empty)
        print(f"  Content #{i+1} (index {idx}, {path}): {non_empty} paragraphs, first heading: '{first_heading}'")


if __name__ == '__main__':
    idml_path = Path("/Users/apl/StudioProjects/ocr/_files/idml/1888/The American Sentinel EN 01-12 03g.idml")
    if not idml_path.exists():
        print(f"Error: {idml_path} not found")
        sys.exit(1)
    inspect_meta_stories(idml_path)
