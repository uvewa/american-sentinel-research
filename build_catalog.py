#!/usr/bin/env python3
"""
Build catalog.json from article frontmatter.

Scans all transcribed article .md files, extracts YAML frontmatter,
and builds a searchable catalog with taxonomy.

Usage:
    python build_catalog.py [--content-dir PATH] [--output PATH]

Options:
    --content-dir PATH  Root directory containing transcribed files
                        Default: ../Documents/PUBLICAR/APL/English
    --output PATH       Output catalog file path
                        Default: catalog.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


def extract_frontmatter(file_path: Path) -> dict[str, Any] | None:
    """Extract YAML frontmatter from a markdown file."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"  Warning: Could not read {file_path}: {e}")
        return None

    # Match YAML frontmatter between --- delimiters
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
        return frontmatter if isinstance(frontmatter, dict) else None
    except yaml.YAMLError as e:
        print(f"  Warning: Invalid YAML in {file_path}: {e}")
        return None


def generate_article_id(frontmatter: dict, file_path: Path) -> str:
    """Generate a unique article ID from frontmatter and path."""
    pub = frontmatter.get('publication', 'unknown')
    date = frontmatter.get('date', '')

    # Extract article number from filename (e.g., "02_The-Situation..." -> "02")
    filename = file_path.stem
    num_match = re.match(r'^(\d+)_', filename)
    article_num = num_match.group(1) if num_match else '00'

    # Build ID: as-1891-01-01-02 (publication-date-article_num)
    pub_short = {
        'American Sentinel': 'as',
        'Signs of the Times': 'st',
        'Review and Herald': 'rh',
    }.get(pub, pub[:2].lower())

    if isinstance(date, datetime):
        date_str = date.strftime('%Y-%m-%d')
    else:
        date_str = str(date) if date else 'unknown'

    return f"{pub_short}-{date_str}-{article_num}"


def build_catalog(content_dir: Path) -> dict[str, Any]:
    """Scan content directory and build catalog."""
    articles = []
    all_principles = set()
    all_applications = {}  # principle -> set of applications
    all_keywords = set()

    # Find all .md files in Transcribed directories
    transcribed_pattern = "**/2. Transcribed/**/*.md"
    md_files = list(content_dir.glob(transcribed_pattern))

    print(f"Scanning {len(md_files)} markdown files...")

    for file_path in sorted(md_files):
        # Skip non-article files
        filename = file_path.name
        if filename in ('uncertainties.md',):
            continue
        if filename.startswith('00_masthead'):
            continue
        if filename.endswith('_Publication-Info.md'):
            continue

        frontmatter = extract_frontmatter(file_path)
        if not frontmatter:
            continue

        # Extract fields
        title = frontmatter.get('title', '')
        if not title:
            continue

        article_id = generate_article_id(frontmatter, file_path)

        # Build relative path from content_dir
        rel_path = file_path.relative_to(content_dir)

        # Extract categorization (handle None values)
        principles = frontmatter.get('principles') or []
        applications = frontmatter.get('applications') or []
        keywords = frontmatter.get('keywords') or []

        # Track taxonomy
        for p in principles:
            all_principles.add(p)
            if p not in all_applications:
                all_applications[p] = set()

        for a in applications:
            # Associate applications with principles mentioned in same article
            for p in principles:
                all_applications[p].add(a)

        for k in keywords:
            all_keywords.add(str(k))  # Convert to string (handles years, numbers)

        # Handle date formatting
        date = frontmatter.get('date')
        if isinstance(date, datetime):
            date_str = date.strftime('%Y-%m-%d')
        else:
            date_str = str(date) if date else None

        # Editorial articles without an explicit author get a virtual author name
        author = frontmatter.get('author')
        author_short = frontmatter.get('author_short')
        if not author and frontmatter.get('attribution') == 'editorial':
            author = 'Editorial Notes'

        article = {
            'id': article_id,
            'path': str(rel_path),
            'title': title,
            'author': author,
            'author_short': author_short,
            'date': date_str,
            'publication': frontmatter.get('publication'),
            'volume': frontmatter.get('volume'),
            'issue': frontmatter.get('issue'),
            'attribution': frontmatter.get('attribution'),
            'original_publication': frontmatter.get('original_publication'),
            'principles': principles,
            'applications': applications,
            'keywords': keywords,
        }

        # Remove None values for cleaner output
        article = {k: v for k, v in article.items() if v is not None}

        articles.append(article)
        print(f"  Added: {title[:50]}...")

    # Build taxonomy
    taxonomy = {
        'principles': sorted(all_principles),
        'applications': {
            p: sorted(apps) for p, apps in sorted(all_applications.items())
        },
        'keywords': sorted(all_keywords),
    }

    catalog = {
        'generated': datetime.now().astimezone().isoformat(),
        'article_count': len(articles),
        'taxonomy': taxonomy,
        'articles': articles,
    }

    return catalog


