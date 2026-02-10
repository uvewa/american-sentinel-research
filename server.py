#!/usr/bin/env python3
"""
Religious Liberty Research Portal - Local Web Server

A browsable web interface for the article catalog.

Usage:
    python server.py [--port PORT] [--content-dir PATH]

Then open http://localhost:8080 in your browser.
"""

import argparse
import json
import os
import re
import html
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    exit(1)

# Global config
CATALOG_PATH = Path('catalog.json')
CONTENT_DIR = Path.home() / 'Documents/PUBLICAR/APL/English'


def load_catalog():
    """Load the catalog from JSON file."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'articles': [], 'taxonomy': {'principles': [], 'applications': {}, 'keywords': []}}


def load_article(path: str) -> dict:
    """Load an article file and parse its frontmatter and content."""
    full_path = CONTENT_DIR / path
    if not full_path.exists():
        return None

    content = full_path.read_text(encoding='utf-8')

    # Parse frontmatter
    frontmatter = {}
    body = content

    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
            # Convert date objects to strings for JSON serialization
            for key, value in frontmatter.items():
                if hasattr(value, 'isoformat'):
                    frontmatter[key] = value.isoformat()
        except yaml.YAMLError:
            pass
        body = match.group(2)

    return {
        'frontmatter': frontmatter,
        'content': body
    }


def markdown_to_html(md: str) -> str:
    """Simple markdown to HTML conversion."""
    lines = md.split('\n')
    html_lines = []
    in_blockquote = False
    in_list = False

    for line in lines:
        # Headers
        if line.startswith('# '):
            html_lines.append(f'<h1>{html.escape(line[2:])}</h1>')
        elif line.startswith('## '):
            html_lines.append(f'<h2>{html.escape(line[3:])}</h2>')
        elif line.startswith('### '):
            html_lines.append(f'<h3>{html.escape(line[4:])}</h3>')
        # Blockquotes
        elif line.startswith('> '):
            if not in_blockquote:
                html_lines.append('<blockquote>')
                in_blockquote = True
            html_lines.append(html.escape(line[2:]) + '<br>')
        # Horizontal rule
        elif line.strip() == '---':
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            html_lines.append('<hr>')
        # List items
        elif line.startswith('- '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            html_lines.append(f'<li>{html.escape(line[2:])}</li>')
        elif line.strip().startswith(tuple(f'{i}. ' for i in range(1, 20))):
            if not in_list:
                html_lines.append('<ol>')
                in_list = True
            text = re.sub(r'^\d+\.\s*', '', line.strip())
            html_lines.append(f'<li>{html.escape(text)}</li>')
        # Empty line
        elif line.strip() == '':
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append('</ul>' if html_lines[-2].startswith('<ul') or '<li>' in html_lines[-1] else '</ol>')
                in_list = False
            html_lines.append('<br>')
        # Regular paragraph
        else:
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            # Handle emphasis
            text = html.escape(line)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            html_lines.append(f'<p>{text}</p>')

    if in_blockquote:
        html_lines.append('</blockquote>')
    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Religious Liberty Research Portal</title>
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
        <h1>Religious Liberty Research Portal</h1>
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
                <div class="article-content" id="article-content"></div>
            </div>
        </main>
    </div>

    <script>
        let catalog = null;
        let currentFilter = null;
        let currentFilterType = null;
        let displayedArticles = [];
        let currentPage = 0;
        const PAGE_SIZE = 25;

        async function loadCatalog() {
            const response = await fetch('/api/catalog');
            catalog = await response.json();
            renderNav();
            document.getElementById('total-count').textContent = catalog.article_count;
            document.getElementById('article-count').textContent = catalog.article_count;
            renderArticles(catalog.articles);
        }

        function renderNav() {
            // Principles with nested applications
            const principlesNav = document.getElementById('principles-nav');
            const principleCount = {};
            const appCount = {};
            catalog.articles.forEach(a => {
                (a.principles || []).forEach(p => {
                    principleCount[p] = (principleCount[p] || 0) + 1;
                });
                (a.applications || []).forEach(app => {
                    appCount[app] = (appCount[app] || 0) + 1;
                });
            });

            const apps = catalog.taxonomy.applications || {};

            principlesNav.innerHTML = catalog.taxonomy.principles.map(p => {
                const subApps = (apps[p] || []).filter(a => appCount[a]);
                const subHtml = subApps.length ? `<ul class="sub-list" id="sub-${CSS.escape(p)}">${
                    subApps.map(a =>
                        `<li><a href="#" onclick="filterByApplication('${a.replace(/'/g, "\\'")}'); return false;" data-filter="app-${a}">
                            ${a} <span class="count">${appCount[a] || 0}</span>
                        </a></li>`
                    ).join('')
                }</ul>` : '';
                const arrow = subApps.length ? `<span class="expand-arrow" id="arrow-${CSS.escape(p)}">&#9654;</span>` : '';
                return `<li class="expandable"><a href="#" onclick="filterByPrinciple('${p}', event); return false;" data-filter="principle-${p}">
                    ${arrow}${p} <span class="count">${principleCount[p] || 0}</span>
                </a>${subHtml}</li>`;
            }).join('');

            // Authors
            const authorsNav = document.getElementById('authors-nav');
            const authorCount = {};
            catalog.articles.forEach(a => {
                const author = a.author || 'Anonymous';
                authorCount[author] = (authorCount[author] || 0) + 1;
            });

            const authors = Object.keys(authorCount).sort();
            authorsNav.innerHTML = authors.map(a =>
                `<li><a href="#" onclick="filterByAuthor('${a}'); return false;" data-filter="author-${a}">
                    ${a} <span class="count">${authorCount[a]}</span>
                </a></li>`
            ).join('');
        }

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

            list.innerHTML = page.map((a, i) => `
                <li class="article-card" onclick="openArticle(${start + i})">
                    <h3>${a.title}</h3>
                    <div class="article-meta">
                        ${a.author || 'Anonymous'} &bull; ${a.date} &bull; ${a.publication}
                    </div>
                    <div class="article-tags">
                        ${(a.principles || []).map(p => `<span class="tag principle">${p}</span>`).join('')}
                        ${(a.applications || []).slice(0, 3).map(app => `<span class="tag">${app}</span>`).join('')}
                    </div>
                </li>
            `).join('');

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

        function openArticle(index) {
            window.location.hash = 'article/' + encodeURIComponent(displayedArticles[index].path);
        }

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
            window.location.hash = '';
        }

        function showAll() {
            currentFilter = null;
            currentFilterType = null;
            setActiveNav('#nav-all');
            renderArticles(catalog.articles);
            showListView();
        }

        function filterByPrinciple(principle, event) {
            currentFilter = principle;
            currentFilterType = 'principle';
            setActiveNav(`[data-filter="principle-${principle}"]`);
            const filtered = catalog.articles.filter(a =>
                (a.principles || []).includes(principle)
            );
            renderArticles(filtered);
            showListView();

            // Toggle subcategory list
            const subList = document.getElementById('sub-' + CSS.escape(principle));
            const arrow = document.getElementById('arrow-' + CSS.escape(principle));
            if (subList) {
                // Close all other sub-lists
                document.querySelectorAll('.sub-list').forEach(sl => {
                    if (sl !== subList) { sl.classList.remove('open'); }
                });
                document.querySelectorAll('.expand-arrow').forEach(ar => {
                    if (ar !== arrow) { ar.classList.remove('open'); }
                });
                subList.classList.toggle('open');
                if (arrow) arrow.classList.toggle('open');
            }
        }

        function filterByApplication(application) {
            currentFilter = application;
            currentFilterType = 'application';
            setActiveNav(`[data-filter="app-${application}"]`);
            const filtered = catalog.articles.filter(a =>
                (a.applications || []).includes(application)
            );
            renderArticles(filtered);
            showListView();
        }

        function filterByAuthor(author) {
            currentFilter = author;
            currentFilterType = 'author';
            setActiveNav(`[data-filter="author-${author}"]`);
            const filtered = catalog.articles.filter(a =>
                (a.author || 'Anonymous') === author
            );
            renderArticles(filtered);
            showListView();
        }

        async function showArticle(path) {
            try {
            const response = await fetch('/api/article?path=' + encodeURIComponent(path));
            if (!response.ok) { alert('Server error: ' + response.status); return; }
            const data = await response.json();

            document.getElementById('article-title').textContent = data.frontmatter.title || 'Untitled';

            const meta = [];
            if (data.frontmatter.author) meta.push(data.frontmatter.author);
            if (data.frontmatter.date) meta.push(data.frontmatter.date);
            if (data.frontmatter.publication) meta.push(data.frontmatter.publication);
            if (data.frontmatter.original_publication) meta.push('(from ' + data.frontmatter.original_publication + ')');
            document.getElementById('article-meta').textContent = meta.join(' • ');

            const tags = [];
            (data.frontmatter.principles || []).forEach(p => {
                tags.push(`<span class="tag principle">${p}</span>`);
            });
            (data.frontmatter.applications || []).forEach(a => {
                tags.push(`<span class="tag">${a}</span>`);
            });
            document.getElementById('article-tags').innerHTML = tags.join('');

            document.getElementById('article-content').innerHTML = data.html;

            document.getElementById('list-view').style.display = 'none';
            document.getElementById('article-view').classList.add('active');
            } catch(err) { alert('Error loading article: ' + err.message); }
        }

        function hideArticle() {
            window.location.hash = '';
        }

        // Search
        document.getElementById('search').addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();

            if (!query) {
                if (currentFilter && currentFilterType === 'principle') {
                    filterByPrinciple(currentFilter);
                } else if (currentFilter && currentFilterType === 'application') {
                    filterByApplication(currentFilter);
                } else if (currentFilter && currentFilterType === 'author') {
                    filterByAuthor(currentFilter);
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

        function handleRoute() {
            const hash = window.location.hash;
            if (hash.startsWith('#article/')) {
                const path = decodeURIComponent(hash.substring('#article/'.length));
                showArticle(path);
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
</html>
'''


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def send_json(self, data):
        """Send JSON response with proper headers."""
        try:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except Exception as e:
            print(f"Error in send_json: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def send_html(self, html_content):
        """Send HTML response with proper headers."""
        body = html_content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == '/' or path == '/index.html':
                self.send_html(HTML_TEMPLATE)

            elif path == '/api/catalog':
                catalog = load_catalog()
                self.send_json(catalog)

            elif path == '/api/article':
                article_path = query.get('path', [''])[0]
                print(f"Loading article: {article_path}", flush=True)
                article = load_article(article_path)

                if article:
                    print(f"Article loaded, converting to HTML...", flush=True)
                    article['html'] = markdown_to_html(article['content'])
                    print(f"Sending JSON response...", flush=True)
                    self.send_json(article)
                    print(f"Response sent.", flush=True)
                else:
                    print(f"Article not found: {article_path}", flush=True)
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Article not found"}')

            else:
                self.send_response(404)
                self.end_headers()

        except Exception as e:
            print(f"Error handling request: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        # Log requests for debugging
        print(f"[{self.command}] {self.path}", flush=True)


def main():
    global CATALOG_PATH, CONTENT_DIR

    parser = argparse.ArgumentParser(description='Religious Liberty Research Portal')
    parser.add_argument('--port', type=int, default=8080, help='Port to run server on')
    parser.add_argument('--catalog', type=Path, default=Path('catalog.json'), help='Path to catalog.json')
    parser.add_argument('--content-dir', type=Path,
                        default=Path.home() / 'Documents/PUBLICAR/APL/English',
                        help='Root directory containing transcribed files')

    args = parser.parse_args()

    CATALOG_PATH = args.catalog
    CONTENT_DIR = args.content_dir

    if not CATALOG_PATH.exists():
        print(f"Warning: Catalog not found at {CATALOG_PATH}")
        print("Run build_catalog.py first to generate it.")

    server = HTTPServer(('localhost', args.port), RequestHandler)
    print(f"\n{'='*50}")
    print("  Religious Liberty Research Portal")
    print(f"{'='*50}")
    print(f"\n  Open in browser: http://localhost:{args.port}")
    print(f"\n  Press Ctrl+C to stop the server")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.shutdown()


if __name__ == '__main__':
    main()
