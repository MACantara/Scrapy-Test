# spiders

This folder contains the site-specific Scrapy spiders used by the project. Each spider is self-contained and implements listing page generation, listing parsing (extract article URLs) and article parsing (extract title, content, author, published_date, source).

This document explains how to add a new spider and shows the spiders that exist today.

## Contract / Item shape
Each spider should yield simple dicts (or Scrapy Items) with the following keys at minimum:
- `title` — string
- `url` — canonical article URL
- `content` — article body (string)
- `author` — string or `None`
- `published_date` — `datetime.date` or `None` (ISO-parsable preferred)
- `source` — short source name (e.g. `Philstar`, `PNA`)

Pipelines will map these keys into the Flask `Article` model.

## Helpers available
- `from scrapy_spiders.db import url_exists, preload_existing_urls`
  - `preload_existing_urls()` loads normalized existing article URLs from the Flask DB into memory (call during spider `__init__` to avoid import-time DB initialization).
  - `url_exists(url)` checks whether a normalized URL is already present; use it to avoid scheduling articles that are already stored.

- Use `bs4` / BeautifulSoup inside spiders (project uses BeautifulSoup for HTML convenience).

## Where to hook into the runner
The top-level `scrapy_spiders/runner.py` imports spider classes and exposes them via the `AVAILABLE` mapping. If you add a new spider file, import it in `runner.py` and add the mapping (key is the spider name used by the runner CLI).

## How to create a new spider (recommended template)
Copy one of the existing spiders and follow this minimal template. Put the file under `scrapy_spiders/spiders/<your_site>.py`.

```python
import scrapy
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime

class ExampleSpider(scrapy.Spider):
    name = "example"
    LISTING_URL = "https://example.com/"

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        preload_existing_urls()  # loads existing URLs for dedup checks

    def start_requests(self):
        cap = self.pages if self.pages is not None else 10
        for p in range(1, cap + 1):
            if p == 1:
                url = self.LISTING_URL
            else:
                url = urljoin(self.LISTING_URL, f"page/{p}/")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        # find article links and yield requests to parse_article
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(self.LISTING_URL, href)
            if url_exists(href):
                continue
            yield scrapy.Request(href, callback=self.parse_article)

    def parse_article(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        title = (soup.find('h1') or soup.find('title')).get_text(strip=True)
        content = (soup.find('div', class_='article-body') or soup).get_text(strip=True)
        author = None
        published_date = None
        # extract/normalize as needed
        yield {
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            'published_date': published_date,
            'source': 'Example'
        }
```

Notes:
- Use `preload_existing_urls()` in `__init__` (not at import-time) to avoid initializing the Flask app during module import.
- Call `url_exists()` before scheduling article requests to avoid duplicates.
- Keep `published_date` as a `date` object when possible; pipelines will handle DB persistence.

## Scaffolding a new spider with the helper script

A lightweight generator is included at `scripts/create_spider.py` to bootstrap a new spider file. It creates a ready-to-edit spider under `scrapy_spiders/spiders/<name>.py` using the same conventions as the examples above.

Usage (from the project root, PowerShell example):

```powershell
# create a new spider named `mynews` with a listing URL and human-friendly source name
python scripts/create_spider.py mynews --listing-url https://mynews.example/ --source "My News"

# overwrite if file exists
python scripts/create_spider.py mynews --listing-url https://mynews.example/ --source "My News" --force
```

What the script does:
- Writes `scrapy_spiders/spiders/<name>.py` with a starter template (start_requests, parse_listing, parse_article).
- Uses `preload_existing_urls()` in the spider `__init__` so the generated spider follows the project's dedup pattern.

Next steps after running the script:
- Open the generated file and customize selectors and normalization logic in `parse_listing` and `parse_article`.
- Optionally register the spider with the runner by importing it in `scrapy_spiders/runner.py` and adding it to the `AVAILABLE` mapping.
- For quick import-only tests (without creating DB engines), set `SKIP_DB_CREATE=1` in your environment before importing the spider.

The generator is intentionally simple so you can tailor the selectors for each site; use the existing spiders as richer examples for complex extraction rules.

## Running a single spider
From the project root you can use the packaged runner:

```powershell
# Run the 'pna' spider for 2 pages
python -m scrapy_spiders.runner pna --pages 2
```

Or run programmatically using Scrapy's `CrawlerProcess` (the runner is preferred because it configures the SQLAlchemy pipeline):

```python
from scrapy.crawler import CrawlerProcess
from scrapy_spiders.spiders.pna import PNASpider

process = CrawlerProcess()
process.crawl(PNASpider, pages=1, limit=5, job_id=42)
process.start()
```

## Current spiders (files)
- `pna.py` — PNA spider (author cleaning, date parsing, supports `?p=N` pagination and `/latest`)
- `rappler.py` — Rappler spider (supports `/latest` pages)
- `philstar.py` — Philstar spider (filters out unwanted sections such as `/forex-stocks/`)
- `manilabulletin.py` — Manila Bulletin spider

## Testing tips
- If you only want to import spiders without touching the DB, set `SKIP_DB_CREATE=1` in your environment so `app.db.init_db()` does not attempt DB creation.
- Ensure `bs4` and `scrapy` are installed in your virtualenv.

## Troubleshooting
- If the runner complains about missing DB drivers (e.g. `No module named 'mysql'`), install the proper DB driver or use `SKIP_DB_CREATE=1` for local testing.
- If you run into Twisted reactor issues on Windows, run spiders in separate processes (the Flask app already spawns separate processes for web-triggered runs).