def validate_frontmatter(catalog: dict) -> list[str]:
    """Check for common frontmatter issues."""
    issues = []

    for article in catalog['articles']:
        article_id = article.get('id', 'unknown')

        # Check required fields
        if not article.get('title'):
            issues.append(f"{article_id}: Missing title")
        if not article.get('date'):
            issues.append(f"{article_id}: Missing date")
        if not article.get('publication'):
            issues.append(f"{article_id}: Missing publication")

        # Check attribution
        attr = article.get('attribution')
        if not attr:
            issues.append(f"{article_id}: Missing attribution")
        elif attr not in ('explicit', 'reprint', 'editorial'):
            issues.append(f"{article_id}: Invalid attribution value: {attr}")

        # Check categorization
        if not article.get('principles'):
            issues.append(f"{article_id}: No principles assigned")
        if not article.get('applications'):
            issues.append(f"{article_id}: No applications assigned")

    return issues


def print_taxonomy_stats(catalog: dict) -> None:
    """Print statistics about the taxonomy."""
    taxonomy = catalog['taxonomy']

    print("\n--- Taxonomy Statistics ---")
    print(f"Principles: {len(taxonomy['principles'])}")
    for p in taxonomy['principles']:
        apps = taxonomy['applications'].get(p, [])
        print(f"  {p}: {len(apps)} applications")

    print(f"\nTotal unique keywords: {len(taxonomy['keywords'])}")
    print(f"Total articles: {catalog['article_count']}")

    # Attribution breakdown
    attr_counts = {}
    for article in catalog['articles']:
        attr = article.get('attribution', 'missing')
        attr_counts[attr] = attr_counts.get(attr, 0) + 1
    if attr_counts:
        print("\n--- Attribution Breakdown ---")
        for attr in ('explicit', 'reprint', 'editorial', 'missing'):
            count = attr_counts.get(attr, 0)
            if count:
                print(f"  {attr}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description='Build catalog.json from article frontmatter'
    )
    parser.add_argument(
        '--content-dir',
        type=Path,
        default=Path.home() / 'Documents/PUBLICAR/APL/English',
        help='Root directory containing transcribed files'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('catalog.json'),
        help='Output catalog file path'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Check for frontmatter issues'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Print taxonomy statistics'
    )

    args = parser.parse_args()

    if not args.content_dir.exists():
        print(f"Error: Content directory not found: {args.content_dir}")
        sys.exit(1)

    print(f"Content directory: {args.content_dir}")
    print(f"Output file: {args.output}")

    catalog = build_catalog(args.content_dir)

    # Write catalog
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"\nCatalog written to {args.output}")
    print(f"Total articles: {catalog['article_count']}")

    if args.validate:
        issues = validate_frontmatter(catalog)
        if issues:
            print("\n--- Validation Issues ---")
            for issue in issues:
                print(f"  {issue}")
        else:
            print("\nNo validation issues found.")

    if args.stats:
        print_taxonomy_stats(catalog)


if __name__ == '__main__':
    main()
