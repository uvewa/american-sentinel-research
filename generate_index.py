#!/usr/bin/env python3
"""
Generate browsable markdown indexes from catalog.json.

Creates:
- by-category.md - Articles organized by principle and application
- by-author.md - Articles organized by author
- by-date.md - Articles in chronological order

Usage:
    python generate_index.py [--catalog PATH] [--output-dir PATH]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_catalog(catalog_path: Path) -> dict:
    """Load catalog.json."""
    with open(catalog_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_by_category(catalog: dict, output_path: Path) -> None:
    """Generate index organized by principle and application."""
    # Group articles by principle
    by_principle = defaultdict(list)
    for article in catalog['articles']:
        for principle in article.get('principles', []):
            by_principle[principle].append(article)

    # Group by application within each principle
    lines = [
        "# Articles by Category",
        "",
        f"*Generated from {catalog['article_count']} articles*",
        "",
        "---",
        "",
    ]

    taxonomy = catalog.get('taxonomy', {})
    principles = taxonomy.get('principles', sorted(by_principle.keys()))

    for principle in principles:
        articles = by_principle.get(principle, [])
        if not articles:
            continue

        lines.append(f"## {principle}")
        lines.append("")

        # Group by application within this principle
        by_app = defaultdict(list)
        for article in articles:
            apps = article.get('applications', [])
            if apps:
                for app in apps:
                    by_app[app].append(article)
            else:
                by_app['(Uncategorized)'].append(article)

        # Sort applications
        for app in sorted(by_app.keys()):
            app_articles = by_app[app]
            lines.append(f"### {app}")
            lines.append("")

            # Sort articles by date
            for article in sorted(app_articles, key=lambda a: a.get('date', '')):
                title = article.get('title', 'Untitled')
                author = article.get('author_short') or article.get('author', '')
                date = article.get('date', '')
                path = article.get('path', '')

                author_str = f" - {author}" if author else ""
                lines.append(f"- [{title}]({path}){author_str}, {date}")

            lines.append("")

        lines.append("---")
        lines.append("")

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")


def generate_by_author(catalog: dict, output_path: Path) -> None:
    """Generate index organized by author."""
    by_author = defaultdict(list)
    for article in catalog['articles']:
        author = article.get('author') or article.get('author_short') or 'Anonymous/Unknown'
        by_author[author].append(article)

    lines = [
        "# Articles by Author",
        "",
        f"*Generated from {catalog['article_count']} articles*",
        "",
        "---",
        "",
    ]

    for author in sorted(by_author.keys()):
        articles = by_author[author]
        lines.append(f"## {author}")
        lines.append("")

        for article in sorted(articles, key=lambda a: a.get('date', '')):
            title = article.get('title', 'Untitled')
            date = article.get('date', '')
            path = article.get('path', '')
            principles = ', '.join(article.get('principles', []))

            lines.append(f"- [{title}]({path}) - {date}")
            if principles:
                lines.append(f"  - *{principles}*")

        lines.append("")

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")


def generate_by_date(catalog: dict, output_path: Path) -> None:
    """Generate chronological index."""
    articles = sorted(catalog['articles'], key=lambda a: a.get('date', ''))

    lines = [
        "# Articles by Date",
        "",
        f"*Generated from {catalog['article_count']} articles*",
        "",
        "---",
        "",
    ]

    current_year = None
    for article in articles:
        date = article.get('date', '')
        year = date[:4] if date else 'Unknown'

        if year != current_year:
            current_year = year
            lines.append(f"## {year}")
            lines.append("")

        title = article.get('title', 'Untitled')
        author = article.get('author_short') or article.get('author', '')
        path = article.get('path', '')
        publication = article.get('publication', '')

        author_str = f" ({author})" if author else ""
        lines.append(f"- **{date}** - [{title}]({path}){author_str}")

    lines.append("")
    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")


def generate_taxonomy(catalog: dict, output_path: Path) -> None:
    """Generate taxonomy overview."""
    taxonomy = catalog.get('taxonomy', {})

    lines = [
        "# Taxonomy Overview",
        "",
        f"*Generated from {catalog['article_count']} articles*",
        "",
        "---",
        "",
        "## Principles and Applications",
        "",
    ]

    principles = taxonomy.get('principles', [])
    applications = taxonomy.get('applications', {})

    for principle in principles:
        apps = applications.get(principle, [])
        lines.append(f"### {principle}")
        lines.append("")
        if apps:
            for app in apps:
                lines.append(f"- {app}")
        else:
            lines.append("- *(no applications yet)*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## All Keywords")
    lines.append("")

    keywords = taxonomy.get('keywords', [])
    # Group keywords alphabetically
    lines.append(", ".join(keywords))
    lines.append("")

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate browsable markdown indexes from catalog.json'
    )
    parser.add_argument(
        '--catalog',
        type=Path,
        default=Path('catalog.json'),
        help='Path to catalog.json'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('.'),
        help='Output directory for index files'
    )

    args = parser.parse_args()

    if not args.catalog.exists():
        print(f"Error: Catalog not found: {args.catalog}")
        print("Run build_catalog.py first to generate the catalog.")
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog(args.catalog)

    print(f"Loaded catalog with {catalog['article_count']} articles")
    print()

    generate_by_category(catalog, args.output_dir / 'by-category.md')
    generate_by_author(catalog, args.output_dir / 'by-author.md')
    generate_by_date(catalog, args.output_dir / 'by-date.md')
    generate_taxonomy(catalog, args.output_dir / 'taxonomy.md')

    print()
    print("Done! Open any of the .md files to browse.")


if __name__ == '__main__':
    main()
