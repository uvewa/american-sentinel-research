#!/usr/bin/env python3
"""
Build static research portal from transcribed article files.

Generates a complete static site that can be served from any web server
(including Apache/Nginx subdirectories, GitHub Pages, or even file://).

Usage:
    python build_site.py [--content-dir PATH] [--output PATH] [--template PATH]

Produces:
    research/
      index.html          - SPA with embedded catalog reference
      catalog.json        - Article metadata index
      articles/           - Pre-rendered HTML fragments (one per article)
        as-1886-01-01-01.html
        as-1886-01-01-02.html
        ...
      .htaccess           - RewriteEngine Off (prevent WordPress interference)
"""

import argparse
import json
import os
import re
import html
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Import catalog-building functions from build_catalog.py (same directory)
# ---------------------------------------------------------------------------
_script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_script_dir))

try:
    from build_catalog import build_catalog, extract_frontmatter, generate_article_id
except ImportError:
    print("Error: Could not import from build_catalog.py.")
    print("Make sure build_catalog.py is in the same directory as this script.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Markdown-to-HTML converter (adapted from server.py)
# ---------------------------------------------------------------------------

def markdown_to_html(md: str) -> str:
    """
    Convert article markdown body to HTML fragment.

    Handles headings, blockquotes, unordered/ordered lists, horizontal rules,
    bold, italic, and regular paragraphs. Designed for the simple subset of
    markdown used in the transcription files (no tables, images, or code blocks).
    """
    lines = md.split('\n')
    html_lines = []
    in_blockquote = False
    in_list = False
    list_tag = 'ul'  # track whether current list is <ul> or <ol>

    def next_nonblank(idx):
        """Return the next non-blank line after idx, or ''."""
        for j in range(idx + 1, len(lines)):
            if lines[j].strip():
                return lines[j]
        return ''

    for i, line in enumerate(lines):
        # Headers
        if line.startswith('# '):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append(f'<h1>{_inline(line[2:])}</h1>')

        elif line.startswith('## '):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append(f'<h2>{_inline(line[3:])}</h2>')

        elif line.startswith('### '):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append(f'<h3>{_inline(line[4:])}</h3>')

        elif line.startswith('#### '):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append(f'<h4>{_inline(line[5:])}</h4>')

        # Blockquotes
        elif line.startswith('> '):
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            if not in_blockquote:
                html_lines.append('<blockquote>')
                in_blockquote = True
            html_lines.append(_inline(line[2:]) + '<br>')

        # Horizontal rule
        elif line.strip() == '---':
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append('<hr>')

        # Unordered list items
        elif line.startswith('- '):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list and list_tag != 'ul':
                html_lines.append(f'</{list_tag}>')
                in_list = False
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
                list_tag = 'ul'
            html_lines.append(f'<li>{_inline(line[2:])}</li>')

        # Ordered list items
        elif re.match(r'^\d+\.\s', line.strip()):
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list and list_tag != 'ol':
                html_lines.append(f'</{list_tag}>')
                in_list = False
            if not in_list:
                html_lines.append('<ol>')
                in_list = True
                list_tag = 'ol'
            text = re.sub(r'^\d+\.\s*', '', line.strip())
            html_lines.append(f'<li>{_inline(text)}</li>')

        # Empty line - close open blocks, add spacing
        elif line.strip() == '':
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                # Keep list open if the next content line is another list item
                nxt = next_nonblank(i)
                is_next_ol = bool(re.match(r'^\d+\.\s', nxt.strip())) if nxt else False
                is_next_ul = nxt.startswith('- ') if nxt else False
                if (list_tag == 'ol' and is_next_ol) or (list_tag == 'ul' and is_next_ul):
                    pass  # keep list open
                else:
                    html_lines.append(f'</{list_tag}>')
                    in_list = False
            html_lines.append('')

        # Regular paragraph
        else:
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append(f'</{list_tag}>')
                in_list = False
            html_lines.append(f'<p>{_inline(line)}</p>')

    # Close any open blocks
    if in_blockquote:
        html_lines.append('</blockquote>')
    if in_list:
        html_lines.append(f'</{list_tag}>')

    return '\n'.join(html_lines)


def _inline(text: str) -> str:
    """Apply inline formatting (bold, italic) after HTML-escaping."""
    text = html.escape(text)
    # Bold must come before italic so **bold** is not eaten by *italic* regex
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


# ---------------------------------------------------------------------------
# Article body extraction
# ---------------------------------------------------------------------------

def extract_article_body(file_path: Path) -> str:
    """Read a .md file and return the body text after YAML frontmatter."""
    content = file_path.read_text(encoding='utf-8')
    match = re.match(r'^---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
    return match.group(1) if match else content


def extract_plain_text(md_body: str) -> str:
    """Strip markdown formatting from body text, returning plain text for search indexing."""
    lines = md_body.split('\n')
    result = []
    for line in lines:
        # Strip header markers
        line = re.sub(r'^#{1,6}\s+', '', line)
        # Strip blockquote markers
        line = re.sub(r'^>\s*', '', line)
        # Strip unordered list markers
        line = re.sub(r'^-\s+', '', line)
        # Strip ordered list markers
        line = re.sub(r'^\d+\.\s+', '', line)
        # Strip horizontal rules
        if line.strip() == '---':
            continue
        # Strip bold and italic markers
        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
        line = re.sub(r'\*(.+?)\*', r'\1', line)
        # Keep non-empty lines
        stripped = line.strip()
        if stripped:
            result.append(stripped)
    return ' '.join(result)


# ---------------------------------------------------------------------------
# Static HTML template (adapted from server.py for static file serving)
# ---------------------------------------------------------------------------

STATIC_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Searchable archive of American Sentinel articles on religious liberty and church-state separation, 1886-1900. Browse by principle, author, year, or keyword.">
    <meta name="robots" content="index, follow">
    <meta property="og:title" content="{SITE_TITLE}">
    <meta property="og:description" content="Historical writings on religious liberty and church-state separation, 1886-1900">
    <meta property="og:type" content="website">
    <title>{SITE_TITLE}</title>
    <noscript>
        <style>.app-root{display:none!important}</style>
    </noscript>
    <style>
        /* ================================================================
           CSS RESET & CUSTOM PROPERTIES
           ================================================================ */
        :root {
            --color-navy: #2c3e50;
            --color-navy-dark: #1a252f;
            --color-blue: #3498db;
            --color-blue-hover: #2980b9;
            --color-blue-light: #e8f4f8;
            --color-bg: #f8f9fa;
            --color-card: #ffffff;
            --color-text: #2d3436;
            --color-text-secondary: #636e72;
            --color-text-muted: #95a5a6;
            --color-border: #dfe6e9;
            --color-border-light: #ecf0f1;
            --color-tag-principle-bg: #dbeafe;
            --color-tag-principle-text: #1e40af;
            --color-tag-application-bg: #e5e7eb;
            --color-tag-application-text: #374151;
            --color-tag-keyword-bg: #f3f4f6;
            --color-tag-keyword-text: #6b7280;
            --color-success: #27ae60;
            --color-error: #e74c3c;
            --sidebar-width: 300px;
            --header-height: auto;
            --transition-fast: 0.15s ease;
            --transition-normal: 0.25s ease;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
            --shadow-md: 0 4px 12px rgba(0,0,0,0.1);
            --shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
            --radius-sm: 4px;
            --radius-md: 8px;
            --radius-lg: 12px;
        }

        *, *::before, *::after {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        html {
            font-size: 16px;
            -webkit-text-size-adjust: 100%;
            scroll-behavior: smooth;
        }

        body {
            font-family: Georgia, 'Times New Roman', Times, serif;
            background: var(--color-bg);
            color: var(--color-text);
            line-height: 1.7;
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* ================================================================
           TYPOGRAPHY
           ================================================================ */
        h1, h2, h3, h4, h5, h6 {
            line-height: 1.3;
            font-weight: 700;
        }

        a {
            color: var(--color-blue);
            text-decoration: none;
            transition: color var(--transition-fast);
        }

        a:hover {
            color: var(--color-blue-hover);
        }

        /* ================================================================
           HEADER
           ================================================================ */
        .site-header {
            background: var(--color-navy);
            color: #ffffff;
            padding: 1.25rem 2rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            position: relative;
            z-index: 100;
        }

        .site-header-inner {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .site-header .back-link {
            color: rgba(255,255,255,0.7);
            font-size: 0.85rem;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            transition: color var(--transition-fast);
            white-space: nowrap;
        }

        .site-header .back-link:hover {
            color: #ffffff;
        }

        .site-header h1 {
            font-size: 1.5rem;
            font-weight: 400;
            letter-spacing: 0.01em;
            margin-bottom: 0.2rem;
        }

        .site-header .subtitle {
            font-size: 0.875rem;
            opacity: 0.75;
            font-style: italic;
            line-height: 1.4;
        }

        .hamburger-btn {
            display: none;
            background: none;
            border: none;
            color: #ffffff;
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            line-height: 1;
            border-radius: var(--radius-sm);
            transition: background var(--transition-fast);
        }

        .hamburger-btn:hover {
            background: rgba(255,255,255,0.1);
        }

        .download-offline-btn {
            color: #ffffff;
            text-decoration: none;
            font-size: 0.8rem;
            padding: 0.3rem 0.7rem;
            border: 1px solid rgba(255,255,255,0.4);
            border-radius: 4px;
            white-space: nowrap;
            opacity: 0.85;
            transition: opacity 0.2s, background 0.2s;
        }
        .download-offline-btn:hover {
            opacity: 1;
            background: rgba(255,255,255,0.1);
        }

        /* ================================================================
           LAYOUT: SIDEBAR + MAIN
           ================================================================ */
        .app-layout {
            display: flex;
            min-height: calc(100vh - 80px);
        }

        /* ================================================================
           SIDEBAR
           ================================================================ */
        .sidebar {
            width: var(--sidebar-width);
            min-width: var(--sidebar-width);
            background: var(--color-card);
            border-right: 1px solid var(--color-border);
            overflow-y: auto;
            position: sticky;
            top: 0;
            height: 100vh;
            padding: 0;
            z-index: 50;
            -webkit-overflow-scrolling: touch;
        }

        .sidebar-inner {
            padding: 1rem 0;
        }

        .sidebar-section {
            margin-bottom: 0.25rem;
        }

        .sidebar-heading {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--color-text-muted);
            padding: 1rem 1.25rem 0.4rem;
            user-select: none;
        }

        .sidebar-list {
            list-style: none;
        }

        .sidebar-list li {
            position: relative;
        }

        .sidebar-link {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.4rem 1.25rem;
            color: var(--color-text);
            font-size: 0.875rem;
            text-decoration: none;
            border-left: 3px solid transparent;
            transition: background var(--transition-fast), border-color var(--transition-fast);
            cursor: pointer;
            user-select: none;
        }

        .sidebar-link:hover {
            background: var(--color-bg);
            color: var(--color-text);
        }

        .sidebar-link.active {
            background: var(--color-blue-light);
            color: var(--color-blue-hover);
            border-left-color: var(--color-blue);
            font-weight: 600;
        }

        .sidebar-link .count {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            font-weight: 600;
            color: var(--color-text-muted);
            background: var(--color-bg);
            padding: 0.1rem 0.45rem;
            border-radius: 10px;
            min-width: 1.6rem;
            text-align: center;
            flex-shrink: 0;
            margin-left: 0.5rem;
        }

        .sidebar-link.active .count {
            background: rgba(52,152,219,0.15);
            color: var(--color-blue-hover);
        }

        /* Expandable principle groups */
        .sidebar-link .expand-icon {
            display: inline-block;
            width: 1em;
            font-size: 0.65em;
            margin-right: 0.35em;
            transition: transform var(--transition-fast);
            flex-shrink: 0;
            text-align: center;
        }

        .sidebar-link .expand-icon.open {
            transform: rotate(90deg);
        }

        .sidebar-link .label {
            flex: 1;
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .sub-list {
            list-style: none;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }

        .sub-list.open {
            max-height: 2000px;
        }

        .sub-list .sidebar-link {
            padding-left: 2.5rem;
            font-size: 0.82rem;
            color: var(--color-text-secondary);
        }

        .sub-list .sidebar-link:hover {
            color: var(--color-text);
        }

        .sub-list .sidebar-link.active {
            color: var(--color-blue-hover);
        }

        .sidebar-divider {
            border: none;
            border-top: 1px solid var(--color-border-light);
            margin: 0.5rem 1.25rem;
        }

        /* ================================================================
           MOBILE SIDEBAR OVERLAY
           ================================================================ */
        .sidebar-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.4);
            z-index: 40;
            opacity: 0;
            transition: opacity var(--transition-normal);
        }

        .sidebar-overlay.visible {
            opacity: 1;
        }

        /* ================================================================
           MAIN CONTENT
           ================================================================ */
        .main-content {
            flex: 1;
            min-width: 0;
            padding: 2rem;
        }

        /* ================================================================
           LOADING STATE
           ================================================================ */
        .loading-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 4rem 2rem;
            text-align: center;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--color-border);
            border-top-color: var(--color-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-bottom: 1.25rem;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loading-container p {
            color: var(--color-text-secondary);
            font-size: 0.95rem;
        }

        .loading-error {
            color: var(--color-error);
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: var(--radius-md);
            padding: 1rem 1.5rem;
            margin-top: 1rem;
            font-size: 0.9rem;
        }

        /* ================================================================
           SEARCH
           ================================================================ */
        .search-wrapper {
            position: relative;
            margin-bottom: 1.5rem;
        }

        .search-icon {
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--color-text-muted);
            pointer-events: none;
            font-size: 0.95rem;
        }

        .search-input {
            width: 100%;
            padding: 0.75rem 1rem 0.75rem 2.75rem;
            font-size: 0.95rem;
            font-family: Georgia, 'Times New Roman', Times, serif;
            border: 2px solid var(--color-border);
            border-radius: var(--radius-md);
            background: var(--color-card);
            color: var(--color-text);
            transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
            outline: none;
        }

        .search-input:focus {
            border-color: var(--color-blue);
            box-shadow: 0 0 0 3px rgba(52,152,219,0.15);
        }

        .search-input::placeholder {
            color: var(--color-text-muted);
        }

        .search-clear {
            position: absolute;
            right: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            color: var(--color-text-muted);
            cursor: pointer;
            font-size: 1.1rem;
            padding: 0.25rem;
            line-height: 1;
            display: none;
        }

        .search-clear:hover {
            color: var(--color-text);
        }

        /* Search snippet (body-text match excerpt) */
        .article-card-snippet {
            font-size: 0.85rem;
            color: var(--color-text-secondary);
            margin-top: 0.35rem;
            line-height: 1.5;
            font-style: italic;
        }

        .search-highlight {
            background: #fef08a;
            color: var(--color-text);
            font-weight: 600;
            font-style: normal;
            padding: 0.05rem 0.15rem;
            border-radius: 2px;
        }

        .search-highlight.current {
            background: #f59e0b;
            outline: 2px solid #d97706;
        }

        .highlight-nav {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 1rem;
            margin-bottom: 1rem;
            background: #fef9e7;
            border: 1px solid #f9e79f;
            border-radius: var(--radius-md);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.82rem;
            color: var(--color-text-secondary);
        }

        .highlight-nav-info { flex: 1; }

        .highlight-nav-btn {
            background: none;
            border: 1px solid var(--color-border);
            border-radius: var(--radius-sm);
            padding: 0.2rem 0.6rem;
            cursor: pointer;
            font-size: 0.8rem;
            color: var(--color-text-secondary);
        }

        .highlight-nav-btn:hover { background: var(--color-bg); }

        .highlight-nav-close {
            background: none;
            border: none;
            cursor: pointer;
            color: var(--color-text-muted);
            font-size: 1rem;
            padding: 0.1rem 0.3rem;
        }

        .search-loading-indicator {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            color: var(--color-text-muted);
            text-align: center;
            padding: 0.5rem 0;
            display: none;
        }

        /* Date range filter */
        .date-range-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.4rem 1.25rem;
        }

        .date-range-row label {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            color: var(--color-text-secondary);
            min-width: 2.5rem;
        }

        .date-range-row select {
            flex: 1;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            padding: 0.3rem 0.4rem;
            border: 1px solid var(--color-border);
            border-radius: var(--radius-sm);
            background: var(--color-card);
            color: var(--color-text);
            cursor: pointer;
        }

        .date-range-row select:focus {
            outline: none;
            border-color: var(--color-blue);
        }

        .date-range-clear {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.75rem;
            color: var(--color-text-muted);
            cursor: pointer;
            padding: 0.2rem 1.25rem;
            display: none;
        }

        .date-range-clear:hover {
            color: var(--color-error);
        }

        /* ================================================================
           RESULTS SUMMARY
           ================================================================ */
        .results-summary {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.85rem;
            color: var(--color-text-secondary);
            margin-bottom: 1rem;
            padding: 0.5rem 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .results-summary .active-filter {
            background: var(--color-blue-light);
            color: var(--color-blue-hover);
            padding: 0.2rem 0.6rem;
            border-radius: var(--radius-sm);
            font-weight: 600;
        }

        .results-summary .clear-filter {
            font-size: 0.8rem;
            cursor: pointer;
            color: var(--color-text-muted);
            margin-left: 0.5rem;
        }

        .results-summary .clear-filter:hover {
            color: var(--color-error);
        }

        /* Sort select */
        .sort-select {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            padding: 0.25rem 0.5rem;
            border: 1px solid var(--color-border);
            border-radius: var(--radius-sm);
            background: var(--color-card);
            color: var(--color-text-secondary);
            cursor: pointer;
            flex-shrink: 0;
        }

        .sort-select:focus {
            outline: none;
            border-color: var(--color-blue);
        }

        /* Active filter chips */
        .filter-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            align-items: center;
        }

        .filter-chip {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            font-size: 0.78rem;
            background: var(--color-blue-light);
            color: var(--color-blue-hover);
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-weight: 600;
            white-space: nowrap;
        }

        .filter-chip-remove {
            background: none;
            border: none;
            color: var(--color-blue-hover);
            cursor: pointer;
            font-size: 0.9rem;
            line-height: 1;
            padding: 0;
            opacity: 0.6;
            transition: opacity var(--transition-fast);
        }

        .filter-chip-remove:hover {
            opacity: 1;
        }

        .filter-chips .clear-all-link {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.75rem;
            color: var(--color-text-muted);
            cursor: pointer;
            margin-left: 0.25rem;
        }

        .filter-chips .clear-all-link:hover {
            color: var(--color-error);
        }

        /* ================================================================
           ARTICLE CARDS (LIST VIEW)
           ================================================================ */
        .article-list {
            list-style: none;
        }

        .article-card {
            background: var(--color-card);
            border-radius: var(--radius-md);
            padding: 1.25rem 1.5rem;
            margin-bottom: 0.75rem;
            box-shadow: var(--shadow-sm);
            cursor: pointer;
            transition: box-shadow var(--transition-normal), transform var(--transition-normal);
            border: 1px solid var(--color-border-light);
        }

        .article-card:hover {
            box-shadow: var(--shadow-md);
            transform: translateY(-1px);
        }

        .article-card-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--color-navy);
            margin-bottom: 0.35rem;
            line-height: 1.35;
        }

        .article-card-meta {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            color: var(--color-text-secondary);
            margin-bottom: 0.5rem;
        }

        .article-card-meta .sep {
            margin: 0 0.4rem;
            color: var(--color-text-muted);
        }

        .article-card-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
        }

        /* ================================================================
           TAGS
           ================================================================ */
        .tag {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            font-weight: 600;
            padding: 0.15rem 0.5rem;
            border-radius: var(--radius-sm);
            white-space: nowrap;
            display: inline-block;
        }

        .tag-principle {
            background: var(--color-tag-principle-bg);
            color: var(--color-tag-principle-text);
        }

        .tag-application {
            background: var(--color-tag-application-bg);
            color: var(--color-tag-application-text);
        }

        .tag-keyword {
            background: var(--color-tag-keyword-bg);
            color: var(--color-tag-keyword-text);
        }

        .tag-clickable {
            cursor: pointer;
            transition: opacity var(--transition-fast);
        }

        .tag-clickable:hover {
            opacity: 0.8;
        }

        /* ================================================================
           NO RESULTS
           ================================================================ */
        .no-results {
            text-align: center;
            padding: 3rem 2rem;
            color: var(--color-text-secondary);
        }

        .no-results h3 {
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
            color: var(--color-text);
        }

        .no-results p {
            font-size: 0.9rem;
        }

        /* ================================================================
           PAGINATION
           ================================================================ */
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 1rem;
            padding: 1.75rem 0 0.5rem;
        }

        .pagination-btn {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.85rem;
            font-weight: 600;
            background: var(--color-blue);
            color: #ffffff;
            border: none;
            padding: 0.5rem 1.25rem;
            border-radius: var(--radius-md);
            cursor: pointer;
            transition: background var(--transition-fast);
        }

        .pagination-btn:hover:not(:disabled) {
            background: var(--color-blue-hover);
        }

        .pagination-btn:disabled {
            background: var(--color-border);
            color: var(--color-text-muted);
            cursor: default;
        }

        .pagination-info {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.85rem;
            color: var(--color-text-secondary);
        }

        /* ================================================================
           ARTICLE DETAIL VIEW
           ================================================================ */
        .article-detail {
            display: none;
        }

        .article-detail.active {
            display: block;
            overflow-x: hidden;
        }

        .back-btn {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            margin-bottom: 1.25rem;
            color: var(--color-blue);
            cursor: pointer;
            font-size: 0.9rem;
            background: none;
            border: none;
            padding: 0.35rem 0;
            font-weight: 500;
        }

        .back-btn:hover {
            color: var(--color-blue-hover);
            text-decoration: underline;
        }

        .article-detail-header {
            border-bottom: 2px solid var(--color-border);
            padding-bottom: 1.25rem;
            margin-bottom: 1.5rem;
        }

        .article-detail-header h1 {
            font-size: 1.75rem;
            color: var(--color-navy);
            margin-bottom: 0.5rem;
            line-height: 1.25;
        }

        .article-detail-meta {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.9rem;
            color: var(--color-text-secondary);
            margin-bottom: 0.75rem;
        }

        .article-detail-meta .reprint-note {
            font-style: italic;
            color: var(--color-text-muted);
        }

        .article-detail-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }

        .article-detail-tags .tag {
            font-size: 0.75rem;
            padding: 0.2rem 0.6rem;
        }

        /* Article body content */
        .article-body {
            background: var(--color-card);
            padding: 2.5rem;
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--color-border-light);
        }

        .article-body h1 {
            font-size: 1.5rem;
            margin: 2rem 0 1rem;
            color: var(--color-navy);
        }

        .article-body h2 {
            font-size: 1.25rem;
            margin: 1.75rem 0 0.75rem;
            color: var(--color-navy);
        }

        .article-body h3 {
            font-size: 1.1rem;
            margin: 1.5rem 0 0.5rem;
            color: var(--color-navy);
        }

        .article-body p {
            margin-bottom: 1rem;
            text-align: justify;
            text-justify: inter-word;
            hyphens: auto;
            -webkit-hyphens: auto;
        }

        .article-body blockquote {
            border-left: 3px solid var(--color-blue);
            padding: 0.75rem 1.25rem;
            margin: 1.25rem 0;
            background: var(--color-bg);
            color: var(--color-text-secondary);
            font-style: italic;
            border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        }

        .article-body blockquote p:last-child {
            margin-bottom: 0;
        }

        .article-body em {
            font-style: italic;
        }

        .article-body strong {
            font-weight: 700;
        }

        .article-body hr {
            margin: 2rem 0;
            border: none;
            border-top: 1px solid var(--color-border);
        }

        .article-body ul, .article-body ol {
            margin: 1rem 0;
            padding-left: 2rem;
        }

        .article-body li {
            margin-bottom: 0.4rem;
        }

        .article-body .smallcaps {
            font-variant: small-caps;
        }

        /* Detail header layout */
        .detail-header-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
        }

        .detail-header-top h1 {
            flex: 1;
        }

        .detail-actions {
            display: flex;
            gap: 0.5rem;
            flex-shrink: 0;
            margin-top: 0.25rem;
        }

        .detail-action-btn {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            font-weight: 600;
            background: var(--color-bg);
            border: 1px solid var(--color-border);
            border-radius: var(--radius-sm);
            padding: 0.35rem 0.7rem;
            cursor: pointer;
            color: var(--color-text-secondary);
            transition: all var(--transition-fast);
            white-space: nowrap;
        }

        .detail-action-btn:hover {
            background: var(--color-border-light);
            color: var(--color-text);
        }

        .detail-action-btn.saved {
            color: #f59e0b;
            border-color: #f59e0b;
        }

        /* Save star in list view cards */
        .article-card-save {
            position: absolute;
            top: 0.75rem;
            right: 0.75rem;
            background: none;
            border: none;
            cursor: pointer;
            font-size: 1.1rem;
            color: var(--color-text-muted);
            padding: 0.15rem;
            line-height: 1;
            transition: color var(--transition-fast);
            z-index: 2;
        }

        .article-card-save:hover {
            color: #f59e0b;
        }

        .article-card-save.saved {
            color: #f59e0b;
        }

        .article-card {
            position: relative;
        }

        /* Citation modal */
        .cite-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.4);
            z-index: 200;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .cite-modal {
            background: var(--color-card);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-lg);
            padding: 1.5rem;
            max-width: 560px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }

        .cite-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--color-navy);
        }

        .cite-modal-close {
            background: none;
            border: none;
            font-size: 1.3rem;
            cursor: pointer;
            color: var(--color-text-muted);
            padding: 0.15rem 0.35rem;
            line-height: 1;
        }

        .cite-modal-close:hover {
            color: var(--color-text);
        }

        .cite-format-label {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--color-text-muted);
            margin-bottom: 0.35rem;
        }

        .cite-text {
            font-size: 0.88rem;
            line-height: 1.6;
            background: var(--color-bg);
            border: 1px solid var(--color-border-light);
            border-radius: var(--radius-sm);
            padding: 0.75rem 1rem;
            margin-bottom: 0.6rem;
            user-select: all;
        }

        .cite-text-mono {
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 0.78rem;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .cite-copy-btn {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.78rem;
            font-weight: 600;
            background: var(--color-blue);
            color: #fff;
            border: none;
            border-radius: var(--radius-sm);
            padding: 0.3rem 0.8rem;
            cursor: pointer;
            transition: background var(--transition-fast);
            margin-bottom: 0.75rem;
        }

        .cite-copy-btn:hover {
            background: var(--color-blue-hover);
        }

        .cite-bibtex-details {
            margin-top: 0.25rem;
        }

        .cite-bibtex-details summary {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.78rem;
            color: var(--color-text-secondary);
            cursor: pointer;
            user-select: none;
            margin-bottom: 0.35rem;
        }

        /* Toast notification */
        .toast {
            position: fixed;
            bottom: 2rem;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: var(--color-navy);
            color: #fff;
            padding: 0.6rem 1.25rem;
            border-radius: var(--radius-md);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.85rem;
            box-shadow: var(--shadow-lg);
            z-index: 300;
            opacity: 0;
            transition: transform 0.3s ease, opacity 0.3s ease;
            pointer-events: none;
        }

        .toast.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }

        /* Article navigation (prev/next) */
        .article-nav {
            display: flex;
            gap: 1rem;
            margin-top: 2rem;
            padding-top: 1.25rem;
            border-top: 1px solid var(--color-border);
        }

        .article-nav-btn {
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 0.75rem 1rem;
            border: 1px solid var(--color-border);
            border-radius: var(--radius-md);
            cursor: pointer;
            transition: background var(--transition-fast), border-color var(--transition-fast);
            text-decoration: none;
            color: inherit;
        }

        .article-nav-btn:hover {
            background: var(--color-bg);
            border-color: var(--color-blue);
            color: inherit;
        }

        .article-nav-btn.disabled {
            opacity: 0.3;
            pointer-events: none;
        }

        .article-nav-next {
            text-align: right;
        }

        .article-nav-dir {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--color-blue);
            margin-bottom: 0.2rem;
        }

        .article-nav-title {
            font-size: 0.85rem;
            color: var(--color-text-secondary);
            line-height: 1.3;
        }

        /* Issue articles section */
        .issue-articles-section {
            margin-top: 1.5rem;
            border: 1px solid var(--color-border-light);
            border-radius: var(--radius-md);
            background: var(--color-card);
        }

        .issue-articles-heading {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--color-text-secondary);
            padding: 0.75rem 1rem;
            cursor: pointer;
            user-select: none;
        }

        .issue-articles-list {
            list-style: none;
            border-top: 1px solid var(--color-border-light);
        }

        .issue-articles-list li {
            border-bottom: 1px solid var(--color-border-light);
        }

        .issue-articles-list li:last-child {
            border-bottom: none;
        }

        .issue-articles-list a {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 1rem;
            font-size: 0.85rem;
            color: var(--color-text);
            text-decoration: none;
            transition: background var(--transition-fast);
        }

        .issue-articles-list a:hover {
            background: var(--color-bg);
            color: var(--color-text);
        }

        .issue-article-author {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.75rem;
            color: var(--color-text-muted);
            flex-shrink: 0;
            margin-left: 0.75rem;
        }

        /* Related articles section */
        .related-articles-section {
            margin-top: 1.5rem;
        }

        .related-articles-heading {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--color-text-muted);
            margin-bottom: 0.6rem;
        }

        .related-articles-list {
            list-style: none;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 0.6rem;
        }

        .related-article-card {
            border: 1px solid var(--color-border-light);
            border-radius: var(--radius-md);
            padding: 0.75rem 1rem;
            cursor: pointer;
            transition: background var(--transition-fast), border-color var(--transition-fast);
        }

        .related-article-card:hover {
            background: var(--color-bg);
            border-color: var(--color-blue);
        }

        .related-article-title {
            font-size: 0.88rem;
            font-weight: 600;
            color: var(--color-navy);
            line-height: 1.3;
            margin-bottom: 0.2rem;
        }

        .related-article-meta {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.72rem;
            color: var(--color-text-muted);
            margin-bottom: 0.3rem;
        }

        .related-article-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.25rem;
        }

        .related-article-tags .tag {
            font-size: 0.62rem;
            padding: 0.1rem 0.4rem;
        }

        /* Issue TOC header */
        .issue-toc-header {
            background: var(--color-navy);
            color: #fff;
            padding: 1rem 1.5rem;
            border-radius: var(--radius-md);
            margin-bottom: 1rem;
        }

        .issue-toc-header h2 {
            font-size: 1.1rem;
            font-weight: 400;
            margin-bottom: 0.15rem;
        }

        .issue-toc-header .issue-toc-sub {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.8rem;
            opacity: 0.75;
        }

        /* Keywords section at bottom of article */
        .article-keywords {
            margin-top: 2rem;
            padding-top: 1.25rem;
            border-top: 1px solid var(--color-border);
        }

        .article-keywords-label {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--color-text-muted);
            margin-bottom: 0.5rem;
        }

        .article-keywords-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }

        /* ================================================================
           ARTICLE LOADING
           ================================================================ */
        .article-loading {
            text-align: center;
            padding: 3rem;
            color: var(--color-text-secondary);
        }

        .article-loading .spinner {
            margin: 0 auto 1rem;
        }

        /* ================================================================
           FOOTER
           ================================================================ */
        .site-footer {
            text-align: center;
            padding: 2rem;
            color: var(--color-text-muted);
            font-size: 0.8rem;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            border-top: 1px solid var(--color-border-light);
            margin-top: 2rem;
        }

        /* ================================================================
           NOSCRIPT
           ================================================================ */
        .noscript-message {
            max-width: 600px;
            margin: 4rem auto;
            padding: 2rem;
            text-align: center;
            background: var(--color-card);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-md);
        }

        .noscript-message h2 {
            margin-bottom: 1rem;
            color: var(--color-navy);
        }

        .noscript-message p {
            color: var(--color-text-secondary);
        }

        /* ================================================================
           SEARCH OPTIONS (expandable below search bar)
           ================================================================ */
        .search-options {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease, opacity 0.2s ease;
            opacity: 0;
        }

        .search-options.visible {
            max-height: 200px;
            opacity: 1;
        }

        .search-modes {
            display: flex;
            gap: 0.35rem;
            margin: 0.6rem 0;
        }

        .search-mode-pill {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.7rem;
            padding: 0.25rem 0.6rem;
            border: 1px solid var(--color-border);
            border-radius: 999px;
            background: var(--color-bg);
            color: var(--color-text-secondary);
            cursor: pointer;
            transition: all var(--transition-fast);
        }

        .search-mode-pill.active {
            background: var(--color-blue);
            color: #ffffff;
            border-color: var(--color-blue);
        }

        .search-mode-pill:hover:not(.active) {
            background: var(--color-border-light);
        }

        .search-fields {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.15rem 0.6rem;
            margin-bottom: 0.5rem;
            font-size: 0.72rem;
            color: var(--color-text-secondary);
        }

        .search-fields-label {
            font-weight: 600;
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--color-text-muted);
        }

        .search-fields label {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            cursor: pointer;
            user-select: none;
        }

        .search-fields input[type="checkbox"] {
            margin: 0;
            accent-color: var(--color-blue);
        }

        .search-tips {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 0.72rem;
            color: var(--color-text-muted);
            margin-bottom: 0.4rem;
        }

        .search-tips summary { cursor: pointer; user-select: none; }

        .search-tips ul {
            margin-top: 0.35rem;
            padding-left: 1.2rem;
            line-height: 1.7;
        }

        .search-tips code {
            background: var(--color-bg);
            padding: 0.1rem 0.3rem;
            border-radius: 3px;
            font-size: 0.7rem;
        }

        /* ================================================================
           SPLIT VIEW (results list + article reading pane)
           ================================================================ */
        .main-content.split-view {
            display: flex;
            padding: 0;
        }

        .main-content.split-view #list-view {
            width: 380px;
            min-width: 380px;
            border-right: 1px solid var(--color-border);
            padding: 1.25rem;
            position: sticky;
            top: 0;
            height: 100vh;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            flex-shrink: 0;
        }

        .main-content.split-view .article-detail.active {
            flex: 1;
            min-width: 0;
            padding: 2rem;
            overflow-y: auto;
            height: 100vh;
            position: sticky;
            top: 0;
        }

        .article-card.active-reading {
            background: var(--color-blue-light);
            border-left: 3px solid var(--color-blue);
            transform: none;
            box-shadow: var(--shadow-sm);
        }

        .main-content.split-view .search-options.visible {
            max-height: 0;
            opacity: 0;
        }

        .main-content.split-view .article-body {
            padding: 1.75rem;
        }

        .main-content.split-view .article-card-tags {
            display: none;
        }

        .main-content.split-view .article-card {
            padding: 0.85rem 1rem;
            margin-bottom: 0.5rem;
        }

        .main-content.split-view .article-card-title {
            font-size: 0.95rem;
        }

        .main-content.split-view .article-card-meta {
            font-size: 0.75rem;
        }

        .main-content.split-view .issue-toc-header {
            padding: 0.75rem 1rem;
            margin-bottom: 0.75rem;
        }

        .main-content.split-view .issue-toc-header h2 {
            font-size: 0.95rem;
        }

        /* ================================================================
           RESPONSIVE: TABLET
           ================================================================ */
        @media (max-width: 1024px) {
            .main-content {
                padding: 1.5rem;
            }

            .article-body {
                padding: 1.75rem;
            }
        }

        /* ================================================================
           RESPONSIVE: SPLIT VIEW COLLAPSE
           ================================================================ */
        @media (max-width: 900px) {
            .main-content.split-view {
                display: block;
                padding: 1rem;
            }

            .main-content.split-view #list-view {
                display: none !important;
            }

            .main-content.split-view .article-detail.active {
                height: auto;
                position: static;
                overflow-y: visible;
                padding: 0;
            }
        }

        /* ================================================================
           RESPONSIVE: MOBILE
           ================================================================ */
        @media (max-width: 768px) {
            .hamburger-btn {
                display: block;
            }

            .sidebar {
                position: fixed;
                top: 0;
                left: 0;
                height: 100vh;
                z-index: 50;
                transform: translateX(-100%);
                transition: transform var(--transition-normal);
                box-shadow: none;
            }

            .sidebar.open {
                transform: translateX(0);
                box-shadow: var(--shadow-lg);
            }

            .sidebar-overlay {
                display: block;
            }

            .site-header h1 {
                font-size: 1.15rem;
            }

            .site-header .subtitle {
                display: none;
            }

            .main-content {
                padding: 1rem;
            }

            .article-body {
                padding: 1.25rem;
            }

            .article-detail-header h1 {
                font-size: 1.35rem;
            }

            .article-card {
                padding: 1rem 1.15rem;
            }

            .detail-header-top {
                flex-direction: column;
                gap: 0.5rem;
            }

            .detail-actions {
                flex-wrap: wrap;
            }
        }

        /* ================================================================
           PRINT STYLES
           ================================================================ */
        @media print {
            .sidebar,
            .sidebar-overlay,
            .hamburger-btn,
            .download-offline-btn,
            .search-wrapper,
            .pagination,
            .back-btn,
            .results-summary,
            .highlight-nav,
            .site-header .back-link {
                display: none !important;
            }

            .search-highlight {
                background: none !important;
                font-weight: inherit !important;
                padding: 0 !important;
                outline: none !important;
            }

            .cite-modal-overlay,
            .toast,
            .article-nav,
            .issue-articles-section,
            .related-articles-section,
            .detail-actions,
            .sort-select,
            #filter-chips-bar,
            #saved-section {
                display: none !important;
            }

            .site-header {
                background: none;
                color: var(--color-text);
                box-shadow: none;
                padding: 1rem 0;
                border-bottom: 2px solid #000;
            }

            .app-layout {
                display: block;
            }

            .main-content {
                max-width: 100%;
                padding: 0;
            }

            .article-body {
                box-shadow: none;
                border: none;
                padding: 0;
            }

            .article-card {
                box-shadow: none;
                border: 1px solid #ccc;
                break-inside: avoid;
            }

            .main-content.split-view #list-view {
                display: none !important;
            }

            .main-content.split-view .article-detail.active {
                height: auto;
                position: static;
                overflow-y: visible;
            }
        }

        /* ================================================================
           ACCESSIBILITY
           ================================================================ */
        .sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0,0,0,0);
            white-space: nowrap;
            border: 0;
        }

        :focus-visible {
            outline: 2px solid var(--color-blue);
            outline-offset: 2px;
        }

        .sidebar-link:focus-visible,
        .article-card:focus-visible {
            outline: 2px solid var(--color-blue);
            outline-offset: -2px;
        }
    </style>
