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

    for line in lines:
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

STATIC_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{SITE_TITLE}</title>
    <style>
        :root {
            --primary: #2c3e50;
            --secondary: #3498db;
            --accent: #e74c3c;
            --bg: #f8f9fa;
            --card-bg: #ffffff;
            --text: #333;
            --text-light: #666;
            --border: #ddd;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Georgia', serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }

        header {
            background: var(--primary);
            color: white;
            padding: 1.5rem 2rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        header h1 {
            font-size: 1.8rem;
            font-weight: normal;
            margin-bottom: 0.5rem;
        }

        header p {
            opacity: 0.8;
            font-size: 0.95rem;
        }

        .container {
            display: flex;
            min-height: calc(100vh - 120px);
        }

        .sidebar {
            width: 280px;
            background: var(--card-bg);
            border-right: 1px solid var(--border);
            padding: 1rem;
            overflow-y: auto;
            position: sticky;
            top: 0;
            height: calc(100vh - 120px);
        }

        .sidebar h2 {
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-light);
            margin: 1.5rem 0 0.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border);
        }

        .sidebar h2:first-child {
            margin-top: 0;
        }

        .sidebar ul {
            list-style: none;
        }

        .sidebar li {
            margin: 0.25rem 0;
        }

        .sidebar a {
            color: var(--text);
            text-decoration: none;
            font-size: 0.9rem;
            display: block;
            padding: 0.4rem 0.6rem;
            border-radius: 4px;
            transition: background 0.2s;
        }

        .sidebar a:hover {
            background: var(--bg);
        }

        .sidebar a.active {
            background: var(--secondary);
            color: white;
        }

        .sidebar .count {
            float: right;
            background: var(--bg);
            color: var(--text-light);
            font-size: 0.75rem;
            padding: 0.1rem 0.4rem;
            border-radius: 10px;
        }

        .sidebar a.active .count {
            background: rgba(255,255,255,0.2);
            color: white;
        }

        .sidebar .sub-list {
            display: none;
            padding-left: 0.75rem;
        }

        .sidebar .sub-list.open {
            display: block;
        }

        .sidebar .sub-list a {
            font-size: 0.82rem;
            padding: 0.25rem 0.6rem;
            color: var(--text-light);
        }

        .sidebar .sub-list a:hover {
            color: var(--text);
        }

        .sidebar .sub-list a.active {
            color: white;
        }

        .sidebar .expandable {
            position: relative;
        }

        .sidebar .expand-arrow {
            display: inline-block;
            width: 0.6em;
            margin-right: 0.3em;
            font-size: 0.7em;
            transition: transform 0.15s;
        }

        .sidebar .expand-arrow.open {
            transform: rotate(90deg);
        }

        .main {
            flex: 1;
            padding: 2rem;
            max-width: 900px;
        }

        .search-box {
            margin-bottom: 1.5rem;
        }

        .search-box input {
            width: 100%;
            padding: 0.8rem 1rem;
            font-size: 1rem;
            border: 2px solid var(--border);
            border-radius: 8px;
            font-family: inherit;
        }

        .search-box input:focus {
            outline: none;
            border-color: var(--secondary);
        }

        .article-list {
            list-style: none;
        }

        .article-card {
            background: var(--card-bg);
            border-radius: 8px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            cursor: pointer;
            transition: box-shadow 0.2s, transform 0.2s;
        }

        .article-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.12);
            transform: translateY(-2px);
        }

        .article-card h3 {
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
            color: var(--primary);
        }

        .article-meta {
            font-size: 0.85rem;
            color: var(--text-light);
            margin-bottom: 0.5rem;
        }

        .article-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }

        .tag {
            background: var(--bg);
            color: var(--text-light);
            font-size: 0.75rem;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }

        .tag.principle {
            background: #e8f4f8;
            color: #2980b9;
        }

        /* Article view */
        .article-view {
            display: none;
        }

        .article-view.active {
            display: block;
        }

        .article-view .back-btn {
            display: inline-block;
            margin-bottom: 1rem;
            color: var(--secondary);
            cursor: pointer;
            font-size: 0.9rem;
        }

        .article-view .back-btn:hover {
            text-decoration: underline;
        }

        .article-header {
            border-bottom: 2px solid var(--border);
            padding-bottom: 1rem;
            margin-bottom: 1.5rem;
        }

        .article-header h1 {
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
            color: var(--primary);
        }

        .article-content {
            background: var(--card-bg);
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .article-content h1 { font-size: 1.6rem; margin: 1.5rem 0 1rem; }
        .article-content h2 { font-size: 1.3rem; margin: 1.5rem 0 0.75rem; }
        .article-content h3 { font-size: 1.1rem; margin: 1.25rem 0 0.5rem; }
        .article-content h4 { font-size: 1rem; margin: 1rem 0 0.5rem; }
        .article-content p { margin-bottom: 1rem; text-align: justify; }
        .article-content blockquote {
            border-left: 3px solid var(--secondary);
            padding-left: 1rem;
            margin: 1rem 0;
            color: var(--text-light);
            font-style: italic;
        }
        .article-content em { font-style: italic; }
        .article-content strong { font-weight: bold; }
        .article-content hr { margin: 2rem 0; border: none; border-top: 1px solid var(--border); }

        .stats {
            text-align: center;
            padding: 2rem;
            color: var(--text-light);
        }

        .stats .number {
            font-size: 2.5rem;
            color: var(--primary);
            display: block;
        }

        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 1rem;
            padding: 1.5rem 0;
        }

        .pagination button {
            background: var(--secondary);
            color: white;
            border: none;
            padding: 0.5rem 1.2rem;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.9rem;
        }

        .pagination button:disabled {
            background: var(--border);
            cursor: default;
        }

        .pagination span {
            color: var(--text-light);
            font-size: 0.9rem;
        }

        .loading-spinner {
            text-align: center;
            padding: 3rem;
            color: var(--text-light);
        }

        @media (max-width: 768px) {
            .container {
                flex-direction: column;
            }
            .sidebar {
                width: 100%;
                height: auto;
                position: static;
            }
            .main {
                padding: 1rem;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>{SITE_TITLE}</h1>
        <p>Historical Adventist Pioneer writings on church-state relations and religious freedom</p>
    </header>

    <div class="container">
        <nav class="sidebar">
            <h2>Browse</h2>
            <ul>
                <li><a href="#" onclick="showAll(); return false;" class="active" id="nav-all">All Articles <span class="count" id="total-count">0</span></a></li>
            </ul>

            <h2>Principles</h2>
            <ul id="principles-nav"></ul>

            <h2>Years</h2>
            <ul id="years-nav"></ul>

            <h2>Authors</h2>
            <ul id="authors-nav"></ul>
        </nav>

        <main class="main">
            <div id="list-view">
                <div class="search-box">
                    <input type="text" id="search" placeholder="Search articles, keywords, authors...">
                </div>

                <div class="stats" id="stats">
                    <span class="number" id="article-count">0</span>
                    articles cataloged
                </div>

                <ul class="article-list" id="article-list"></ul>
                <div class="pagination" id="pagination" style="display:none">
                    <button id="prev-btn" onclick="changePage(-1)">Previous</button>
                    <span id="page-info"></span>
                    <button id="next-btn" onclick="changePage(1)">Next</button>
                </div>
            </div>

            <div id="article-view" class="article-view">
                <span class="back-btn" onclick="hideArticle()">&larr; Back to list</span>
                <div class="article-header">
                    <h1 id="article-title"></h1>
                    <div class="article-meta" id="article-meta"></div>
                    <div class="article-tags" id="article-tags"></div>
                </div>
                <div class="article-content" id="article-content">
                    <div class="loading-spinner">Loading article...</div>
                </div>
            </div>
        </main>
    </div>

    <script>
        // ---- Configuration ----
        const CATALOG_URL = "{CATALOG_URL}";
        const ARTICLES_DIR = "articles/";
        const PAGE_SIZE = 25;

        // ---- State ----
        let catalog = null;
        let currentFilter = null;
        let currentFilterType = null;
        let displayedArticles = [];
        let currentPage = 0;
        // Cache of fetched article HTML fragments
        const articleCache = {};

        // ---- Initialization ----
        async function loadCatalog() {
            try {
                const response = await fetch(CATALOG_URL);
                if (!response.ok) throw new Error('HTTP ' + response.status);
                catalog = await response.json();
            } catch (err) {
                document.getElementById('article-list').innerHTML =
                    '<li style="text-align:center;color:#c00;padding:2rem;">Failed to load catalog: ' +
                    err.message + '</li>';
                return;
            }
            renderNav();
            document.getElementById('total-count').textContent = catalog.article_count;
            document.getElementById('article-count').textContent = catalog.article_count;
            renderArticles(catalog.articles);
        }

        // ---- Navigation rendering ----
        function renderNav() {
            // Principles with nested applications
            const principlesNav = document.getElementById('principles-nav');
            const principleCount = {};
            const appCount = {};
            const yearCount = {};
            catalog.articles.forEach(a => {
                (a.principles || []).forEach(p => {
                    principleCount[p] = (principleCount[p] || 0) + 1;
                });
                (a.applications || []).forEach(app => {
                    appCount[app] = (appCount[app] || 0) + 1;
                });
                if (a.date) {
                    const yr = a.date.substring(0, 4);
                    yearCount[yr] = (yearCount[yr] || 0) + 1;
                }
            });

            const apps = catalog.taxonomy.applications || {};

            principlesNav.innerHTML = catalog.taxonomy.principles.map(p => {
                const subApps = (apps[p] || []).filter(a => appCount[a]);
                const subHtml = subApps.length ? '<ul class="sub-list" id="sub-' + cssEsc(p) + '">' +
                    subApps.map(a =>
                        '<li><a href="#" onclick="filterByApplication(\'' + jsEsc(a) + '\'); return false;" data-filter="app-' + a + '">' +
                            a + ' <span class="count">' + (appCount[a] || 0) + '</span>' +
                        '</a></li>'
                    ).join('') + '</ul>' : '';
                const arrow = subApps.length ? '<span class="expand-arrow" id="arrow-' + cssEsc(p) + '">&#9654;</span>' : '';
                return '<li class="expandable"><a href="#" onclick="filterByPrinciple(\'' + jsEsc(p) + '\', event); return false;" data-filter="principle-' + p + '">' +
                    arrow + p + ' <span class="count">' + (principleCount[p] || 0) + '</span>' +
                '</a>' + subHtml + '</li>';
            }).join('');

            // Years
            const yearsNav = document.getElementById('years-nav');
            const years = Object.keys(yearCount).sort();
            yearsNav.innerHTML = years.map(y =>
                '<li><a href="#" onclick="filterByYear(\'' + y + '\'); return false;" data-filter="year-' + y + '">' +
                    y + ' <span class="count">' + yearCount[y] + '</span>' +
                '</a></li>'
            ).join('');

            // Authors
            const authorsNav = document.getElementById('authors-nav');
            const authorCount = {};
            catalog.articles.forEach(a => {
                const author = a.author || 'Anonymous';
                authorCount[author] = (authorCount[author] || 0) + 1;
            });

            const authors = Object.keys(authorCount).sort();
            authorsNav.innerHTML = authors.map(a =>
                '<li><a href="#" onclick="filterByAuthor(\'' + jsEsc(a) + '\'); return false;" data-filter="author-' + a + '">' +
                    a + ' <span class="count">' + authorCount[a] + '</span>' +
                '</a></li>'
            ).join('');
        }

        // ---- Helpers ----
        function cssEsc(s) { return CSS.escape(s); }
        function jsEsc(s) { return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

        function escHtml(s) {
            return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        }

        // ---- Article list rendering ----
        function renderArticles(articles) {
            displayedArticles = articles;
            currentPage = 0;
            renderPage();
        }

        function renderPage() {
            const list = document.getElementById('article-list');
            const stats = document.getElementById('stats');
            const pagination = document.getElementById('pagination');
            const articles = displayedArticles;

            if (articles.length === 0) {
                list.innerHTML = '<li style="text-align: center; color: #666; padding: 2rem;">No articles found</li>';
                stats.style.display = 'none';
                pagination.style.display = 'none';
                return;
            }

            stats.style.display = 'none';

            const totalPages = Math.ceil(articles.length / PAGE_SIZE);
            const start = currentPage * PAGE_SIZE;
            const end = Math.min(start + PAGE_SIZE, articles.length);
            const page = articles.slice(start, end);

            list.innerHTML = page.map((a, i) => {
                const author = escHtml(a.author || 'Anonymous');
                const title = escHtml(a.title || 'Untitled');
                const date = escHtml(a.date || '');
                const pub = escHtml(a.publication || '');
                const principles = (a.principles || []).map(p => '<span class="tag principle">' + escHtml(p) + '</span>').join('');
                const apps = (a.applications || []).slice(0, 3).map(ap => '<span class="tag">' + escHtml(ap) + '</span>').join('');
                return '<li class="article-card" onclick="openArticle(' + (start + i) + ')">' +
                    '<h3>' + title + '</h3>' +
                    '<div class="article-meta">' + author + ' &bull; ' + date + ' &bull; ' + pub + '</div>' +
                    '<div class="article-tags">' + principles + apps + '</div>' +
                '</li>';
            }).join('');

            if (totalPages > 1) {
                pagination.style.display = 'flex';
                document.getElementById('prev-btn').disabled = currentPage === 0;
                document.getElementById('next-btn').disabled = currentPage >= totalPages - 1;
                document.getElementById('page-info').textContent =
                    'Page ' + (currentPage + 1) + ' of ' + totalPages + ' (' + articles.length + ' articles)';
            } else {
                pagination.style.display = 'none';
            }
        }

        function changePage(delta) {
            currentPage += delta;
            renderPage();
            window.scrollTo(0, 0);
        }

        // ---- Article viewing ----
        function openArticle(index) {
            const article = displayedArticles[index];
            if (article && article.id) {
                window.location.hash = 'article/' + encodeURIComponent(article.id);
            }
        }

        async function showArticle(articleId) {
            // Find article metadata from catalog
            const article = catalog.articles.find(a => a.id === articleId);
            if (!article) {
                document.getElementById('article-content').innerHTML =
                    '<p style="color:#c00;">Article not found in catalog.</p>';
                document.getElementById('list-view').style.display = 'none';
                document.getElementById('article-view').classList.add('active');
                return;
            }

            // Populate header
            document.getElementById('article-title').textContent = article.title || 'Untitled';

            const meta = [];
            if (article.author) meta.push(article.author);
            if (article.date) meta.push(article.date);
            if (article.publication) meta.push(article.publication);
            if (article.original_publication) meta.push('(from ' + article.original_publication + ')');
            document.getElementById('article-meta').textContent = meta.join(' \u2022 ');

            const tags = [];
            (article.principles || []).forEach(p => {
                tags.push('<span class="tag principle">' + escHtml(p) + '</span>');
            });
            (article.applications || []).forEach(a => {
                tags.push('<span class="tag">' + escHtml(a) + '</span>');
            });
            document.getElementById('article-tags').innerHTML = tags.join('');

            // Show view, set loading state
            document.getElementById('list-view').style.display = 'none';
            document.getElementById('article-view').classList.add('active');
            document.getElementById('article-content').innerHTML =
                '<div class="loading-spinner">Loading article...</div>';

            // Fetch pre-rendered HTML fragment
            try {
                let htmlContent = articleCache[articleId];
                if (!htmlContent) {
                    const url = ARTICLES_DIR + encodeURIComponent(articleId) + '.html';
                    const response = await fetch(url);
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    htmlContent = await response.text();
                    articleCache[articleId] = htmlContent;
                }
                document.getElementById('article-content').innerHTML = htmlContent;
            } catch (err) {
                document.getElementById('article-content').innerHTML =
                    '<p style="color:#c00;">Failed to load article: ' + escHtml(err.message) + '</p>';
            }

            window.scrollTo(0, 0);
        }

        function hideArticle() {
            window.location.hash = '';
        }

        // ---- Filtering ----
        function setActiveNav(selector) {
            document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
            if (selector) {
                const el = document.querySelector(selector);
                if (el) el.classList.add('active');
            }
        }

        function showListView() {
            document.getElementById('list-view').style.display = 'block';
            document.getElementById('article-view').classList.remove('active');
        }

        function showAll() {
            currentFilter = null;
            currentFilterType = null;
            setActiveNav('#nav-all');
            renderArticles(catalog.articles);
            showListView();
            window.location.hash = '';
        }

        function filterByPrinciple(principle, event) {
            currentFilter = principle;
            currentFilterType = 'principle';
            setActiveNav('[data-filter="principle-' + principle + '"]');
            const filtered = catalog.articles.filter(a =>
                (a.principles || []).includes(principle)
            );
            renderArticles(filtered);
            showListView();

            // Toggle subcategory list
            const subList = document.getElementById('sub-' + cssEsc(principle));
            const arrow = document.getElementById('arrow-' + cssEsc(principle));
            if (subList) {
                document.querySelectorAll('.sub-list').forEach(sl => {
                    if (sl !== subList) sl.classList.remove('open');
                });
                document.querySelectorAll('.expand-arrow').forEach(ar => {
                    if (ar !== arrow) ar.classList.remove('open');
                });
                subList.classList.toggle('open');
                if (arrow) arrow.classList.toggle('open');
            }
        }

        function filterByApplication(application) {
            currentFilter = application;
            currentFilterType = 'application';
            setActiveNav('[data-filter="app-' + application + '"]');
            const filtered = catalog.articles.filter(a =>
                (a.applications || []).includes(application)
            );
            renderArticles(filtered);
            showListView();
        }

        function filterByAuthor(author) {
            currentFilter = author;
            currentFilterType = 'author';
            setActiveNav('[data-filter="author-' + author + '"]');
            const filtered = catalog.articles.filter(a =>
                (a.author || 'Anonymous') === author
            );
            renderArticles(filtered);
            showListView();
        }

        function filterByYear(year) {
            currentFilter = year;
            currentFilterType = 'year';
            setActiveNav('[data-filter="year-' + year + '"]');
            const filtered = catalog.articles.filter(a =>
                a.date && a.date.substring(0, 4) === year
            );
            renderArticles(filtered);
            showListView();
        }

        // ---- Search ----
        document.getElementById('search').addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();

            if (!query) {
                if (currentFilter && currentFilterType === 'principle') {
                    filterByPrinciple(currentFilter);
                } else if (currentFilter && currentFilterType === 'application') {
                    filterByApplication(currentFilter);
                } else if (currentFilter && currentFilterType === 'author') {
                    filterByAuthor(currentFilter);
                } else if (currentFilter && currentFilterType === 'year') {
                    filterByYear(currentFilter);
                } else {
                    renderArticles(catalog.articles);
                }
                return;
            }

            let articles = catalog.articles;
            if (currentFilter && currentFilterType === 'principle') {
                articles = articles.filter(a => (a.principles || []).includes(currentFilter));
            } else if (currentFilter && currentFilterType === 'application') {
                articles = articles.filter(a => (a.applications || []).includes(currentFilter));
            } else if (currentFilter && currentFilterType === 'author') {
                articles = articles.filter(a => (a.author || 'Anonymous') === currentFilter);
            } else if (currentFilter && currentFilterType === 'year') {
                articles = articles.filter(a => a.date && a.date.substring(0, 4) === currentFilter);
            }

            const filtered = articles.filter(a => {
                const searchable = [
                    a.title,
                    a.author,
                    ...(a.principles || []),
                    ...(a.applications || []),
                    ...(a.keywords || [])
                ].join(' ').toLowerCase();
                return searchable.includes(query);
            });

            renderArticles(filtered);
        });

        // ---- Routing ----
        function handleRoute() {
            const hash = window.location.hash;
            if (hash.startsWith('#article/')) {
                const articleId = decodeURIComponent(hash.substring('#article/'.length));
                showArticle(articleId);
            } else {
                document.getElementById('list-view').style.display = 'block';
                document.getElementById('article-view').classList.remove('active');
            }
        }

        window.addEventListener('hashchange', handleRoute);

        loadCatalog().then(() => {
            if (window.location.hash) handleRoute();
        });
    </script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Site builder
# ---------------------------------------------------------------------------

def build_site(content_dir: Path, output_dir: Path, template_path: Path | None):
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

    args = parser.parse_args()
    build_site(args.content_dir, args.output, args.template)


if __name__ == '__main__':
    main()
