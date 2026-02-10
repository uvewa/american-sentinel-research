# American Sentinel Research Archive

A searchable digital archive of *The American Sentinel* (1886-1900), a Seventh-day Adventist periodical dedicated to religious liberty, church-state separation, and freedom of conscience.

**Live site:** [americansentinel.org/research](https://americansentinel.org/research/)

## About the Publication

*The American Sentinel* was published from 1886 to 1900, first as a monthly and later as a weekly periodical. It addressed issues of religious liberty during a period when Sunday laws, constitutional amendments, and church-state entanglements were actively debated in the United States. Key editors included Alonzo T. Jones and E. J. Waggoner.

## What's in the Archive

- **2,577 articles** transcribed from original publications (1886-1892)
- Full-text search across all article content
- Categorized by principle, application, author, and date
- Each article preserves the exact text of the original publication

## Project Tools

| File | Description |
|------|-------------|
| `build_site.py` | Builds the static research portal (HTML, catalog, search index) |
| `build_catalog.py` | Scans transcribed article files and generates `catalog.json` |
| `extract_idml.py` | Extracts articles from InDesign IDML files (used for 1886-1890) |
| `template.html` | Single-page application template for the research portal |
| `catalog.json` | Article metadata catalog (2,577 entries) |
| `requirements.txt` | Python dependencies |

## Building the Site

```bash
pip install -r requirements.txt
python3 build_site.py --output ./research
```

This generates a self-contained static site in `./research/` with:
- `index.html` — the single-page research portal
- `catalog.json` — article metadata
- `search-data.json` — full-text search index
- `articles/` — individual article HTML fragments

## Research Portal Features

- **Three-column layout**: sidebar filters, article content, persistent search panel
- **Full-text search**: search across all article body text with highlighted snippets
- **Sidebar filters**: browse by year, principle, application, or author
- **Responsive design**: adapts to desktop, tablet, and mobile
- **No server required**: fully static site, works from any web server

## Taxonomy

Articles are categorized by timeless principles and their specific applications:

- **Religious Liberty** — Freedom of Conscience, Freedom of Worship, Right to Dissent
- **Church and State** — Separation, Government Favoritism, Christian Nation Claims
- **Limits of Civil Authority** — Religious vs Civil Law, Legislating Morality
- **Persecution** — Legal Persecution, Fines and Imprisonment, Historical Parallels
- **Constitutional Principles** — First Amendment, No Religious Tests, Founding Fathers' Intent
- **Religion and Education** — State Schools, Public Funding, Bible Reading
- **The Sabbath Question** — Sunday Legislation, Day of Rest Arguments

## License

The original *American Sentinel* articles are in the public domain. The tools in this repository are provided as-is for research and educational purposes.