</head>
<body>
    <!-- No-JavaScript fallback -->
    <noscript>
        <div class="noscript-message">
            <h2>JavaScript Required</h2>
            <p>The American Sentinel Research Archive requires JavaScript to browse and search the article catalog. Please enable JavaScript in your browser settings and reload this page.</p>
        </div>
    </noscript>

    <div class="app-root">
        <!-- ============================================================
             HEADER
             ============================================================ -->
        <header class="site-header" role="banner">
            <div class="site-header-inner">
                <div>
                    <a href="https://americansentinel.org" class="back-link">&larr; americansentinel.org</a>
                    <h1>American Sentinel Research Archive</h1>
                    <p class="subtitle">Historical writings on religious liberty and church-state separation, 1886&ndash;1900</p>
                </div>
                <a href="offline.html" download class="download-offline-btn" id="download-offline-btn" title="Download for offline use">&#11015; Offline</a>
                <button class="hamburger-btn" id="hamburger-btn" aria-label="Toggle navigation menu" aria-expanded="false">&#9776;</button>
            </div>
        </header>

        <!-- ============================================================
             APP LAYOUT
             ============================================================ -->
        <div class="app-layout">
            <!-- Sidebar overlay for mobile -->
            <div class="sidebar-overlay" id="sidebar-overlay"></div>

            <!-- Sidebar navigation -->
            <nav class="sidebar" id="sidebar" role="navigation" aria-label="Article filters">
                <div class="sidebar-inner">
                    <!-- Browse section -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Browse</div>
                        <ul class="sidebar-list">
                            <li>
                                <a class="sidebar-link active" id="nav-all" data-route="" role="button" tabindex="0">
                                    <span class="label">All Articles</span>
                                    <span class="count" id="total-count">&hellip;</span>
                                </a>
                            </li>
                        </ul>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Date Range Filter -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Date Range</div>
                        <div class="date-range-row">
                            <label for="year-from">From</label>
                            <select id="year-from"><option value="">All</option></select>
                        </div>
                        <div class="date-range-row">
                            <label for="year-to">To</label>
                            <select id="year-to"><option value="">All</option></select>
                        </div>
                        <a class="date-range-clear" id="date-range-clear" role="button" tabindex="0">Clear date range</a>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Years -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Years</div>
                        <ul class="sidebar-list" id="years-nav"></ul>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Principles -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Principles</div>
                        <ul class="sidebar-list" id="principles-nav"></ul>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Authors -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Authors</div>
                        <ul class="sidebar-list" id="authors-nav"></ul>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Article Type -->
                    <div class="sidebar-section">
                        <div class="sidebar-heading">Article Type</div>
                        <ul class="sidebar-list" id="attribution-nav"></ul>
                    </div>

                    <hr class="sidebar-divider">

                    <!-- Saved Articles -->
                    <div class="sidebar-section" id="saved-section" style="display:none">
                        <div class="sidebar-heading">Bookmarks</div>
                        <ul class="sidebar-list">
                            <li>
                                <a class="sidebar-link" id="nav-saved" data-filter-saved="true" role="button" tabindex="0">
                                    <span class="label">Saved Articles</span>
                                    <span class="count" id="saved-count">0</span>
                                </a>
                            </li>
                        </ul>
                    </div>
                </div>
            </nav>

            <!-- Main content area -->
            <main class="main-content" id="main-content" role="main">
                <!-- Loading state -->
                <div class="loading-container" id="loading-state">
                    <div class="spinner"></div>
                    <p>Loading article catalog&hellip;</p>
                </div>

                <!-- List view (search + cards + pagination) -->
                <div id="list-view" style="display:none">
                    <div class="search-wrapper">
                        <span class="search-icon" aria-hidden="true">&#128269;</span>
                        <input type="search"
                               class="search-input"
                               id="search-input"
                               placeholder="Search articles &mdash; use quotes, wildcards (*), proximity (~), field: prefixes&hellip;"
                               aria-label="Search articles">
                        <button class="search-clear" id="search-clear" aria-label="Clear search">&times;</button>
                        <div class="search-options" id="search-options">
                            <div class="search-modes" id="search-modes">
                                <button class="search-mode-pill active" data-mode="and">All Words</button>
                                <button class="search-mode-pill" data-mode="phrase">Exact Phrase</button>
                                <button class="search-mode-pill" data-mode="or">Any Word</button>
                            </div>
                            <div class="search-fields" id="search-fields">
                                <span class="search-fields-label">Search in:</span>
                                <label><input type="checkbox" value="title" checked> Title</label>
                                <label><input type="checkbox" value="author" checked> Author</label>
                                <label><input type="checkbox" value="keywords" checked> Keywords</label>
                                <label><input type="checkbox" value="categories" checked> Categories</label>
                                <label><input type="checkbox" value="body" checked> Body</label>
                            </div>
                            <details class="search-tips">
                                <summary>Search tips</summary>
                                <ul>
                                    <li>Use <code>"quotes"</code> for exact phrases</li>
                                    <li>Use <code>-word</code> to exclude a term</li>
                                    <li>Use <code>*</code> for wildcards: <code>legislat*</code></li>
                                    <li>Use <code>"word1 word2"~5</code> for proximity</li>
                                    <li>Prefix with <code>title:</code> or <code>author:</code></li>
                                </ul>
                            </details>
                        </div>
                    </div>

                    <div class="search-loading-indicator" id="search-loading">Loading full-text search index&hellip;</div>

                    <div class="results-summary" id="results-summary">
                        <span id="results-summary-text"></span>
                        <select class="sort-select" id="sort-select" aria-label="Sort articles">
                            <option value="date-desc">Date (newest first)</option>
                            <option value="date-asc">Date (oldest first)</option>
                            <option value="title-asc">Title (A&ndash;Z)</option>
                            <option value="title-desc">Title (Z&ndash;A)</option>
                        </select>
                    </div>
                    <div id="filter-chips-bar" style="display:none"></div>

                    <ul class="article-list" id="article-list" role="list"></ul>

                    <div class="pagination" id="pagination" style="display:none">
                        <button class="pagination-btn" id="prev-btn" aria-label="Previous page">&larr; Previous</button>
                        <span class="pagination-info" id="page-info"></span>
                        <button class="pagination-btn" id="next-btn" aria-label="Next page">Next &rarr;</button>
                    </div>
                </div>

                <!-- Article detail view -->
                <div class="article-detail" id="article-detail">
                    <button class="back-btn" id="detail-back-btn">&larr; Back to list</button>

                    <div class="article-detail-header">
                        <div class="detail-header-top">
                            <h1 id="detail-title"></h1>
                            <div class="detail-actions">
                                <button class="detail-action-btn" id="save-btn" aria-label="Save article" title="Save article">&#9734;</button>
                                <button class="detail-action-btn" id="cite-btn" aria-label="Cite this article" title="Cite">Cite</button>
                                <button class="detail-action-btn" id="share-btn" aria-label="Share article" title="Share">Share</button>
                                <button class="detail-action-btn" id="print-btn" aria-label="Print article" title="Print">Print</button>
                                <a class="detail-action-btn" id="pdf-btn" href="#" target="_blank" rel="noopener" aria-label="View original PDF scan" title="View Original Scan">PDF</a>
                            </div>
                        </div>
                        <div class="article-detail-meta" id="detail-meta"></div>
                        <div class="article-detail-tags" id="detail-tags"></div>
                    </div>

                    <!-- Citation modal -->
                    <div class="cite-modal-overlay" id="cite-modal-overlay" style="display:none">
                        <div class="cite-modal" id="cite-modal">
                            <div class="cite-modal-header">
                                <span>Cite This Article</span>
                                <button class="cite-modal-close" id="cite-modal-close" aria-label="Close">&times;</button>
                            </div>
                            <div class="cite-format-label">Chicago Manual of Style (17th ed.)</div>
                            <div class="cite-text" id="cite-text-chicago"></div>
                            <button class="cite-copy-btn" id="cite-copy-chicago">Copy</button>
                            <details class="cite-bibtex-details">
                                <summary>BibTeX</summary>
                                <div class="cite-text cite-text-mono" id="cite-text-bibtex"></div>
                                <button class="cite-copy-btn" id="cite-copy-bibtex">Copy</button>
                            </details>
                        </div>
                    </div>

                    <!-- Toast notification -->
                    <div class="toast" id="toast"></div>

                    <div class="highlight-nav" id="highlight-nav" style="display:none">
                        <span class="highlight-nav-info" id="highlight-nav-info"></span>
                        <button class="highlight-nav-btn" id="highlight-prev">&uarr; Prev</button>
                        <button class="highlight-nav-btn" id="highlight-next">&darr; Next</button>
                        <button class="highlight-nav-close" id="highlight-close" aria-label="Clear highlights">&times;</button>
                    </div>

                    <div class="article-body" id="detail-body">
                        <div class="article-loading">
                            <div class="spinner"></div>
                            <p>Loading article&hellip;</p>
                        </div>
                    </div>

                    <div class="article-keywords" id="detail-keywords" style="display:none">
                        <div class="article-keywords-label">Keywords</div>
                        <div class="article-keywords-list" id="detail-keywords-list"></div>
                    </div>

                    <!-- Next/Previous article navigation -->
                    <div class="article-nav" id="article-nav" style="display:none">
                        <a class="article-nav-btn article-nav-prev" id="nav-prev" role="button" tabindex="0">
                            <span class="article-nav-dir">&larr; Previous</span>
                            <span class="article-nav-title" id="nav-prev-title"></span>
                        </a>
                        <a class="article-nav-btn article-nav-next" id="nav-next" role="button" tabindex="0">
                            <span class="article-nav-dir">Next &rarr;</span>
                            <span class="article-nav-title" id="nav-next-title"></span>
                        </a>
                    </div>

                    <!-- Other articles in this issue -->
                    <details class="issue-articles-section" id="issue-articles-section" style="display:none">
                        <summary class="issue-articles-heading">Other articles in this issue</summary>
                        <ul class="issue-articles-list" id="issue-articles-list"></ul>
                    </details>

                    <!-- Related articles -->
                    <div class="related-articles-section" id="related-articles-section" style="display:none">
                        <div class="related-articles-heading">Related Articles</div>
                        <ul class="related-articles-list" id="related-articles-list"></ul>
                    </div>
                </div>
            </main>

        </div>

        <!-- Footer -->
        <footer class="site-footer">
            American Sentinel Research Archive &mdash; Preserving the words of Adventist pioneers on religious liberty
        </footer>
    </div>

    <!-- ================================================================
         JAVASCRIPT APPLICATION
         ================================================================ -->
    <script>
    (function() {
        'use strict';

        /* ============================================================
           CONFIGURATION
           ============================================================ */
        var CATALOG_URL = '{CATALOG_URL}';
        var ARTICLES_BASE = 'articles/';
        var SEARCH_DATA_URL = 'search-data.json';
        var PAGE_SIZE = 25;
        var OFFLINE_MODE = false;

        /* ============================================================
           STATE
           ============================================================ */
        var catalog = null;
        var filteredArticles = [];
        var currentPage = 0;
        var previousHash = '';

        // Index for fast lookups
        var articleById = {};

        // Full-text search data (lazy-loaded)
        var searchData = null;
        var searchDataLoading = false;
        var searchDataLoaded = false;

        // Active filter state (multi-facet)
        var activeFilter = {
            year: null,
            issue: null,
            principle: null,
            application: null,
            author: null,
            attribution: null,
            saved: false,
            yearFrom: '',
            yearTo: '',
            search: '',
            sort: 'date-desc'
        };

        // Current search query for snippet highlighting
        var currentSearchQuery = '';
        var currentArticleId = null;

        // Advanced search state (merged into main search)
        var currentSearchMode = 'and';
        var searchMatchedTerms = [];
        var searchScores = {};
        var searchFields = { title: true, author: true, keywords: true, categories: true, body: true };

        // Highlight navigation state
        var highlightMatches = [];
        var currentHighlightIndex = -1;

        // Saved articles (localStorage)
        var savedArticles = {};
        function loadSavedArticles() {
            try {
                var raw = localStorage.getItem('savedArticles');
                if (raw) {
                    var arr = JSON.parse(raw);
                    savedArticles = {};
                    for (var i = 0; i < arr.length; i++) savedArticles[arr[i]] = true;
                }
            } catch(e) { savedArticles = {}; }
        }
        function persistSavedArticles() {
            try {
                localStorage.setItem('savedArticles', JSON.stringify(Object.keys(savedArticles)));
            } catch(e) {}
        }
        function toggleSaved(articleId) {
            if (savedArticles[articleId]) {
                delete savedArticles[articleId];
            } else {
                savedArticles[articleId] = true;
            }
            persistSavedArticles();
            updateSavedCount();
        }
        function isSaved(articleId) { return !!savedArticles[articleId]; }
        function updateSavedCount() {
            var count = Object.keys(savedArticles).length;
            if (dom.savedCount) dom.savedCount.textContent = count;
            if (dom.savedSection) dom.savedSection.style.display = count > 0 ? 'block' : 'none';
        }

        /* ============================================================
           DOM REFERENCES (cached after DOMContentLoaded)
           ============================================================ */
        var dom = {};

        function cacheDom() {
            dom.loadingState = document.getElementById('loading-state');
            dom.mainContent = document.getElementById('main-content');
            dom.listView = document.getElementById('list-view');
            dom.articleDetail = document.getElementById('article-detail');
            dom.searchInput = document.getElementById('search-input');
            dom.searchClear = document.getElementById('search-clear');
            dom.searchLoading = document.getElementById('search-loading');
            dom.resultsSummary = document.getElementById('results-summary');
            dom.resultsSummaryText = document.getElementById('results-summary-text');
            dom.sortSelect = document.getElementById('sort-select');
            dom.filterChipsBar = document.getElementById('filter-chips-bar');
            dom.articleList = document.getElementById('article-list');
            dom.pagination = document.getElementById('pagination');
            dom.prevBtn = document.getElementById('prev-btn');
            dom.nextBtn = document.getElementById('next-btn');
            dom.pageInfo = document.getElementById('page-info');
            dom.totalCount = document.getElementById('total-count');
            dom.yearsNav = document.getElementById('years-nav');
            dom.principlesNav = document.getElementById('principles-nav');
            dom.authorsNav = document.getElementById('authors-nav');
            dom.attributionNav = document.getElementById('attribution-nav');
            dom.detailTitle = document.getElementById('detail-title');
            dom.detailMeta = document.getElementById('detail-meta');
            dom.detailTags = document.getElementById('detail-tags');
            dom.detailBody = document.getElementById('detail-body');
            dom.detailKeywords = document.getElementById('detail-keywords');
            dom.detailKeywordsList = document.getElementById('detail-keywords-list');
            dom.detailBackBtn = document.getElementById('detail-back-btn');
            dom.sidebar = document.getElementById('sidebar');
            dom.sidebarOverlay = document.getElementById('sidebar-overlay');
            dom.hamburgerBtn = document.getElementById('hamburger-btn');
            dom.navAll = document.getElementById('nav-all');
            dom.yearFrom = document.getElementById('year-from');
            dom.yearTo = document.getElementById('year-to');
            dom.dateRangeClear = document.getElementById('date-range-clear');

            // Search options
            dom.searchOptions = document.getElementById('search-options');
            dom.searchModes = document.getElementById('search-modes');
            dom.searchFields = document.getElementById('search-fields');

            // Highlight navigation
            dom.highlightNav = document.getElementById('highlight-nav');
            dom.highlightNavInfo = document.getElementById('highlight-nav-info');
            dom.highlightPrev = document.getElementById('highlight-prev');
            dom.highlightNext = document.getElementById('highlight-next');
            dom.highlightClose = document.getElementById('highlight-close');

            // Article detail extras
            dom.articleNav = document.getElementById('article-nav');
            dom.navPrev = document.getElementById('nav-prev');
            dom.navNext = document.getElementById('nav-next');
            dom.navPrevTitle = document.getElementById('nav-prev-title');
            dom.navNextTitle = document.getElementById('nav-next-title');
            dom.issueArticlesSection = document.getElementById('issue-articles-section');
            dom.issueArticlesList = document.getElementById('issue-articles-list');
            dom.relatedArticlesSection = document.getElementById('related-articles-section');
            dom.relatedArticlesList = document.getElementById('related-articles-list');
            dom.saveBtn = document.getElementById('save-btn');
            dom.citeBtn = document.getElementById('cite-btn');
            dom.shareBtn = document.getElementById('share-btn');
            dom.printBtn = document.getElementById('print-btn');
            dom.pdfBtn = document.getElementById('pdf-btn');
            dom.citeModalOverlay = document.getElementById('cite-modal-overlay');
            dom.citeModalClose = document.getElementById('cite-modal-close');
            dom.citeTextChicago = document.getElementById('cite-text-chicago');
            dom.citeTextBibtex = document.getElementById('cite-text-bibtex');
            dom.citeCopyChicago = document.getElementById('cite-copy-chicago');
            dom.citeCopyBibtex = document.getElementById('cite-copy-bibtex');
            dom.toast = document.getElementById('toast');

            // Saved articles
            dom.savedSection = document.getElementById('saved-section');
            dom.savedCount = document.getElementById('saved-count');
            dom.navSaved = document.getElementById('nav-saved');
        }

        /* ============================================================
           UTILITY FUNCTIONS
           ============================================================ */
        function escapeRegex(str) {
            return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function escapeHtml(str) {
            if (!str) return '';
            var div = document.createElement('div');
            div.appendChild(document.createTextNode(str));
            return div.innerHTML;
        }

        function encodeHashParam(str) {
            return encodeURIComponent(str).replace(/%20/g, '+');
        }

        function decodeHashParam(str) {
            return decodeURIComponent(str.replace(/\+/g, ' '));
        }

        function formatDate(dateStr) {
            if (!dateStr) return '';
            var parts = dateStr.split('-');
            var months = ['January','February','March','April','May','June',
                          'July','August','September','October','November','December'];
            var monthIdx = parseInt(parts[1], 10) - 1;
            if (monthIdx < 0 || monthIdx > 11) return dateStr;
            var year = parts[0];
            if (parts.length === 2) return months[monthIdx] + ' ' + year;
            var day = parseInt(parts[2], 10);
            return months[monthIdx] + ' ' + day + ', ' + year;
        }

        function cssEscape(str) {
            if (window.CSS && window.CSS.escape) return window.CSS.escape(str);
            return str.replace(/([^\w-])/g, '\\$1');
        }

        /* ============================================================
           DATA LOADING
           ============================================================ */
        function loadCatalog() {
            if (OFFLINE_MODE) {
                catalog = window.__OFFLINE_CATALOG;
                onCatalogLoaded();
                return;
            }
            var xhr = new XMLHttpRequest();
            xhr.open('GET', CATALOG_URL, true);
            xhr.onreadystatechange = function() {
                if (xhr.readyState !== 4) return;
                if (xhr.status === 200) {
                    try {
                        catalog = JSON.parse(xhr.responseText);
                        onCatalogLoaded();
                    } catch (e) {
                        showLoadError('Failed to parse catalog data: ' + e.message);
                    }
                } else {
                    showLoadError('Failed to load catalog (HTTP ' + xhr.status + '). Please try refreshing the page.');
                }
            };
            xhr.onerror = function() {
                showLoadError('Network error loading catalog. Please check your connection and try again.');
            };
            xhr.send();
        }

        function showLoadError(message) {
            dom.loadingState.innerHTML =
                '<div class="loading-error"><strong>Error:</strong> ' + escapeHtml(message) + '</div>';
        }

        function loadSearchData(callback) {
            if (searchDataLoaded) {
                if (callback) callback();
                return;
            }
            if (OFFLINE_MODE) {
                var articles = window.__OFFLINE_ARTICLES;
                var tmp = document.createElement('div');
                searchData = {};
                for (var aid in articles) {
                    if (articles.hasOwnProperty(aid)) {
                        tmp.innerHTML = articles[aid];
                        searchData[aid] = tmp.textContent || tmp.innerText || '';
                    }
                }
                searchDataLoaded = true;
                if (callback) callback();
                return;
            }
            if (searchDataLoading) return;
            searchDataLoading = true;
            dom.searchLoading.style.display = 'block';

            var xhr = new XMLHttpRequest();
            xhr.open('GET', SEARCH_DATA_URL, true);
            xhr.onreadystatechange = function() {
                if (xhr.readyState !== 4) return;
                searchDataLoading = false;
                dom.searchLoading.style.display = 'none';
                if (xhr.status === 200) {
                    try {
                        var data = JSON.parse(xhr.responseText);
                        searchData = {};
                        for (var i = 0; i < data.length; i++) {
                            searchData[data[i].id] = data[i].t;
                        }
                        searchDataLoaded = true;
                        if (callback) callback();
                    } catch (e) {
                        // Silently fail — metadata search still works
                    }
                }
            };
            xhr.onerror = function() {
                searchDataLoading = false;
                dom.searchLoading.style.display = 'none';
            };
            xhr.send();
        }

        var yearIssueIndex = {}; // { "1886": { "v01n01": { date, volume, issue, count }, ... }, ... }

        var MONTH_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        var MONTH_LONG = ['January','February','March','April','May','June','July','August','September','October','November','December'];

        function formatIssueLabel(issueInfo) {
            var d = issueInfo.date;
            var monthIdx = parseInt(d.substring(5, 7), 10) - 1;
            if (d.length > 7) {
                // Weekly: "Jan 1"
                var day = parseInt(d.substring(8, 10), 10);
                return MONTH_SHORT[monthIdx] + ' ' + day;
            }
            // Monthly: "January"
            return MONTH_LONG[monthIdx];
        }

        function formatIssueLabelFromDate(dateStr) {
            var monthIdx = parseInt(dateStr.substring(5, 7), 10) - 1;
            if (dateStr.length > 7) {
                var day = parseInt(dateStr.substring(8, 10), 10);
                return MONTH_SHORT[monthIdx] + ' ' + day + ', ' + dateStr.substring(0, 4);
            }
            return MONTH_LONG[monthIdx] + ' ' + dateStr.substring(0, 4);
        }

        function onCatalogLoaded() {
            // Build index
            articleById = {};
            for (var i = 0; i < catalog.articles.length; i++) {
                var a = catalog.articles[i];
                articleById[a.id] = a;
            }

            // Build year → issues index
            yearIssueIndex = {};
            for (var i = 0; i < catalog.articles.length; i++) {
                var a = catalog.articles[i];
                if (!a.date) continue;
                var year = a.date.substring(0, 4);
                var key = 'v' + (a.volume < 10 ? '0' : '') + a.volume + 'n' + (a.issue < 10 ? '0' : '') + a.issue;
                if (!yearIssueIndex[year]) yearIssueIndex[year] = {};
                if (!yearIssueIndex[year][key]) {
                    yearIssueIndex[year][key] = { date: a.date, volume: a.volume, issue: a.issue, count: 0 };
                }
                yearIssueIndex[year][key].count++;
            }

            // Set total count
            dom.totalCount.textContent = catalog.article_count;

            // Load saved articles from localStorage
            loadSavedArticles();
            updateSavedCount();

            // Build sidebar navigation
            renderYearsNav();
            renderDateRangeDropdowns();
            renderPrinciplesNav();
            renderAuthorsNav();
            renderAttributionNav();

            // Hide loading, show list
            dom.loadingState.style.display = 'none';
            dom.listView.style.display = 'block';

            // Check if initial route has a search query
            var initHash = window.location.hash.replace(/^#\/?/, '');
            var hasInitialSearch = initHash.indexOf('search') !== -1;

            if (hasInitialSearch) {
                loadSearchData(function() {
                    handleRoute();
                });
            } else {
                handleRoute();
                loadSearchData(function() {
                    if (activeFilter.search) renderListView();
                });
            }
        }

        /* ============================================================
           SIDEBAR RENDERING
           ============================================================ */
        function renderYearsNav(filteredSet) {
            var years = Object.keys(yearIssueIndex).sort();
            var html = '';

            // If filteredSet provided, compute dynamic counts
            var dynYearCounts = null;
            var dynIssueCounts = null;
            if (filteredSet) {
                dynYearCounts = {};
                dynIssueCounts = {};
                for (var fi = 0; fi < filteredSet.length; fi++) {
                    var fa = filteredSet[fi];
                    if (!fa.date) continue;
                    var fy = fa.date.substring(0, 4);
                    dynYearCounts[fy] = (dynYearCounts[fy] || 0) + 1;
                    dynIssueCounts[fa.date] = (dynIssueCounts[fa.date] || 0) + 1;
                }
            }

            for (var j = 0; j < years.length; j++) {
                var y = years[j];
                var issues = yearIssueIndex[y];
                var issueKeys = Object.keys(issues).sort();
                var yearCount = dynYearCounts ? (dynYearCounts[y] || 0) : 0;
                if (!dynYearCounts) {
                    for (var k = 0; k < issueKeys.length; k++) yearCount += issues[issueKeys[k]].count;
                }

                html += '<li>';
                html += '<a class="sidebar-link" data-filter-year="' + y + '" role="button" tabindex="0">';
                html += '<span class="expand-icon" id="arrow-year-' + y + '">&#9654;</span>';
                html += '<span class="label">' + y + '</span>';
                html += '<span class="count">' + yearCount + '</span>';
                html += '</a>';

                html += '<ul class="sub-list" id="sub-year-' + y + '">';
                for (var k = 0; k < issueKeys.length; k++) {
                    var iss = issues[issueKeys[k]];
                    var issueLabel = formatIssueLabel(iss);
                    var issCount = dynIssueCounts ? (dynIssueCounts[iss.date] || 0) : iss.count;
                    html += '<li><a class="sidebar-link" data-filter-issue="' + iss.date + '" role="button" tabindex="0">';
                    html += '<span class="label">' + issueLabel + '</span>';
                    html += '<span class="count">' + issCount + '</span>';
                    html += '</a></li>';
                }
                html += '</ul>';
                html += '</li>';
            }
            dom.yearsNav.innerHTML = html;
        }

        function renderDateRangeDropdowns() {
            var years = [];
            var seen = {};
            for (var i = 0; i < catalog.articles.length; i++) {
                var d = catalog.articles[i].date;
                if (d) {
                    var y = d.substring(0, 4);
                    if (!seen[y]) {
                        seen[y] = true;
                        years.push(y);
                    }
                }
            }
            years.sort();

            var fromHtml = '<option value="">All</option>';
            var toHtml = '<option value="">All</option>';
            for (var j = 0; j < years.length; j++) {
                fromHtml += '<option value="' + years[j] + '">' + years[j] + '</option>';
                toHtml += '<option value="' + years[j] + '">' + years[j] + '</option>';
            }
            dom.yearFrom.innerHTML = fromHtml;
            dom.yearTo.innerHTML = toHtml;
        }

        function renderPrinciplesNav(filteredSet) {
            var articles = filteredSet || catalog.articles;
            var principleCounts = {};
            var appCounts = {};

            for (var i = 0; i < articles.length; i++) {
                var a = articles[i];
                var ps = a.principles || [];
                for (var p = 0; p < ps.length; p++) {
                    principleCounts[ps[p]] = (principleCounts[ps[p]] || 0) + 1;
                }
                var apps = a.applications || [];
                for (var ap = 0; ap < apps.length; ap++) {
                    appCounts[apps[ap]] = (appCounts[apps[ap]] || 0) + 1;
                }
            }

            var principles = catalog.taxonomy.principles || [];
            var appsByPrinciple = catalog.taxonomy.applications || {};
            var html = '';

            for (var pi = 0; pi < principles.length; pi++) {
                var principle = principles[pi];
                var count = principleCounts[principle] || 0;
                if (count === 0 && !filteredSet) continue;

                var subApps = appsByPrinciple[principle] || [];
                var activeApps = [];
                for (var sa = 0; sa < subApps.length; sa++) {
                    if (appCounts[subApps[sa]] || filteredSet) {
                        activeApps.push(subApps[sa]);
                    }
                }

                var hasChildren = activeApps.length > 0;
                var arrowHtml = hasChildren
                    ? '<span class="expand-icon" id="arrow-' + cssEscape(principle) + '">&#9654;</span>'
                    : '';

                html += '<li>';
                html += '<a class="sidebar-link" data-filter-principle="' + escapeHtml(principle) + '" role="button" tabindex="0">' +
                    arrowHtml +
                    '<span class="label">' + escapeHtml(principle) + '</span>' +
                    '<span class="count">' + count + '</span></a>';

                if (hasChildren) {
                    html += '<ul class="sub-list" id="sub-' + cssEscape(principle) + '">';
                    for (var ai = 0; ai < activeApps.length; ai++) {
                        var app = activeApps[ai];
                        var ac = appCounts[app] || 0;
                        html += '<li><a class="sidebar-link" data-filter-application="' + escapeHtml(app) + '" role="button" tabindex="0">' +
                            '<span class="label">' + escapeHtml(app) + '</span>' +
                            '<span class="count">' + ac + '</span></a></li>';
                    }
                    html += '</ul>';
                }
                html += '</li>';
            }

            dom.principlesNav.innerHTML = html;
        }

        function renderAuthorsNav(filteredSet) {
            var articles = filteredSet || catalog.articles;
            var authorCounts = {};
            for (var i = 0; i < articles.length; i++) {
                var author = articles[i].author || null;
                if (author) {
                    authorCounts[author] = (authorCounts[author] || 0) + 1;
                }
            }

            var authors = Object.keys(authorCounts).sort();
            var html = '';
            for (var j = 0; j < authors.length; j++) {
                var a = authors[j];
                html += '<li><a class="sidebar-link" data-filter-author="' + escapeHtml(a) + '" role="button" tabindex="0">' +
                    '<span class="label">' + escapeHtml(a) + '</span>' +
                    '<span class="count">' + authorCounts[a] + '</span></a></li>';
            }
            dom.authorsNav.innerHTML = html;
        }

        function renderAttributionNav(filteredSet) {
            var articles = filteredSet || catalog.articles;
            var counts = { editorial: 0, explicit: 0, reprint: 0 };
            for (var i = 0; i < articles.length; i++) {
                var attr = articles[i].attribution || '';
                if (counts[attr] !== undefined) counts[attr]++;
            }

            var labels = { editorial: 'Editorial', explicit: 'Signed Articles', reprint: 'Reprints' };
            var html = '';
            var types = ['editorial', 'explicit', 'reprint'];
            for (var t = 0; t < types.length; t++) {
                html += '<li><a class="sidebar-link" data-filter-attribution="' + types[t] + '" role="button" tabindex="0">' +
                    '<span class="label">' + labels[types[t]] + '</span>' +
                    '<span class="count">' + counts[types[t]] + '</span></a></li>';
            }
            dom.attributionNav.innerHTML = html;
        }

        /* ============================================================
           SIDEBAR INTERACTIONS
           ============================================================ */
        function updateSidebarActive() {
            var links = document.querySelectorAll('.sidebar-link');
            for (var i = 0; i < links.length; i++) {
                links[i].classList.remove('active');
            }

            var hasAny = activeFilter.year || activeFilter.issue || activeFilter.principle ||
                         activeFilter.application || activeFilter.author || activeFilter.attribution ||
                         activeFilter.saved || activeFilter.yearFrom || activeFilter.yearTo || activeFilter.search;

            if (!hasAny) {
                dom.navAll.classList.add('active');
                return;
            }

            // Highlight active items per section
            function activateLink(attr, val) {
                if (!val) return;
                var els = document.querySelectorAll('[' + attr + '="' + val.replace(/"/g, '\\"') + '"]');
                for (var j = 0; j < els.length; j++) els[j].classList.add('active');
            }

            activateLink('data-filter-year', activeFilter.year);
            activateLink('data-filter-issue', activeFilter.issue);
            activateLink('data-filter-principle', activeFilter.principle);
            activateLink('data-filter-application', activeFilter.application);
            activateLink('data-filter-author', activeFilter.author);
            activateLink('data-filter-attribution', activeFilter.attribution);
            if (activeFilter.saved) {
                dom.navSaved.classList.add('active');
            }
        }

        // openPrincipleGroup: always opens the group (used by handleRoute, application nav)
        function openPrincipleGroup(principle) {
            var allSubs = dom.principlesNav.querySelectorAll('.sub-list');
            var allArrows = dom.principlesNav.querySelectorAll('.expand-icon');
            for (var i = 0; i < allSubs.length; i++) allSubs[i].classList.remove('open');
            for (var j = 0; j < allArrows.length; j++) allArrows[j].classList.remove('open');

            var subList = document.getElementById('sub-' + cssEscape(principle));
            var arrow = document.getElementById('arrow-' + cssEscape(principle));
            if (subList) subList.classList.add('open');
            if (arrow) arrow.classList.add('open');
        }

        // togglePrincipleGroup: toggles open/closed (used only by same-route click handler)
        function togglePrincipleGroup(principle) {
            var subList = document.getElementById('sub-' + cssEscape(principle));
            var isOpen = subList && subList.classList.contains('open');
            if (isOpen) {
                subList.classList.remove('open');
                var arrow = document.getElementById('arrow-' + cssEscape(principle));
                if (arrow) arrow.classList.remove('open');
            } else {
                openPrincipleGroup(principle);
            }
        }

        // openYearGroup: always opens the group (used by handleRoute, issue nav)
        function openYearGroup(year) {
            var allSubs = dom.yearsNav.querySelectorAll('.sub-list');
            var allArrows = dom.yearsNav.querySelectorAll('.expand-icon');
            for (var i = 0; i < allSubs.length; i++) allSubs[i].classList.remove('open');
            for (var j = 0; j < allArrows.length; j++) allArrows[j].classList.remove('open');

            var subList = document.getElementById('sub-year-' + year);
            var arrow = document.getElementById('arrow-year-' + year);
            if (subList) subList.classList.add('open');
            if (arrow) arrow.classList.add('open');
        }

        // toggleYearGroup: toggles open/closed (used only by same-route click handler)
        function toggleYearGroup(year) {
            var subList = document.getElementById('sub-year-' + year);
            var isOpen = subList && subList.classList.contains('open');
            if (isOpen) {
                subList.classList.remove('open');
                var arrow = document.getElementById('arrow-year-' + year);
                if (arrow) arrow.classList.remove('open');
            } else {
                openYearGroup(year);
            }
        }

        function openYearForIssue(issueDate) {
            var year = issueDate.substring(0, 4);
            openYearGroup(year);
        }

        function openPrincipleGroupForApplication(appName) {
            var appsByPrinciple = catalog.taxonomy.applications || {};
            var principles = Object.keys(appsByPrinciple);
            for (var i = 0; i < principles.length; i++) {
                var apps = appsByPrinciple[principles[i]];
                for (var j = 0; j < apps.length; j++) {
                    if (apps[j] === appName) {
                        openPrincipleGroup(principles[i]);
                        return;
                    }
                }
            }
        }

        /* Mobile sidebar */
        function openSidebar() {
            dom.sidebar.classList.add('open');
            dom.sidebarOverlay.style.display = 'block';
            dom.sidebarOverlay.offsetHeight;
            dom.sidebarOverlay.classList.add('visible');
            dom.hamburgerBtn.setAttribute('aria-expanded', 'true');
            document.body.style.overflow = 'hidden';
        }

        function closeSidebar() {
            dom.sidebar.classList.remove('open');
            dom.sidebarOverlay.classList.remove('visible');
            dom.hamburgerBtn.setAttribute('aria-expanded', 'false');
            document.body.style.overflow = '';
            setTimeout(function() {
                if (!dom.sidebarOverlay.classList.contains('visible')) {
                    dom.sidebarOverlay.style.display = 'none';
                }
            }, 300);
        }

        /* ============================================================
           COMPOUND FILTERING (multi-facet)
           ============================================================ */
        function applyFilters() {
            var articles = catalog.articles;

            // 1. Saved articles filter
            if (activeFilter.saved) {
                articles = articles.filter(function(a) { return savedArticles[a.id]; });
            }

            // 2. Year filter
            if (activeFilter.year) {
                articles = articles.filter(function(a) {
                    return a.date && a.date.substring(0, 4) === activeFilter.year;
                });
            }

            // 3. Issue filter (supersedes year)
            if (activeFilter.issue) {
                articles = articles.filter(function(a) {
                    return a.date === activeFilter.issue;
                });
            }

            // 4. Principle filter
            if (activeFilter.principle) {
                articles = articles.filter(function(a) {
                    return (a.principles || []).indexOf(activeFilter.principle) !== -1;
                });
            }

            // 5. Application filter
            if (activeFilter.application) {
                articles = articles.filter(function(a) {
                    return (a.applications || []).indexOf(activeFilter.application) !== -1;
                });
            }

            // 6. Author filter
            if (activeFilter.author) {
                articles = articles.filter(function(a) {
                    return a.author === activeFilter.author;
                });
            }

            // 7. Attribution filter
            if (activeFilter.attribution) {
                articles = articles.filter(function(a) {
                    return a.attribution === activeFilter.attribution;
                });
            }

            // 8. Date range
            if (activeFilter.yearFrom) {
                articles = articles.filter(function(a) {
                    return a.date && a.date.substring(0, 4) >= activeFilter.yearFrom;
                });
            }
            if (activeFilter.yearTo) {
                articles = articles.filter(function(a) {
                    return a.date && a.date.substring(0, 4) <= activeFilter.yearTo;
                });
            }

            // 9. Search query (advanced parsing + full-text)
            if (activeFilter.search) {
                var parsed = parseSearchQuery(activeFilter.search, currentSearchMode);
                if (parsed.clauses.length > 0) {
                    searchScores = {};
                    searchMatchedTerms = [];
                    // Collect matched terms from parsed clauses for highlighting
                    var seenTerms = {};
                    for (var ci = 0; ci < parsed.clauses.length; ci++) {
                        var c = parsed.clauses[ci];
                        if (c.negate) continue;
                        var terms = [];
                        if (c.type === 'proximity') {
                            terms = c.terms;
                        } else {
                            var t = c.raw || c.term || (c.prefix ? c.prefix + '*' : null);
                            if (t) terms = [t];
                        }
                        for (var ti = 0; ti < terms.length; ti++) {
                            if (!seenTerms[terms[ti]]) {
                                seenTerms[terms[ti]] = true;
                                searchMatchedTerms.push(terms[ti]);
                            }
                        }
                    }
                    articles = articles.filter(function(a) {
                        var bodyText = (searchData && searchData[a.id] || '').toLowerCase();
                        var result = matchArticle(a, parsed, bodyText);
                        if (result.matched) {
                            searchScores[a.id] = result.score;
                            return true;
                        }
                        return false;
                    });
                }
                currentSearchQuery = activeFilter.search;
            } else {
                currentSearchQuery = '';
                searchScores = {};
                searchMatchedTerms = [];
            }

            return articles;
        }

        function sortArticles(articles, sortKey) {
            var sorted = articles.slice();
            switch (sortKey) {
                case 'relevance':
                    sorted.sort(function(a, b) {
                        var sa = searchScores[a.id] || 0;
                        var sb = searchScores[b.id] || 0;
                        if (sb !== sa) return sb - sa;
                        return (b.date || '').localeCompare(a.date || '');
                    });
                    break;
                case 'date-asc':
                    sorted.sort(function(a, b) { return (a.date || '').localeCompare(b.date || ''); });
                    break;
                case 'title-asc':
                    sorted.sort(function(a, b) { return (a.title || '').localeCompare(b.title || ''); });
                    break;
                case 'title-desc':
                    sorted.sort(function(a, b) { return (b.title || '').localeCompare(a.title || ''); });
                    break;
                case 'date-desc':
                default:
                    sorted.sort(function(a, b) { return (b.date || '').localeCompare(a.date || ''); });
                    break;
            }
            return sorted;
        }

        function hasActiveFilters() {
            return activeFilter.year || activeFilter.issue || activeFilter.principle ||
                   activeFilter.application || activeFilter.author || activeFilter.attribution ||
                   activeFilter.saved || activeFilter.yearFrom || activeFilter.yearTo || activeFilter.search;
        }

        function getSearchSnippet(articleId, matchedTerms) {
            if (!searchData || !searchData[articleId] || !matchedTerms || matchedTerms.length === 0) return '';
            var text = searchData[articleId];
            var lowerText = text.toLowerCase();

            // Build regex patterns for finding and highlighting
            var patterns = [];
            for (var t = 0; t < matchedTerms.length; t++) {
                var term = matchedTerms[t];
                if (term.charAt(term.length - 1) === '*') {
                    patterns.push(escapeRegex(term.slice(0, -1)) + '\\w*');
                } else {
                    patterns.push(escapeRegex(term));
                }
            }

            // Find position of first match (for snippet centering)
            var firstIdx = -1;
            var secondIdx = -1;
            for (var t = 0; t < matchedTerms.length; t++) {
                var term = matchedTerms[t];
                var idx;
                if (term.charAt(term.length - 1) === '*') {
                    var wRe = new RegExp('\\b' + escapeRegex(term.slice(0, -1)) + '\\w*', 'i');
                    var wMatch = wRe.exec(lowerText);
                    idx = wMatch ? wMatch.index : -1;
                } else {
                    idx = lowerText.indexOf(term.toLowerCase());
                }
                if (idx !== -1) {
                    if (firstIdx === -1 || idx < firstIdx) {
                        secondIdx = firstIdx;
                        firstIdx = idx;
                    } else if (secondIdx === -1 || idx < secondIdx) {
                        secondIdx = idx;
                    }
                }
            }
            if (firstIdx === -1) return '';

            // For multi-term, try to center between first two matches
            var center = firstIdx;
            var snippetRadius = matchedTerms.length > 1 ? 100 : 75;
            if (secondIdx !== -1 && secondIdx - firstIdx < snippetRadius * 2) {
                center = Math.floor((firstIdx + secondIdx) / 2);
            }

            var start = Math.max(0, center - snippetRadius);
            var end = Math.min(text.length, center + snippetRadius);

            // Adjust to word boundaries
            if (start > 0) {
                var spaceIdx = text.indexOf(' ', start);
                if (spaceIdx !== -1 && spaceIdx < center) start = spaceIdx + 1;
            }
            if (end < text.length) {
                var spaceIdx2 = text.lastIndexOf(' ', end);
                if (spaceIdx2 > center) end = spaceIdx2;
            }

            var snippet = text.substring(start, end);
            var prefix = start > 0 ? '&hellip;' : '';
            var suffix = end < text.length ? '&hellip;' : '';

            // Highlight all matched terms in snippet (single pass to avoid tag corruption)
            var escapedSnippet = escapeHtml(snippet);
            if (patterns.length > 0) {
                var combinedRe = new RegExp('(' + patterns.join('|') + ')', 'gi');
                escapedSnippet = escapedSnippet.replace(combinedRe, '<span class="search-highlight">$1</span>');
            }

            return prefix + escapedSnippet + suffix;
        }

        function isBodyTextMatch(article, query) {
            if (!query || !searchData || !searchData[article.id]) return false;
            // Check if the match is ONLY in body text (not in metadata)
            var searchable = (article.title || '') + ' ' +
                (article.author || '') + ' ' +
                (article.principles || []).join(' ') + ' ' +
                (article.applications || []).join(' ') + ' ' +
                (article.keywords || []).join(' ');
            return searchable.toLowerCase().indexOf(query.toLowerCase()) === -1;
        }

        /* ============================================================
           RENDERING: LIST VIEW
           ============================================================ */
        function renderListView() {
            var articles = applyFilters();

            // Sort articles
            filteredArticles = sortArticles(articles, activeFilter.sort);

            currentPage = 0;

            // Exit split view, show/hide views
            dom.mainContent.classList.remove('split-view');
            dom.listView.style.display = 'block';
            dom.articleDetail.classList.remove('active');

            // Update sort select (show/hide relevance option)
            updateSortSelect();

            // Results summary
            renderResultsSummary(filteredArticles.length);

            // Filter chips
            renderFilterChips();

            // Issue TOC header
            renderIssueTocHeader();

            // Render the page
            renderPage();

            // Update sidebar counts dynamically
            updateSidebarCounts();
        }

        function updateSortSelect() {
            var hasRelevance = dom.sortSelect.querySelector('option[value="relevance"]');
            if (activeFilter.search) {
                if (!hasRelevance) {
                    var opt = document.createElement('option');
                    opt.value = 'relevance';
                    opt.textContent = 'Relevance';
                    dom.sortSelect.appendChild(opt);
                }
            } else {
                if (hasRelevance) {
                    hasRelevance.remove();
                    if (activeFilter.sort === 'relevance') {
                        activeFilter.sort = 'date-desc';
                        dom.sortSelect.value = 'date-desc';
                    }
                }
            }
            dom.sortSelect.value = activeFilter.sort;
        }

        function renderResultsSummary(count) {
            var hasFilters = hasActiveFilters();

            if (hasFilters) {
                dom.resultsSummaryText.innerHTML = count + ' article' + (count !== 1 ? 's' : '');
            } else {
                dom.resultsSummaryText.innerHTML = count + ' of ' + catalog.article_count + ' articles';
            }
        }

        function renderFilterChips() {
            var chips = [];

            if (activeFilter.saved) {
                chips.push({ label: 'Saved Articles', key: 'saved' });
            }
            if (activeFilter.year) {
                chips.push({ label: 'Year: ' + activeFilter.year, key: 'year' });
            }
            if (activeFilter.issue) {
                chips.push({ label: 'Issue: ' + formatIssueLabelFromDate(activeFilter.issue), key: 'issue' });
            }
            if (activeFilter.principle) {
                chips.push({ label: activeFilter.principle, key: 'principle' });
            }
            if (activeFilter.application) {
                chips.push({ label: activeFilter.application, key: 'application' });
            }
            if (activeFilter.author) {
                chips.push({ label: activeFilter.author, key: 'author' });
            }
            if (activeFilter.attribution) {
                var attrLabels = { editorial: 'Editorial', explicit: 'Signed Articles', reprint: 'Reprints' };
                chips.push({ label: attrLabels[activeFilter.attribution] || activeFilter.attribution, key: 'attribution' });
            }
            if (activeFilter.yearFrom || activeFilter.yearTo) {
                var rangeStr = (activeFilter.yearFrom || '...') + ' \u2013 ' + (activeFilter.yearTo || '...');
                chips.push({ label: 'Date: ' + rangeStr, key: 'dateRange' });
            }
            if (activeFilter.search) {
                chips.push({ label: '"' + activeFilter.search + '"', key: 'search' });
            }

            if (chips.length === 0) {
                dom.filterChipsBar.style.display = 'none';
                return;
            }

            var html = '<div class="filter-chips">';
            for (var i = 0; i < chips.length; i++) {
                html += '<span class="filter-chip">' + escapeHtml(chips[i].label) +
                    ' <button class="filter-chip-remove" data-remove-filter="' + chips[i].key + '" aria-label="Remove">&times;</button></span>';
            }
            if (chips.length > 1) {
                html += '<a class="clear-all-link" data-clear-all="true" role="button" tabindex="0">Clear all</a>';
            }
            html += '</div>';
            dom.filterChipsBar.innerHTML = html;
            dom.filterChipsBar.style.display = 'block';
        }

        function removeFilter(key) {
            if (key === 'year') { activeFilter.year = null; }
            else if (key === 'issue') { activeFilter.issue = null; }
            else if (key === 'principle') { activeFilter.principle = null; }
            else if (key === 'application') { activeFilter.application = null; }
            else if (key === 'author') { activeFilter.author = null; }
            else if (key === 'attribution') { activeFilter.attribution = null; }
            else if (key === 'saved') { activeFilter.saved = false; }
            else if (key === 'dateRange') {
                activeFilter.yearFrom = '';
                activeFilter.yearTo = '';
                dom.yearFrom.value = '';
                dom.yearTo.value = '';
                updateDateRangeClearVisibility();
            }
            else if (key === 'search') {
                activeFilter.search = '';
                dom.searchInput.value = '';
                updateSearchClearVisibility();
            }
            updateHashFromFilter();
        }

        function clearAllFilters() {
            activeFilter.year = null;
            activeFilter.issue = null;
            activeFilter.principle = null;
            activeFilter.application = null;
            activeFilter.author = null;
            activeFilter.attribution = null;
            activeFilter.saved = false;
            activeFilter.yearFrom = '';
            activeFilter.yearTo = '';
            activeFilter.search = '';
            dom.searchInput.value = '';
            dom.yearFrom.value = '';
            dom.yearTo.value = '';
            updateSearchClearVisibility();
            updateDateRangeClearVisibility();
            updateHashFromFilter();
        }

        function updateSidebarCounts() {
            // Compute counts for other facets based on current filter state
            // This gives researchers cross-dimensional insight
            if (!hasActiveFilters()) return; // No need — static counts already rendered

            // We need the filtered set for counting, but excluding each dimension's own filter
            // For simplicity, use the current filtered set
            var filtered = filteredArticles;
            renderYearsNav(filtered);
            renderPrinciplesNav(filtered);
            renderAuthorsNav(filtered);
            renderAttributionNav(filtered);

            // Re-apply expand states and active highlighting
            if (activeFilter.year) openYearGroup(activeFilter.year);
            if (activeFilter.issue) openYearForIssue(activeFilter.issue);
            if (activeFilter.principle) openPrincipleGroup(activeFilter.principle);
            if (activeFilter.application) openPrincipleGroupForApplication(activeFilter.application);
            updateSidebarActive();
        }

        function renderIssueTocHeader() {
            var existing = document.getElementById('issue-toc-header');
            if (existing) existing.remove();

            if (!activeFilter.issue) return;

            // Find an article in this issue to get vol/num info
            var sample = null;
            for (var i = 0; i < catalog.articles.length; i++) {
                if (catalog.articles[i].date === activeFilter.issue) {
                    sample = catalog.articles[i];
                    break;
                }
            }
            if (!sample) return;

            var header = document.createElement('div');
            header.className = 'issue-toc-header';
            header.id = 'issue-toc-header';
            header.innerHTML = '<h2>American Sentinel</h2>' +
                '<div class="issue-toc-sub">Volume ' + sample.volume + ', Number ' + sample.issue +
                ' &mdash; ' + formatDate(activeFilter.issue) + '</div>';

            dom.articleList.parentNode.insertBefore(header, dom.articleList);
        }

        function renderPage() {
            var articles = filteredArticles;
            // No pagination when viewing a single issue
            var effectivePageSize = activeFilter.issue ? articles.length : PAGE_SIZE;
            var totalPages = Math.ceil(articles.length / effectivePageSize) || 1;
            var start = currentPage * effectivePageSize;
            var end = Math.min(start + effectivePageSize, articles.length);
            var pageArticles = articles.slice(start, end);

            if (articles.length === 0) {
                dom.articleList.innerHTML = '<li class="no-results">' +
                    '<h3>No articles found</h3>' +
                    '<p>Try adjusting your search or filters.</p></li>';
                dom.pagination.style.display = 'none';
                return;
            }

            var html = '';
            for (var i = 0; i < pageArticles.length; i++) {
                var a = pageArticles[i];
                html += renderArticleCard(a);
            }
            dom.articleList.innerHTML = html;

            // Pagination
            if (totalPages > 1) {
                dom.pagination.style.display = 'flex';
                dom.prevBtn.disabled = (currentPage === 0);
                dom.nextBtn.disabled = (currentPage >= totalPages - 1);
                dom.pageInfo.textContent = 'Page ' + (currentPage + 1) + ' of ' + totalPages +
                    ' (' + articles.length + ' articles)';
            } else {
                dom.pagination.style.display = 'none';
            }
        }

        function renderArticleCard(article) {
            var meta = [];
            if (article.author) meta.push(escapeHtml(article.author));
            if (article.date) meta.push(formatDate(article.date));
            if (article.publication) meta.push(escapeHtml(article.publication));
            if (article.volume) meta[meta.length - 1] += ', Vol.&nbsp;' + article.volume;
            if (article.issue) meta[meta.length - 1] += ', No.&nbsp;' + article.issue;

            var tags = '';
            var principles = article.principles || [];
            for (var p = 0; p < principles.length; p++) {
                tags += '<span class="tag tag-principle">' + escapeHtml(principles[p]) + '</span>';
            }
            var applications = article.applications || [];
            for (var ap = 0; ap < applications.length && ap < 3; ap++) {
                tags += '<span class="tag tag-application">' + escapeHtml(applications[ap]) + '</span>';
            }

            var snippetHtml = '';
            if (currentSearchQuery && searchData && searchMatchedTerms.length > 0) {
                var snippet = getSearchSnippet(article.id, searchMatchedTerms);
                if (snippet) {
                    snippetHtml = '<div class="article-card-snippet">' + snippet + '</div>';
                }
            }

            var starClass = isSaved(article.id) ? ' saved' : '';
            var starChar = isSaved(article.id) ? '&#9733;' : '&#9734;';

            return '<li class="article-card" data-article-id="' + escapeHtml(article.id) + '" role="button" tabindex="0">' +
                '<button class="article-card-save' + starClass + '" data-save-article="' + escapeHtml(article.id) + '" aria-label="Save" title="Save article">' + starChar + '</button>' +
                '<div class="article-card-title">' + escapeHtml(article.title) + '</div>' +
                '<div class="article-card-meta">' + meta.join('<span class="sep">&bull;</span>') + '</div>' +
                '<div class="article-card-tags">' + tags + '</div>' +
                snippetHtml +
                '</li>';
        }

        /* ============================================================
           ADVANCED SEARCH: QUERY PARSER
           ============================================================ */
        function parseSearchQuery(queryString, defaultMode) {
            var query = queryString.trim();
            if (!query) return { mode: defaultMode || 'and', clauses: [] };

            // If "phrase" mode, wrap the entire query as one phrase
            if (defaultMode === 'phrase') {
                return {
                    mode: 'and',
                    clauses: [{ type: 'phrase', raw: query.toLowerCase(), negate: false }]
                };
            }

            // Detect explicit OR / AND operators (uppercase, word-bounded)
            var mode = defaultMode || 'and';
            var hasExplicitOr = /\bOR\b/.test(query);
            var hasExplicitAnd = /\bAND\b/.test(query);
            if (hasExplicitOr && !hasExplicitAnd) mode = 'or';

            // Remove AND/OR/NOT operators for tokenizing (NOT handled per-token)
            var cleaned = query.replace(/\bAND\b/g, ' ').replace(/\bOR\b/g, ' ');

            var clauses = [];
            var i = 0;
            var chars = cleaned;
            var len = chars.length;

            while (i < len) {
                // Skip whitespace
                while (i < len && chars[i] === ' ') i++;
                if (i >= len) break;

                var negate = false;

                // Check for NOT keyword
                if (chars.substring(i, i + 4) === 'NOT ' && i + 4 < len) {
                    negate = true;
                    i += 4;
                    while (i < len && chars[i] === ' ') i++;
                }

                // Check for - prefix (negation)
                if (!negate && chars[i] === '-' && i + 1 < len && chars[i + 1] !== ' ') {
                    negate = true;
                    i++;
                }

                // Quoted phrase: "..." or "..."~N
                if (chars[i] === '"') {
                    i++; // skip opening quote
                    var phraseEnd = chars.indexOf('"', i);
                    if (phraseEnd === -1) phraseEnd = len;
                    var phraseText = chars.substring(i, phraseEnd);
                    i = phraseEnd + 1; // skip closing quote

                    // Check for proximity: ~N
                    if (i < len && chars[i] === '~') {
                        i++; // skip ~
                        var distStr = '';
                        while (i < len && chars[i] >= '0' && chars[i] <= '9') {
                            distStr += chars[i];
                            i++;
                        }
                        var distance = parseInt(distStr, 10) || 5;
                        var proxTerms = phraseText.toLowerCase().split(/\s+/).filter(function(t) { return t; });
                        if (proxTerms.length >= 2) {
                            clauses.push({ type: 'proximity', terms: proxTerms, distance: distance, raw: phraseText.toLowerCase(), negate: negate });
                        }
                    } else {
                        // Regular phrase
                        if (phraseText.trim()) {
                            clauses.push({ type: 'phrase', raw: phraseText.toLowerCase(), negate: negate });
                        }
                    }
                    continue;
                }

                // Regular token: read until next space
                var tokenStart = i;
                while (i < len && chars[i] !== ' ') i++;
                var token = chars.substring(tokenStart, i);
                if (!token) continue;

                // Field prefix: title:word, author:word, body:word
                var colonIdx = token.indexOf(':');
                if (colonIdx > 0) {
                    var fieldName = token.substring(0, colonIdx).toLowerCase();
                    var fieldValue = token.substring(colonIdx + 1).toLowerCase();
                    if ((fieldName === 'title' || fieldName === 'author' || fieldName === 'body') && fieldValue) {
                        clauses.push({ type: 'field', field: fieldName, term: fieldValue, negate: negate });
                        continue;
                    }
                }

                // Wildcard: word*
                if (token.indexOf('*') !== -1) {
                    var prefix = token.replace(/\*/g, '').toLowerCase();
                    if (prefix.length >= 3) {
                        clauses.push({ type: 'wildcard', prefix: prefix, negate: negate });
                    } else if (prefix) {
                        // Too short for wildcard, treat as plain term
                        clauses.push({ type: 'term', term: prefix, negate: negate });
                    }
                    continue;
                }

                // Plain term — strip trailing punctuation (.,;:!?)
                var cleanToken = token.toLowerCase().replace(/[.,;:!?]+$/, '');
                if (cleanToken) {
                    clauses.push({ type: 'term', term: cleanToken, negate: negate });
                }
            }

            return { mode: mode, clauses: clauses };
        }

        /* ============================================================
           ADVANCED SEARCH: CLAUSE MATCHERS
           ============================================================ */
        var wildcardRegexCache = {};

        function matchTerm(text, term) {
            return text.indexOf(term) !== -1;
        }

        function matchPhrase(text, phrase) {
            return text.indexOf(phrase) !== -1;
        }

        function matchWildcard(text, prefix) {
            if (!wildcardRegexCache[prefix]) {
                wildcardRegexCache[prefix] = new RegExp('\\b' + escapeRegex(prefix) + '\\w*', 'i');
            }
            return wildcardRegexCache[prefix].test(text);
        }

        function matchProximity(text, terms, distance) {
            // Quick reject: all terms must exist
            for (var t = 0; t < terms.length; t++) {
                if (text.indexOf(terms[t]) === -1) return false;
            }
            // Split into words for position checking
            var words = text.match(/\S+/g) || [];
            // Find positions of each term
            var positions = [];
            for (var t = 0; t < terms.length; t++) {
                var termPositions = [];
                for (var w = 0; w < words.length; w++) {
                    if (words[w].indexOf(terms[t]) !== -1) {
                        termPositions.push(w);
                    }
                }
                if (termPositions.length === 0) return false;
                positions.push(termPositions);
            }
            // Check if all terms appear within distance of each other
            // For simplicity, check pairwise from first term's positions
            if (positions.length === 2) {
                for (var a = 0; a < positions[0].length; a++) {
                    for (var b = 0; b < positions[1].length; b++) {
                        if (Math.abs(positions[0][a] - positions[1][b]) <= distance) return true;
                    }
                }
                return false;
            }
            // For 3+ terms, check if any window of size distance contains all terms
            for (var anchor = 0; anchor < positions[0].length; anchor++) {
                var anchorPos = positions[0][anchor];
                var allClose = true;
                for (var t = 1; t < positions.length; t++) {
                    var found = false;
                    for (var p = 0; p < positions[t].length; p++) {
                        if (Math.abs(positions[t][p] - anchorPos) <= distance) {
                            found = true;
                            break;
                        }
                    }
                    if (!found) { allClose = false; break; }
                }
                if (allClose) return true;
            }
            return false;
        }

        function testClause(clause, titleText, authorText, metaText, bodyText) {
            // Returns: { matched: boolean, fieldScore: number }
            // metaText contains keywords + categories; split for field filtering
            var sf = searchFields;

            // For explicit field: clauses, ignore the checkbox filters
            if (clause.type === 'field') {
                var fieldText = clause.field === 'title' ? titleText :
                                clause.field === 'author' ? authorText : bodyText;
                if (matchTerm(fieldText, clause.term)) return { matched: true, fieldScore: clause.field === 'title' ? 3 : clause.field === 'author' ? 2 : 1 };
                return { matched: false, fieldScore: 0 };
            }

            if (clause.type === 'proximity') {
                var parts = [];
                if (sf.title) parts.push(titleText);
                if (sf.body) parts.push(bodyText);
                var allText = parts.join(' ');
                if (allText && matchProximity(allText, clause.terms, clause.distance)) return { matched: true, fieldScore: 1 };
                return { matched: false, fieldScore: 0 };
            }

            // Generic matching for term, phrase, wildcard
            var matchFn, matchArg;
            if (clause.type === 'term') { matchFn = matchTerm; matchArg = clause.term; }
            else if (clause.type === 'phrase') { matchFn = matchPhrase; matchArg = clause.raw; }
            else if (clause.type === 'wildcard') { matchFn = matchWildcard; matchArg = clause.prefix; }
            else return { matched: false, fieldScore: 0 };

            if (sf.title && matchFn(titleText, matchArg)) return { matched: true, fieldScore: 3 };
            if (sf.author && matchFn(authorText, matchArg)) return { matched: true, fieldScore: 2 };
            if (metaText && matchFn(metaText, matchArg)) return { matched: true, fieldScore: 2 };
            if (sf.body && matchFn(bodyText, matchArg)) return { matched: true, fieldScore: 1 };
            return { matched: false, fieldScore: 0 };
        }

        function matchArticle(article, parsedQuery, bodyText) {
            var titleText = (article.title || '').toLowerCase();
            var authorText = (article.author || '').toLowerCase();
            var metaParts = [];
            if (searchFields.keywords) metaParts.push((article.keywords || []).join(' '));
            if (searchFields.categories) metaParts.push((article.principles || []).join(' ') + ' ' + (article.applications || []).join(' '));
            var metaText = metaParts.join(' ').toLowerCase();

            var clauses = parsedQuery.clauses;
            if (clauses.length === 0) return { matched: false, score: 0, matchedTerms: [] };

            var score = 0;
            var matchedTerms = [];
            var positiveMatched = 0;
            var positiveClauses = 0;

            for (var i = 0; i < clauses.length; i++) {
                var clause = clauses[i];
                var result = testClause(clause, titleText, authorText, metaText, bodyText);

                if (clause.negate) {
                    // Negated clause: if it matches, the article is excluded
                    if (result.matched) return { matched: false, score: 0, matchedTerms: [] };
                } else {
                    positiveClauses++;
                    if (result.matched) {
                        positiveMatched++;
                        score += result.fieldScore;
                        // Collect the term for highlighting
                        var highlightTerm = clause.raw || clause.term || (clause.prefix ? clause.prefix + '*' : null);
                        if (highlightTerm) matchedTerms.push(highlightTerm);
                        // For proximity, add individual terms
                        if (clause.type === 'proximity') {
                            for (var t = 0; t < clause.terms.length; t++) {
                                matchedTerms.push(clause.terms[t]);
                            }
                        }
                    }
                }
            }

            if (positiveClauses === 0) {
                // Only negation clauses — match everything not excluded
                return { matched: true, score: 1, matchedTerms: [] };
            }

            var matched = false;
            if (parsedQuery.mode === 'and') {
                matched = (positiveMatched === positiveClauses);
            } else {
                // 'or' mode
                matched = (positiveMatched > 0);
                // Bonus for matching more terms in OR mode
                score += positiveMatched - 1;
            }

            return { matched: matched, score: score, matchedTerms: matchedTerms };
        }

        /* ============================================================
           ARTICLE BODY HIGHLIGHT + NAVIGATION
           ============================================================ */
        function highlightTermInBody(matchedTerms) {
            highlightMatches = [];
            currentHighlightIndex = -1;
            if (!matchedTerms || matchedTerms.length === 0) return 0;

            // Build combined regex from all terms
            var patterns = [];
            for (var t = 0; t < matchedTerms.length; t++) {
                var term = matchedTerms[t];
                if (term.charAt(term.length - 1) === '*') {
                    patterns.push(escapeRegex(term.slice(0, -1)) + '\\w*');
                } else {
                    patterns.push(escapeRegex(term));
                }
            }
            var combinedRegex = new RegExp('(' + patterns.join('|') + ')', 'gi');

            var walker = document.createTreeWalker(
                dom.detailBody, NodeFilter.SHOW_TEXT, null, false
            );

            var textNodes = [];
            while (walker.nextNode()) textNodes.push(walker.currentNode);

            for (var i = 0; i < textNodes.length; i++) {
                var node = textNodes[i];
                var text = node.textContent;
                combinedRegex.lastIndex = 0;
                if (!combinedRegex.test(text)) continue;

                var parent = node.parentNode;
                var frag = document.createDocumentFragment();
                var lastIdx = 0;
                var match;

                combinedRegex.lastIndex = 0;
                while ((match = combinedRegex.exec(text)) !== null) {
                    if (match.index > lastIdx) {
                        frag.appendChild(document.createTextNode(text.substring(lastIdx, match.index)));
                    }
                    var span = document.createElement('span');
                    span.className = 'search-highlight';
                    span.textContent = match[0];
                    frag.appendChild(span);
                    highlightMatches.push(span);
                    lastIdx = match.index + match[0].length;
                }

                if (lastIdx < text.length) {
                    frag.appendChild(document.createTextNode(text.substring(lastIdx)));
                }
                parent.replaceChild(frag, node);
            }

            return highlightMatches.length;
        }

        function showHighlightNav(count) {
            if (count > 0) {
                dom.highlightNav.style.display = 'flex';
                dom.highlightNavInfo.textContent = 'Match 1 of ' + count;
            } else {
                dom.highlightNav.style.display = 'none';
            }
        }

        function hideHighlightNav() {
            dom.highlightNav.style.display = 'none';
        }

        function goToHighlight(index) {
            if (highlightMatches.length === 0) return;
            if (index < 0) index = highlightMatches.length - 1;
            if (index >= highlightMatches.length) index = 0;

            if (currentHighlightIndex >= 0 && currentHighlightIndex < highlightMatches.length) {
                highlightMatches[currentHighlightIndex].classList.remove('current');
            }

            currentHighlightIndex = index;
            highlightMatches[index].classList.add('current');
            highlightMatches[index].scrollIntoView({ behavior: 'smooth', block: 'center' });
            dom.highlightNavInfo.textContent = 'Match ' + (index + 1) + ' of ' + highlightMatches.length;
        }

        function nextHighlight() {
            goToHighlight(currentHighlightIndex + 1);
        }

        function prevHighlight() {
            goToHighlight(currentHighlightIndex - 1);
        }

        function clearHighlights() {
            for (var i = 0; i < highlightMatches.length; i++) {
                var span = highlightMatches[i];
                var parent = span.parentNode;
                parent.replaceChild(document.createTextNode(span.textContent), span);
                parent.normalize();
            }
            highlightMatches = [];
            currentHighlightIndex = -1;
            hideHighlightNav();
        }

        /* ============================================================
           RENDERING: ARTICLE DETAIL VIEW
           ============================================================ */
        function highlightActiveCard(articleId) {
            var cards = dom.articleList.querySelectorAll('.article-card');
            for (var i = 0; i < cards.length; i++) {
                var cardId = cards[i].getAttribute('data-article-id');
                if (cardId === articleId) {
                    cards[i].classList.add('active-reading');
                    cards[i].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                } else {
                    cards[i].classList.remove('active-reading');
                }
            }
        }

        function showArticleDetail(articleId) {
            currentArticleId = articleId;
            highlightMatches = [];
            currentHighlightIndex = -1;
            hideHighlightNav();

            var article = articleById[articleId];
            if (!article) {
                dom.detailBody.innerHTML = '<div class="no-results"><h3>Article not found</h3>' +
                    '<p>The requested article could not be located in the catalog.</p></div>';
                dom.mainContent.classList.remove('split-view');
                dom.listView.style.display = 'none';
                dom.articleDetail.classList.add('active');
                dom.articleNav.style.display = 'none';
                dom.issueArticlesSection.style.display = 'none';
                dom.relatedArticlesSection.style.display = 'none';
                return;
            }

            // Set header info
            dom.detailTitle.textContent = article.title || 'Untitled';

            // Save button state
            dom.saveBtn.innerHTML = isSaved(articleId) ? '&#9733;' : '&#9734;';
            dom.saveBtn.className = 'detail-action-btn' + (isSaved(articleId) ? ' saved' : '');

            // PDF link
            updatePdfLink();

            // Meta line
            var metaParts = [];
            if (article.author) metaParts.push(escapeHtml(article.author));
            if (article.date) metaParts.push(formatDate(article.date));
            if (article.publication) {
                var pubStr = escapeHtml(article.publication);
                if (article.volume) pubStr += ', Vol.&nbsp;' + article.volume;
                if (article.issue) pubStr += ', No.&nbsp;' + article.issue;
                metaParts.push(pubStr);
            }
            var metaHtml = metaParts.join('<span class="sep"> &bull; </span>');
            if (article.original_publication) {
                metaHtml += '<br><span class="reprint-note">Reprinted from ' +
                    escapeHtml(article.original_publication) + '</span>';
            }
            dom.detailMeta.innerHTML = metaHtml;

            // Tags (clickable)
            var tagsHtml = '';
            var principles = article.principles || [];
            for (var p = 0; p < principles.length; p++) {
                tagsHtml += '<span class="tag tag-principle tag-clickable" data-route="principle/' +
                    encodeHashParam(principles[p]) + '">' + escapeHtml(principles[p]) + '</span>';
            }
            var applications = article.applications || [];
            for (var ap = 0; ap < applications.length; ap++) {
                tagsHtml += '<span class="tag tag-application tag-clickable" data-route="application/' +
                    encodeHashParam(applications[ap]) + '">' + escapeHtml(applications[ap]) + '</span>';
            }
            dom.detailTags.innerHTML = tagsHtml;

            // Keywords section
            var keywords = article.keywords || [];
            if (keywords.length > 0) {
                dom.detailKeywords.style.display = 'block';
                var kwHtml = '';
                for (var k = 0; k < keywords.length; k++) {
                    kwHtml += '<span class="tag tag-keyword tag-clickable" data-route="search/' +
                        encodeHashParam(String(keywords[k])) + '">' + escapeHtml(String(keywords[k])) + '</span>';
                }
                dom.detailKeywordsList.innerHTML = kwHtml;
            } else {
                dom.detailKeywords.style.display = 'none';
            }

            // Show detail - split view or full-width depending on filter state
            var useSplitView = hasActiveFilters() && window.innerWidth > 900;
            if (useSplitView) {
                dom.mainContent.classList.add('split-view');
                dom.listView.style.display = 'block';
                dom.articleDetail.classList.add('active');
                highlightActiveCard(articleId);
            } else {
                dom.mainContent.classList.remove('split-view');
                dom.listView.style.display = 'none';
                dom.articleDetail.classList.add('active');
            }

            // Show loading in body
            dom.detailBody.innerHTML = '<div class="article-loading"><div class="spinner"></div><p>Loading article&hellip;</p></div>';

            // Prev/Next article navigation (within same issue)
            renderArticleNav(article);

            // Other articles in this issue
            renderIssueArticles(article);

            // Related articles
            renderRelatedArticles(article);

            // Fetch article HTML
            fetchArticleContent(articleId);

            // Scroll to top (in split view, scroll the article pane; otherwise window)
            if (dom.mainContent.classList.contains('split-view')) {
                dom.articleDetail.scrollTop = 0;
            } else {
                window.scrollTo(0, 0);
            }
        }

        /* ============================================================
           ARTICLE NAVIGATION (prev/next within issue)
           ============================================================ */
        function getIssueArticles(article) {
            var issueArticles = [];
            for (var i = 0; i < catalog.articles.length; i++) {
                var a = catalog.articles[i];
                if (a.volume === article.volume && a.issue === article.issue && a.date === article.date) {
                    issueArticles.push(a);
                }
            }
            // Sort by id (which contains article number)
            issueArticles.sort(function(a, b) { return a.id.localeCompare(b.id); });
            return issueArticles;
        }

        function renderArticleNav(article) {
            var issueArticles = getIssueArticles(article);
            var idx = -1;
            for (var i = 0; i < issueArticles.length; i++) {
                if (issueArticles[i].id === article.id) { idx = i; break; }
            }

            if (issueArticles.length <= 1) {
                dom.articleNav.style.display = 'none';
                return;
            }

            dom.articleNav.style.display = 'flex';

            if (idx > 0) {
                var prev = issueArticles[idx - 1];
                dom.navPrev.setAttribute('data-nav-article', prev.id);
                dom.navPrev.classList.remove('disabled');
                dom.navPrevTitle.textContent = prev.title || 'Untitled';
            } else {
                dom.navPrev.removeAttribute('data-nav-article');
                dom.navPrev.classList.add('disabled');
                dom.navPrevTitle.textContent = '';
            }

            if (idx < issueArticles.length - 1) {
                var next = issueArticles[idx + 1];
                dom.navNext.setAttribute('data-nav-article', next.id);
                dom.navNext.classList.remove('disabled');
                dom.navNextTitle.textContent = next.title || 'Untitled';
            } else {
                dom.navNext.removeAttribute('data-nav-article');
                dom.navNext.classList.add('disabled');
                dom.navNextTitle.textContent = '';
            }
        }

        function renderIssueArticles(article) {
            var issueArticles = getIssueArticles(article);
            var others = issueArticles.filter(function(a) { return a.id !== article.id; });

            if (others.length === 0) {
                dom.issueArticlesSection.style.display = 'none';
                return;
            }

            dom.issueArticlesSection.style.display = 'block';
            dom.issueArticlesSection.removeAttribute('open');

            var html = '';
            for (var i = 0; i < others.length; i++) {
                var a = others[i];
                var authorStr = a.author ? escapeHtml(a.author) :
                    (a.attribution === 'reprint' && a.original_publication ? 'from ' + escapeHtml(a.original_publication) :
                    (a.attribution === 'editorial' ? 'Editorial' : ''));
                html += '<li><a data-issue-article="' + escapeHtml(a.id) + '" role="button" tabindex="0">' +
                    '<span>' + escapeHtml(a.title || 'Untitled') + '</span>' +
                    (authorStr ? '<span class="issue-article-author">' + authorStr + '</span>' : '') +
                    '</a></li>';
            }
            dom.issueArticlesList.innerHTML = html;
        }

        /* ============================================================
           RELATED ARTICLES
           ============================================================ */
        function findRelatedArticles(article, limit) {
            limit = limit || 5;
            var scores = [];

            for (var i = 0; i < catalog.articles.length; i++) {
                var a = catalog.articles[i];
                // Exclude self and same-issue articles
                if (a.id === article.id) continue;
                if (a.volume === article.volume && a.issue === article.issue && a.date === article.date) continue;

                var score = 0;
                var aPrinciples = a.principles || [];
                var aApps = a.applications || [];
                var aKeywords = a.keywords || [];
                var srcPrinciples = article.principles || [];
                var srcApps = article.applications || [];
                var srcKeywords = article.keywords || [];

                for (var p = 0; p < srcPrinciples.length; p++) {
                    if (aPrinciples.indexOf(srcPrinciples[p]) !== -1) score += 3;
                }
                for (var ap = 0; ap < srcApps.length; ap++) {
                    if (aApps.indexOf(srcApps[ap]) !== -1) score += 2;
                }
                for (var k = 0; k < srcKeywords.length; k++) {
                    if (aKeywords.indexOf(srcKeywords[k]) !== -1) score += 1;
                }
                if (article.author && a.author === article.author) score += 1;

                if (score > 0) {
                    scores.push({ article: a, score: score });
                }
            }

            scores.sort(function(a, b) {
                if (b.score !== a.score) return b.score - a.score;
                return (b.article.date || '').localeCompare(a.article.date || '');
            });

            return scores.slice(0, limit).map(function(s) { return s.article; });
        }

        function renderRelatedArticles(article) {
            var related = findRelatedArticles(article, 5);

            if (related.length === 0) {
                dom.relatedArticlesSection.style.display = 'none';
                return;
            }

            dom.relatedArticlesSection.style.display = 'block';

            var srcPrinciples = article.principles || [];
            var srcApps = article.applications || [];

            var html = '';
            for (var i = 0; i < related.length; i++) {
                var a = related[i];
                var meta = [];
                if (a.author) meta.push(escapeHtml(a.author));
                if (a.date) meta.push(formatDate(a.date));

                // Show matching tags
                var tags = '';
                var aPrinciples = a.principles || [];
                for (var p = 0; p < aPrinciples.length; p++) {
                    if (srcPrinciples.indexOf(aPrinciples[p]) !== -1) {
                        tags += '<span class="tag tag-principle">' + escapeHtml(aPrinciples[p]) + '</span>';
                    }
                }
                var aApps = a.applications || [];
                for (var ap = 0; ap < aApps.length && tags.split('tag').length < 5; ap++) {
                    if (srcApps.indexOf(aApps[ap]) !== -1) {
                        tags += '<span class="tag tag-application">' + escapeHtml(aApps[ap]) + '</span>';
                    }
                }

                html += '<li class="related-article-card" data-related-article="' + escapeHtml(a.id) + '" role="button" tabindex="0">' +
                    '<div class="related-article-title">' + escapeHtml(a.title || 'Untitled') + '</div>' +
                    '<div class="related-article-meta">' + meta.join(' &bull; ') + '</div>' +
                    (tags ? '<div class="related-article-tags">' + tags + '</div>' : '') +
                    '</li>';
            }
            dom.relatedArticlesList.innerHTML = html;
        }

        /* ============================================================
           CITATION
           ============================================================ */
        function formatCitation(article) {
            var author = article.author || '';
            var title = article.title || '';
            var pub = article.publication || 'American Sentinel';
            var vol = article.volume || '';
            var iss = article.issue || '';
            var dateStr = article.date ? formatDate(article.date) : '';
            var origPub = article.original_publication || '';

            var chicago = '';
            if (article.attribution === 'reprint' && origPub) {
                chicago = '\u201C' + title + '.\u201D Originally published in ' + origPub + '. Reprinted in ' +
                    pub + ' ' + vol + ', no. ' + iss + ' (' + dateStr + ').';
            } else if (article.attribution === 'editorial' || !author) {
                chicago = '\u201C' + title + '.\u201D ' + pub + ' ' + vol + ', no. ' + iss + ' (' + dateStr + ').';
            } else {
                // Split author name for Chicago: "Last, First Middle"
                var nameParts = author.split(' ');
                var chicagoAuthor = author;
                if (nameParts.length >= 2) {
                    chicagoAuthor = nameParts[nameParts.length - 1] + ', ' + nameParts.slice(0, -1).join(' ');
                }
                chicago = chicagoAuthor + '. \u201C' + title + '.\u201D ' + pub + ' ' + vol + ', no. ' + iss + ' (' + dateStr + ').';
            }

            // BibTeX
            var bibtexKey = (article.author_short || 'anon') + (article.date ? article.date.substring(0, 4) : '') +
                (title.split(' ')[0] || '').toLowerCase().replace(/[^a-z]/g, '');
            var bibtex = '@article{' + bibtexKey + ',\n' +
                '  title   = {' + title + '},\n' +
                (author ? '  author  = {' + author + '},\n' : '') +
                '  journal = {' + pub + '},\n' +
                '  volume  = {' + vol + '},\n' +
                '  number  = {' + iss + '},\n' +
                '  year    = {' + (article.date ? article.date.substring(0, 4) : '') + '},\n' +
                (origPub ? '  note    = {Reprinted from ' + origPub + '},\n' : '') +
                '}';

            return { chicago: chicago, bibtex: bibtex };
        }

        function showCiteModal() {
            if (!currentArticleId) return;
            var article = articleById[currentArticleId];
            if (!article) return;

            var citation = formatCitation(article);
            dom.citeTextChicago.textContent = citation.chicago;
            dom.citeTextBibtex.textContent = citation.bibtex;
            dom.citeModalOverlay.style.display = 'flex';
        }

        function closeCiteModal() {
            dom.citeModalOverlay.style.display = 'none';
        }

        function showToast(message) {
            dom.toast.textContent = message;
            dom.toast.classList.add('show');
            setTimeout(function() {
                dom.toast.classList.remove('show');
            }, 2000);
        }

        function copyToClipboard(text) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(function() {
                    showToast('Citation copied!');
                });
            } else {
                // Fallback
                var ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast('Citation copied!');
            }
        }

        /* ============================================================
           EXPORT SAVED ARTICLES
           ============================================================ */
        function exportSavedCitations() {
            var ids = Object.keys(savedArticles);
            if (ids.length === 0) return;

            var lines = [];
            for (var i = 0; i < ids.length; i++) {
                var a = articleById[ids[i]];
                if (a) {
                    var c = formatCitation(a);
                    lines.push(c.chicago);
                }
            }

            var blob = new Blob([lines.join('\n\n')], { type: 'text/plain' });
            var url = URL.createObjectURL(blob);
            var link = document.createElement('a');
            link.href = url;
            link.download = 'saved-articles-citations.txt';
            link.click();
            URL.revokeObjectURL(url);
        }

        function fetchArticleContent(articleId) {
            if (OFFLINE_MODE) {
                var html = window.__OFFLINE_ARTICLES[articleId];
                if (html) {
                    dom.detailBody.innerHTML = html;
                    if (searchMatchedTerms.length > 0) {
                        var matchCount = highlightTermInBody(searchMatchedTerms);
                        showHighlightNav(matchCount);
                        if (matchCount > 0) goToHighlight(0);
                    }
                } else {
                    dom.detailBody.innerHTML = '<div class="no-results">' +
                        '<h3>Article content not available</h3>' +
                        '<p>The full text of this article was not included in this offline archive.</p></div>';
                }
                return;
            }
            var url = ARTICLES_BASE + encodeURIComponent(articleId) + '.html';
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.onreadystatechange = function() {
                if (xhr.readyState !== 4) return;
                if (xhr.status === 200) {
                    dom.detailBody.innerHTML = xhr.responseText;
                    if (searchMatchedTerms.length > 0) {
                        var matchCount = highlightTermInBody(searchMatchedTerms);
                        showHighlightNav(matchCount);
                        if (matchCount > 0) goToHighlight(0);
                    }
                } else if (xhr.status === 404) {
                    dom.detailBody.innerHTML = '<div class="no-results">' +
                        '<h3>Article content not available</h3>' +
                        '<p>The full text of this article has not yet been published to the archive.</p></div>';
                } else {
                    dom.detailBody.innerHTML = '<div class="loading-error">' +
                        '<strong>Error loading article</strong> (HTTP ' + xhr.status + '). ' +
                        'Please try again later.</div>';
                }
            };
            xhr.onerror = function() {
                dom.detailBody.innerHTML = '<div class="loading-error">' +
                    '<strong>Network error.</strong> Please check your connection and try again.</div>';
            };
            xhr.send();
        }

        /* ============================================================
           URL ROUTING (hash-based)
           ============================================================ */
        function buildHash() {
            var parts = [];
            if (activeFilter.year) parts.push('year=' + encodeHashParam(activeFilter.year));
            if (activeFilter.issue) parts.push('issue=' + encodeHashParam(activeFilter.issue));
            if (activeFilter.principle) parts.push('principle=' + encodeHashParam(activeFilter.principle));
            if (activeFilter.application) parts.push('application=' + encodeHashParam(activeFilter.application));
            if (activeFilter.author) parts.push('author=' + encodeHashParam(activeFilter.author));
            if (activeFilter.attribution) parts.push('attribution=' + encodeHashParam(activeFilter.attribution));
            if (activeFilter.saved) parts.push('saved=1');
            if (activeFilter.yearFrom) parts.push('yearFrom=' + activeFilter.yearFrom);
            if (activeFilter.yearTo) parts.push('yearTo=' + activeFilter.yearTo);
            if (activeFilter.search) parts.push('search=' + encodeHashParam(activeFilter.search));
            if (activeFilter.search && currentSearchMode !== 'and') parts.push('mode=' + currentSearchMode);
            if (activeFilter.sort && activeFilter.sort !== 'date-desc') parts.push('sort=' + activeFilter.sort);

            if (parts.length === 0) return '';

            // Backward-compatible simple format for single legacy filters
            if (parts.length === 1) {
                var facets = ['year','issue','principle','application','author'];
                for (var f = 0; f < facets.length; f++) {
                    if (activeFilter[facets[f]] && !activeFilter.search) {
                        return facets[f] + '/' + encodeHashParam(activeFilter[facets[f]]);
                    }
                }
                if (activeFilter.search && !activeFilter.year && !activeFilter.principle && !activeFilter.author) {
                    return 'search/' + encodeHashParam(activeFilter.search);
                }
            }

            return 'filter/' + parts.join('&');
        }

        function parseHash(hash) {
            var filter = {
                year: null, issue: null, principle: null, application: null,
                author: null, attribution: null, saved: false,
                yearFrom: '', yearTo: '', search: '', sort: 'date-desc', mode: 'and'
            };

            if (!hash || hash === '') return filter;

            // Compound filter route
            if (hash.indexOf('filter/') === 0) {
                var paramStr = hash.substring(7);
                var pairs = paramStr.split('&');
                for (var i = 0; i < pairs.length; i++) {
                    var eqIdx = pairs[i].indexOf('=');
                    if (eqIdx === -1) continue;
                    var key = pairs[i].substring(0, eqIdx);
                    var val = decodeHashParam(pairs[i].substring(eqIdx + 1));

                    if (key === 'search') filter.search = val;
                    else if (key === 'mode') filter.mode = val;
                    else if (key === 'yearFrom') filter.yearFrom = val;
                    else if (key === 'yearTo') filter.yearTo = val;
                    else if (key === 'sort') filter.sort = val;
                    else if (key === 'saved') filter.saved = val === '1';
                    else if (key === 'year') filter.year = val;
                    else if (key === 'issue') filter.issue = val;
                    else if (key === 'principle') filter.principle = val;
                    else if (key === 'application') filter.application = val;
                    else if (key === 'author') filter.author = val;
                    else if (key === 'attribution') filter.attribution = val;
                }
                return filter;
            }

            // Legacy simple routes
            var slashIdx = hash.indexOf('/');
            var routeType = slashIdx > -1 ? hash.substring(0, slashIdx) : hash;
            var routeValue = slashIdx > -1 ? decodeHashParam(hash.substring(slashIdx + 1)) : '';

            if (routeType === 'search') {
                filter.search = routeValue;
            } else if (routeType === 'year' || routeType === 'principle' || routeType === 'application' || routeType === 'author' || routeType === 'issue') {
                filter[routeType] = routeValue;
            }

            return filter;
        }

        function handleRoute() {
            var hash = window.location.hash.replace(/^#\/?/, '');

            // Article detail view
            if (hash.indexOf('article/') === 0) {
                var articleId = decodeHashParam(hash.substring(8));
                showArticleDetail(articleId);
                return;
            }

            // No longer viewing a specific article
            currentArticleId = null;

            // Parse filter state from hash
            var parsed = parseHash(hash);
            activeFilter.year = parsed.year;
            activeFilter.issue = parsed.issue;
            activeFilter.principle = parsed.principle;
            activeFilter.application = parsed.application;
            activeFilter.author = parsed.author;
            activeFilter.attribution = parsed.attribution;
            activeFilter.saved = parsed.saved;
            activeFilter.search = parsed.search;
            activeFilter.yearFrom = parsed.yearFrom;
            activeFilter.yearTo = parsed.yearTo;
            activeFilter.sort = parsed.sort || 'date-desc';

            // Apply search mode from URL
            if (parsed.mode && (parsed.mode === 'and' || parsed.mode === 'phrase' || parsed.mode === 'or')) {
                currentSearchMode = parsed.mode;
            } else {
                currentSearchMode = 'and';
            }
            updateSearchModePills();

            // Update sidebar active state
            updateSidebarActive();

            // Open relevant groups
            if (activeFilter.year) openYearGroup(activeFilter.year);
            if (activeFilter.issue) openYearForIssue(activeFilter.issue);
            if (activeFilter.principle) openPrincipleGroup(activeFilter.principle);
            if (activeFilter.application) openPrincipleGroupForApplication(activeFilter.application);

            // Update search input
            dom.searchInput.value = activeFilter.search || '';
            updateSearchClearVisibility();
            updateSearchOptionsVisibility();

            // Update date range dropdowns
            dom.yearFrom.value = activeFilter.yearFrom || '';
            dom.yearTo.value = activeFilter.yearTo || '';
            updateDateRangeClearVisibility();

            // Update sort select
            dom.sortSelect.value = activeFilter.sort;

            // Render
            renderListView();
        }

        /* ============================================================
           SEARCH
           ============================================================ */
        var searchDebounceTimer = null;

        function onSearchInput() {
            var query = dom.searchInput.value.trim();
            updateSearchClearVisibility();
            updateSearchOptionsVisibility();

            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(function() {
                activeFilter.search = query;
                // Auto-switch to relevance sort when starting a search
                if (query && activeFilter.sort !== 'relevance') {
                    activeFilter.sort = 'relevance';
                }
                if (query && !searchDataLoaded) {
                    loadSearchData(function() {
                        updateHashFromFilter();
                    });
                } else {
                    updateHashFromFilter();
                }
            }, 250);
        }

        function updateSearchClearVisibility() {
            dom.searchClear.style.display = dom.searchInput.value.length > 0 ? 'block' : 'none';
        }

        function updateSearchOptionsVisibility() {
            var hasValue = dom.searchInput.value.length > 0;
            if (hasValue) {
                dom.searchOptions.classList.add('visible');
            } else if (document.activeElement !== dom.searchInput) {
                dom.searchOptions.classList.remove('visible');
            }
        }

        function updateSearchModePills() {
            var pills = dom.searchModes.querySelectorAll('.search-mode-pill');
            for (var i = 0; i < pills.length; i++) {
                if (pills[i].getAttribute('data-mode') === currentSearchMode) {
                    pills[i].classList.add('active');
                } else {
                    pills[i].classList.remove('active');
                }
            }
        }

        function clearSearch() {
            dom.searchInput.value = '';
            updateSearchClearVisibility();
            dom.searchOptions.classList.remove('visible');
            activeFilter.search = '';
            currentSearchMode = 'and';
            updateSearchModePills();
            updateHashFromFilter();
        }

        /* ============================================================
           DATE RANGE
           ============================================================ */
        function onDateRangeChange() {
            activeFilter.yearFrom = dom.yearFrom.value;
            activeFilter.yearTo = dom.yearTo.value;
            // Date range supersedes year/issue filter
            if (activeFilter.yearFrom || activeFilter.yearTo) {
                activeFilter.year = null;
                activeFilter.issue = null;
            }
            updateDateRangeClearVisibility();
            updateHashFromFilter();
        }

        function clearDateRange() {
            dom.yearFrom.value = '';
            dom.yearTo.value = '';
            activeFilter.yearFrom = '';
            activeFilter.yearTo = '';
            updateDateRangeClearVisibility();
            updateHashFromFilter();
        }

        function updateDateRangeClearVisibility() {
            dom.dateRangeClear.style.display =
                (activeFilter.yearFrom || activeFilter.yearTo) ? 'block' : 'none';
        }

        /* ============================================================
           NAVIGATION HELPERS
           ============================================================ */
        function updateHashFromFilter() {
            var newHash = buildHash();
            setHash(newHash);
        }

        function setHash(hash) {
            if (hash) {
                window.location.hash = '#' + hash;
            } else {
                if (window.location.hash) {
                    window.location.hash = '';
                } else {
                    handleRoute();
                }
            }
        }

        function goBack() {
            var hash = window.location.hash.replace(/^#\/?/, '');
            if (hash.indexOf('article/') === 0) {
                if (previousHash && previousHash.indexOf('article/') !== 0) {
                    window.location.hash = '#' + previousHash;
                } else {
                    setHash('');
                }
            } else {
                setHash('');
            }
        }

        /* ============================================================
           EVENT DELEGATION
           ============================================================ */
        function handleDelegatedClick(e) {
            var target = e.target;

            while (target && target !== document.body) {
                // Save article button (in card list or detail)
                var saveId = target.getAttribute('data-save-article');
                if (saveId) {
                    e.preventDefault();
                    e.stopPropagation();
                    toggleSaved(saveId);
                    // Update button appearance
                    if (isSaved(saveId)) {
                        target.classList.add('saved');
                        target.innerHTML = '&#9733;';
                    } else {
                        target.classList.remove('saved');
                        target.innerHTML = '&#9734;';
                    }
                    // If viewing saved filter, re-render
                    if (activeFilter.saved) renderListView();
                    return;
                }

                // Filter chip remove
                var removeKey = target.getAttribute('data-remove-filter');
                if (removeKey) {
                    e.preventDefault();
                    removeFilter(removeKey);
                    return;
                }

                // Clear all filters
                if (target.getAttribute('data-clear-all') === 'true') {
                    e.preventDefault();
                    clearAllFilters();
                    return;
                }

                // Multi-facet sidebar filter clicks
                var filterYear = target.getAttribute('data-filter-year');
                if (filterYear !== null) {
                    e.preventDefault();
                    closeSidebar();
                    if (activeFilter.year === filterYear) {
                        toggleYearGroup(filterYear);
                        return;
                    }
                    activeFilter.year = filterYear;
                    activeFilter.issue = null; // issue is within year
                    updateHashFromFilter();
                    return;
                }

                var filterIssue = target.getAttribute('data-filter-issue');
                if (filterIssue !== null) {
                    e.preventDefault();
                    closeSidebar();
                    activeFilter.issue = filterIssue;
                    activeFilter.year = null; // issue supersedes year
                    updateHashFromFilter();
                    return;
                }

                var filterPrinciple = target.getAttribute('data-filter-principle');
                if (filterPrinciple !== null) {
                    e.preventDefault();
                    closeSidebar();
                    if (activeFilter.principle === filterPrinciple) {
                        togglePrincipleGroup(filterPrinciple);
                        return;
                    }
                    activeFilter.principle = filterPrinciple;
                    updateHashFromFilter();
                    return;
                }

                var filterApp = target.getAttribute('data-filter-application');
                if (filterApp !== null) {
                    e.preventDefault();
                    closeSidebar();
                    activeFilter.application = filterApp;
                    updateHashFromFilter();
                    return;
                }

                var filterAuthor = target.getAttribute('data-filter-author');
                if (filterAuthor !== null) {
                    e.preventDefault();
                    closeSidebar();
                    activeFilter.author = filterAuthor;
                    updateHashFromFilter();
                    return;
                }

                var filterAttribution = target.getAttribute('data-filter-attribution');
                if (filterAttribution !== null) {
                    e.preventDefault();
                    closeSidebar();
                    activeFilter.attribution = filterAttribution;
                    updateHashFromFilter();
                    return;
                }

                var filterSaved = target.getAttribute('data-filter-saved');
                if (filterSaved !== null) {
                    e.preventDefault();
                    closeSidebar();
                    activeFilter.saved = !activeFilter.saved;
                    updateHashFromFilter();
                    return;
                }

                // Legacy data-route (for "All Articles", keyword tags, etc.)
                var route = target.getAttribute('data-route');
                if (route !== null) {
                    e.preventDefault();
                    closeSidebar();

                    if (route === '') {
                        clearAllFilters();
                        return;
                    }

                    // Handle tag clicks from article detail
                    if (route.indexOf('principle/') === 0) {
                        activeFilter.principle = decodeHashParam(route.substring(10));
                        updateHashFromFilter();
                        return;
                    }
                    if (route.indexOf('application/') === 0) {
                        activeFilter.application = decodeHashParam(route.substring(12));
                        updateHashFromFilter();
                        return;
                    }
                    if (route.indexOf('search/') === 0) {
                        activeFilter.search = decodeHashParam(route.substring(7));
                        dom.searchInput.value = activeFilter.search;
                        updateSearchClearVisibility();
                        updateHashFromFilter();
                        return;
                    }

                    setHash(route);
                    return;
                }

                // Article nav (prev/next)
                var navArticle = target.getAttribute('data-nav-article');
                if (navArticle) {
                    e.preventDefault();
                    setHash('article/' + encodeHashParam(navArticle));
                    return;
                }

                // Issue article link
                var issueLink = target.getAttribute('data-issue-article');
                if (issueLink) {
                    e.preventDefault();
                    setHash('article/' + encodeHashParam(issueLink));
                    return;
                }

                // Related article card
                var relatedId = target.getAttribute('data-related-article');
                if (relatedId) {
                    e.preventDefault();
                    setHash('article/' + encodeHashParam(relatedId));
                    return;
                }

                var articleId = target.getAttribute('data-article-id');
                if (articleId) {
                    e.preventDefault();
                    setHash('article/' + encodeHashParam(articleId));
                    return;
                }

                if (target.classList && target.classList.contains('article-card')) {
                    var id = target.getAttribute('data-article-id');
                    if (id) {
                        e.preventDefault();
                        setHash('article/' + encodeHashParam(id));
                        return;
                    }
                }

                target = target.parentElement;
            }
        }

        function handleDelegatedKeydown(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                var target = e.target;
                // Check for any filter or navigation attributes
                if (target.getAttribute('data-filter-year') !== null ||
                    target.getAttribute('data-filter-issue') !== null ||
                    target.getAttribute('data-filter-principle') !== null ||
                    target.getAttribute('data-filter-application') !== null ||
                    target.getAttribute('data-filter-author') !== null ||
                    target.getAttribute('data-filter-attribution') !== null ||
                    target.getAttribute('data-filter-saved') !== null ||
                    target.getAttribute('data-route') !== null ||
                    target.getAttribute('data-article-id') !== null ||
                    target.getAttribute('data-nav-article') !== null ||
                    target.getAttribute('data-issue-article') !== null ||
                    target.getAttribute('data-related-article') !== null) {
                    e.preventDefault();
                    target.click();
                    return;
                }
            }
        }

        /* ============================================================
           PAGINATION EVENT HANDLERS
           ============================================================ */
        function goNextPage() {
            var totalPages = Math.ceil(filteredArticles.length / PAGE_SIZE);
            if (currentPage < totalPages - 1) {
                currentPage++;
                renderPage();
                window.scrollTo(0, 0);
            }
        }

        function goPrevPage() {
            if (currentPage > 0) {
                currentPage--;
                renderPage();
                window.scrollTo(0, 0);
            }
        }

        /* ============================================================
           SHARE & PRINT
           ============================================================ */
        function shareArticle() {
            var url = window.location.href;
            if (navigator.share) {
                var article = currentArticleId ? articleById[currentArticleId] : null;
                navigator.share({
                    title: article ? article.title : 'American Sentinel Research Archive',
                    url: url
                }).catch(function() {});
            } else {
                copyLinkToClipboard(url);
            }
        }

        function copyLinkToClipboard(url) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url).then(function() {
                    showToast('Link copied!');
                });
            } else {
                var ta = document.createElement('textarea');
                ta.value = url;
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast('Link copied!');
            }
        }

        function printArticle() {
            window.print();
        }

        function updatePdfLink() {
            if (!currentArticleId) { dom.pdfBtn.href = '#'; return; }
            var article = articleById[currentArticleId];
            if (!article || !article.date || !article.volume || !article.issue) { dom.pdfBtn.href = '#'; return; }
            var year = article.date.substring(0, 4);
            var vol = String(article.volume).padStart(2, '0');
            var num = String(article.issue).padStart(2, '0');
            var pdfDate = article.date.length === 7 ? article.date + '-01' : article.date;
            // Publication renamed to "Sentinel of Liberty" from v15n18 (1900-05-10)
            var pubName = (article.volume === 15 && article.issue >= 18) ? 'Sentinel of Liberty' : 'American Sentinel';
            var filename = pubName + ' (' + pdfDate + ') Volume ' + vol + ', Number ' + num + '.pdf';
            var base = OFFLINE_MODE ? 'https://americansentinel.org' : '';
            dom.pdfBtn.href = base + '/files/american-sentinel-pdf-issues/' + year + '/' + encodeURIComponent(filename);
        }

        /* ============================================================
           INITIALIZATION
           ============================================================ */
        function init() {
            OFFLINE_MODE = typeof window.__OFFLINE_CATALOG !== 'undefined';
            cacheDom();

            // Hide download button in offline mode
            if (OFFLINE_MODE) {
                var dlBtn = document.getElementById('download-offline-btn');
                if (dlBtn) dlBtn.style.display = 'none';
            }

            // Event listeners
            dom.searchInput.addEventListener('input', onSearchInput);
            dom.searchClear.addEventListener('click', clearSearch);
            dom.prevBtn.addEventListener('click', goPrevPage);
            dom.nextBtn.addEventListener('click', goNextPage);
            dom.detailBackBtn.addEventListener('click', goBack);
            dom.yearFrom.addEventListener('change', onDateRangeChange);
            dom.yearTo.addEventListener('change', onDateRangeChange);
            dom.dateRangeClear.addEventListener('click', clearDateRange);
            dom.hamburgerBtn.addEventListener('click', function() {
                if (dom.sidebar.classList.contains('open')) {
                    closeSidebar();
                } else {
                    openSidebar();
                }
            });
            dom.sidebarOverlay.addEventListener('click', closeSidebar);

            // Sort select
            dom.sortSelect.addEventListener('change', function() {
                activeFilter.sort = dom.sortSelect.value;
                updateHashFromFilter();
            });

            // Search mode pill events
            dom.searchModes.addEventListener('click', function(e) {
                var pill = e.target.closest('.search-mode-pill');
                if (!pill) return;
                currentSearchMode = pill.getAttribute('data-mode');
                var pills = dom.searchModes.querySelectorAll('.search-mode-pill');
                for (var i = 0; i < pills.length; i++) pills[i].classList.remove('active');
                pill.classList.add('active');
                if (activeFilter.search) updateHashFromFilter();
            });

            // Search field checkbox events
            dom.searchFields.addEventListener('change', function(e) {
                if (e.target.type !== 'checkbox') return;
                searchFields[e.target.value] = e.target.checked;
                if (activeFilter.search) updateHashFromFilter();
            });

            // Search input focus/blur for showing options
            dom.searchInput.addEventListener('focus', function() {
                if (dom.searchInput.value.length > 0) {
                    dom.searchOptions.classList.add('visible');
                }
            });
            dom.searchInput.addEventListener('blur', function() {
                // Delay to allow clicks on options
                setTimeout(function() {
                    if (dom.searchInput.value.length === 0) {
                        dom.searchOptions.classList.remove('visible');
                    }
                }, 200);
            });

            // Highlight navigation events
            dom.highlightPrev.addEventListener('click', prevHighlight);
            dom.highlightNext.addEventListener('click', nextHighlight);
            dom.highlightClose.addEventListener('click', clearHighlights);

            // Share, Print & PDF
            dom.shareBtn.addEventListener('click', shareArticle);
            dom.printBtn.addEventListener('click', printArticle);
            // PDF link href is set dynamically in updatePdfLink()

            // Citation modal events
            dom.citeBtn.addEventListener('click', showCiteModal);
            dom.citeModalClose.addEventListener('click', closeCiteModal);
            dom.citeModalOverlay.addEventListener('click', function(e) {
                if (e.target === dom.citeModalOverlay) closeCiteModal();
            });
            dom.citeCopyChicago.addEventListener('click', function() {
                copyToClipboard(dom.citeTextChicago.textContent);
            });
            dom.citeCopyBibtex.addEventListener('click', function() {
                copyToClipboard(dom.citeTextBibtex.textContent);
            });

            // Save button in detail view
            dom.saveBtn.addEventListener('click', function() {
                if (!currentArticleId) return;
                toggleSaved(currentArticleId);
                dom.saveBtn.innerHTML = isSaved(currentArticleId) ? '&#9733;' : '&#9734;';
                dom.saveBtn.className = 'detail-action-btn' + (isSaved(currentArticleId) ? ' saved' : '');
            });

            // Global delegated click/keydown
            document.addEventListener('click', handleDelegatedClick);
            document.addEventListener('keydown', handleDelegatedKeydown);

            // Window resize: exit split view on narrow screens
            window.addEventListener('resize', function() {
                if (dom.mainContent.classList.contains('split-view') && window.innerWidth <= 900) {
                    dom.mainContent.classList.remove('split-view');
                    dom.listView.style.display = 'none';
                }
            });

            // Hash change for back/forward
            window.addEventListener('hashchange', function() {
                var newHash = window.location.hash.replace(/^#\/?/, '');
                handleRoute();
                previousHash = newHash;
            });

            // Track initial hash
            previousHash = window.location.hash.replace(/^#\/?/, '');

            // Load catalog
            loadCatalog();
        }

        // Start on DOM ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
        } else {
            init();
        }
    })();
    </script>
</body>
</html>

'''


# ---------------------------------------------------------------------------
# Site builder
# ---------------------------------------------------------------------------

def build_site(content_dir: Path, output_dir: Path, template_path: Path | None, offline: bool = False):
    """
    Build the complete static research portal.

    Steps:
      1. Build catalog from article .md files (reusing build_catalog logic)
      2. Create output directories
      3. Write catalog.json (with taxonomy.keywords omitted to save space)
      4. Convert each article body to HTML and write to articles/{id}.html
      5. Generate index.html from template with placeholders filled
      6. Write .htaccess
    """
    start_time = time.time()

    print(f"Content directory: {content_dir}")
    print(f"Output directory:  {output_dir}")
    print()

    if not content_dir.exists():
        print(f"Error: Content directory not found: {content_dir}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 1: Build the catalog
    # ------------------------------------------------------------------
    print("=== Building catalog ===")
    catalog = build_catalog(content_dir)
    print(f"  Total articles found: {catalog['article_count']}")
    print()

    # ------------------------------------------------------------------
    # Step 2: Create output directories
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    articles_dir = output_dir / 'articles'
    articles_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 3: Write catalog.json
    # Omit taxonomy.keywords (can be 4,000+ entries) since search
    # already works against per-article keywords.
    # ------------------------------------------------------------------
    print("=== Writing catalog.json ===")
    catalog_for_site = {
        'generated': catalog['generated'],
        'article_count': catalog['article_count'],
        'taxonomy': {
            'principles': catalog['taxonomy']['principles'],
            'applications': catalog['taxonomy']['applications'],
            # keywords omitted intentionally — per-article keywords remain
        },
        'articles': catalog['articles'],
    }

    catalog_path = output_dir / 'catalog.json'
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump(catalog_for_site, f, ensure_ascii=False, separators=(',', ':'))

    catalog_size_kb = catalog_path.stat().st_size / 1024
    print(f"  Written: catalog.json ({catalog_size_kb:.0f} KB)")
    print()

    # ------------------------------------------------------------------
    # Step 4: Convert article bodies to HTML fragments
    # ------------------------------------------------------------------
    print("=== Generating article HTML fragments ===")

    # Build a lookup: article_id -> file_path (from catalog entries)
    year_counts = {}
    error_count = 0

    for article in catalog['articles']:
        article_id = article.get('id')
        rel_path = article.get('path')
        if not article_id or not rel_path:
            error_count += 1
            continue

        file_path = content_dir / rel_path
        if not file_path.exists():
            print(f"  Warning: File not found: {file_path}")
            error_count += 1
            continue

        try:
            body = extract_article_body(file_path)
            article_html = markdown_to_html(body)

            out_path = articles_dir / f"{article_id}.html"
            out_path.write_text(article_html, encoding='utf-8')

            # Track per-year progress
            date_str = article.get('date', '')
            year = date_str[:4] if date_str and len(date_str) >= 4 else 'unknown'
            year_counts[year] = year_counts.get(year, 0) + 1

        except Exception as e:
            print(f"  Warning: Failed to process {article_id}: {e}")
            error_count += 1

    # Print per-year summary
    for year in sorted(year_counts.keys()):
        print(f"  {year}: {year_counts[year]} articles")
    if error_count:
        print(f"  Errors/skipped: {error_count}")
    total_articles = sum(year_counts.values())
    print(f"  Total HTML fragments: {total_articles}")
    print()

    # ------------------------------------------------------------------
    # Step 5: Generate search-data.json (full-text search index)
    # ------------------------------------------------------------------
    print("=== Generating search-data.json ===")
    search_data = []
    for article in catalog['articles']:
        article_id = article.get('id')
        rel_path = article.get('path')
        if not article_id or not rel_path:
            continue
        file_path = content_dir / rel_path
        if not file_path.exists():
            continue
        try:
            body = extract_article_body(file_path)
            plain_text = extract_plain_text(body)
            if plain_text:
                search_data.append({'id': article_id, 't': plain_text})
        except Exception:
            pass

    search_path = output_dir / 'search-data.json'
    with open(search_path, 'w', encoding='utf-8') as f:
        json.dump(search_data, f, ensure_ascii=False, separators=(',', ':'))

    search_size_kb = search_path.stat().st_size / 1024
    print(f"  Written: search-data.json ({search_size_kb:.0f} KB, {len(search_data)} articles)")
    print()

    # ------------------------------------------------------------------
    # Step 6: Generate index.html
    # ------------------------------------------------------------------
    print("=== Writing index.html ===")

    site_title = "American Sentinel Research Archive"
    catalog_url = "catalog.json"

    # Use external template if provided and it exists, otherwise use built-in
    if template_path and template_path.exists():
        print(f"  Using external template: {template_path}")
        template_content = template_path.read_text(encoding='utf-8')
    else:
        if template_path and not template_path.exists():
            print(f"  Template not found at {template_path}, using built-in template.")
        else:
            print(f"  Using built-in template.")
        template_content = STATIC_TEMPLATE

    # Replace placeholders
    index_html = template_content.replace('{SITE_TITLE}', site_title)
    index_html = index_html.replace('{CATALOG_URL}', catalog_url)

    index_path = output_dir / 'index.html'
    index_path.write_text(index_html, encoding='utf-8')
    index_size_kb = index_path.stat().st_size / 1024
    print(f"  Written: index.html ({index_size_kb:.0f} KB)")
    print()

    # ------------------------------------------------------------------
    # Step 7: Write .htaccess
    # ------------------------------------------------------------------
    htaccess_path = output_dir / '.htaccess'
    htaccess_path.write_text('RewriteEngine Off\n', encoding='utf-8')
    print(f"  Written: .htaccess")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = time.time() - start_time
    print()
    print("=" * 50)
    print(f"  Build complete in {elapsed:.1f}s")
    print(f"  {total_articles} articles")
    print(f"  Output: {output_dir.resolve()}")
    print("=" * 50)

    # ------------------------------------------------------------------
    # Step 8 (optional): Generate offline.html
    # ------------------------------------------------------------------
    if offline:
        print()
        generate_offline_html(output_dir)


# ---------------------------------------------------------------------------
# Offline HTML generator
# ---------------------------------------------------------------------------

def generate_offline_html(output_dir: Path):
    """Generate a single self-contained offline.html with all data embedded."""
    print("=== Generating offline.html ===")
    start = time.time()

    index_path = output_dir / 'index.html'
    catalog_path = output_dir / 'catalog.json'
    articles_dir = output_dir / 'articles'

    if not index_path.exists():
        print("  Error: index.html not found — run build first")
        return
    if not catalog_path.exists():
        print("  Error: catalog.json not found — run build first")
        return

    index_html = index_path.read_text(encoding='utf-8')
    catalog_json = catalog_path.read_text(encoding='utf-8')

    # Collect all article HTML fragments
    articles_obj = {}
    article_files = sorted(articles_dir.glob('*.html'))
    for af in article_files:
        article_id = af.stem
        articles_obj[article_id] = af.read_text(encoding='utf-8')
    print(f"  Embedded articles: {len(articles_obj)}")

    articles_json = json.dumps(articles_obj, ensure_ascii=False, separators=(',', ':'))

    # Escape </script> inside embedded JSON to prevent premature tag closing
    catalog_json_safe = catalog_json.replace('</script>', '<\\/script>')
    articles_json_safe = articles_json.replace('</script>', '<\\/script>')

    # Inject data scripts before </body>
    inject = (
        '<script>window.__OFFLINE_CATALOG = ' + catalog_json_safe + ';</script>\n'
        '<script>window.__OFFLINE_ARTICLES = ' + articles_json_safe + ';</script>\n'
    )

    if '</body>' in index_html:
        offline_html = index_html.replace('</body>', inject + '</body>', 1)
    else:
        offline_html = index_html + '\n' + inject

    offline_path = output_dir / 'offline.html'
    offline_path.write_text(offline_html, encoding='utf-8')

    size_mb = offline_path.stat().st_size / (1024 * 1024)
    elapsed = time.time() - start
    print(f"  Written: offline.html ({size_mb:.1f} MB) in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Build static research portal from transcribed article files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python build_site.py
    python build_site.py --output ./research
    python build_site.py --content-dir ~/my-articles --output ./site
    python build_site.py --template custom_template.html
        """,
    )
    parser.add_argument(
        '--content-dir',
        type=Path,
        default=Path.home() / 'Documents/PUBLICAR/APL/English',
        help='Root directory containing transcribed files (default: ~/Documents/PUBLICAR/APL/English)',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('research'),
        help='Output directory for the static site (default: ./research)',
    )
    parser.add_argument(
        '--template',
        type=Path,
        default=None,
        help='Path to custom HTML template (default: built-in template). '
             'Template may use {SITE_TITLE} and {CATALOG_URL} placeholders.',
    )
    parser.add_argument(
        '--offline',
        action='store_true',
        default=False,
        help='Generate offline.html — a single self-contained file for offline use.',
    )

    args = parser.parse_args()
    build_site(args.content_dir, args.output, args.template, offline=args.offline)


if __name__ == '__main__':
    main()
