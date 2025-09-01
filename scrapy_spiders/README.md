# scrapy_spiders

This package contains the programmatic Scrapy runner, spiders, database helpers and pipeline used by the surrounding Flask application. It is intended to run Scrapy spiders (one per news site) and persist scraped Article items into the existing Flask/SQLAlchemy database via a Scrapy pipeline.

## Goal / Contract
- Inputs: site-specific listing pages and article pages fetched by Scrapy.
- Outputs: dictionaries/items (title, url, content, author, published_date, source) written to the Flask SQLAlchemy `Article` model by `SQLAlchemyPipeline`.
- Error modes: spiders should skip URLs that already exist in the DB, and pipeline preserves non-fatal exceptions (logs and continues).
- Success: spiders crawl pages, yield items, and pipeline persists Articles and updates `ScrapeJob` counts.

## Layout
- `runner.py` — Programmatic entry point to run spiders (contains `main()` that builds a `CrawlerProcess` and starts spiders). Handles Twisted reactor quirks (Windows) and applies project-level Scrapy settings such as the SQLAlchemy pipeline.

- `pipelines.py` — `SQLAlchemyPipeline` that receives Scrapy items and writes them into the Flask app database using the Flask application context and the project's models.

- `db.py` — Lightweight helpers for URL normalization and a `preload_existing_urls()` function used by spiders to cache existing URLs in memory for fast dedup checks. Note: calling `preload_existing_urls()` triggers Flask app initialization (it reads the DB). Spiders call this at instance init time.

- `spiders/` — Contains site-specific Scrapy spiders. Each spider is self-contained and implements:
  - `start_requests()` — generate listing page URLs (multi-page support)
  - `parse_listing()` — extract article URLs from listing pages
  - `parse_article()` — scrape article content and return an item/dict

  Files:
  - `pna.py` — PNA spider (includes author cleaning and date parsing)
  - `rappler.py` — Rappler spider (supports /latest pages and date parsing)
  - `philstar.py` — Philstar spider (section path filtering like `/forex-stocks/`)
  - `manilabulletin.py` — Manila Bulletin spider

## Key behaviors and notes
- URL deduplication: spiders call `preload_existing_urls()` (or `url_exists()`) to avoid scheduling article pages already present in the DB. Normalization logic lives in `db.py`.

- Pipeline integration: `pipelines.SQLAlchemyPipeline` expects to run inside the same Python environment that can import the Flask app; it uses the Flask app context to create and commit `Article` objects.

- Runner settings: `runner.py` sets a conservative default `CONCURRENT_REQUESTS`, `DOWNLOAD_DELAY`, and enables `SQLAlchemyPipeline` by default when running via the runner. The runner's CLI supports `--pages`, `--limit`, and `--job-id` arguments.

- Twisted/reactor: The runner contains a small compatibility guard for Twisted reactor implementations that lack `_handleSignals` (observed on some Windows setups).

- Database initialization side effects: `preload_existing_urls()` will initialize the Flask/SQLAlchemy app (calls `create_app()`), which may create database engines and require DB drivers (e.g. `mysql-connector-python` if your `DATABASE_URL` is MySQL). To avoid initializing DB at import time, spiders call `preload_existing_urls()` in their `__init__` blocks rather than as a top-level import action.

- Environment flags that may be useful during testing:
  - `SKIP_DB_CREATE=1` — when set, `app.db.init_db()` skips creating DB tables (useful for quick local tests when DB is not available).

## Requirements
- Python 3.8+ (project uses 3.12 elsewhere)
- Scrapy
- BeautifulSoup4 (used inside spiders for HTML parsing)
- Flask & Flask-SQLAlchemy (project-level)
- SQLAlchemy
- Database driver matching your `DATABASE_URL` (e.g. `mysql-connector-python` for MySQL)

Check the project's top-level `requirements.txt` for exact pins.

## Running
From the project root you can run the programmatic runner to execute a single spider (example shown for PowerShell):

```powershell
# Run the Rappler spider for 2 pages
python -m scrapy_spiders.runner rappler --pages 2 --limit 0

# Run a single spider (pna) with a 1-page listing and limit 5 article fetches
python -m scrapy_spiders.runner pna --pages 1 --limit 5

# Run all spiders sequentially
python -m scrapy_spiders.runner all --pages 2
```

When the runner starts it will set the pipeline to `scrapy_spiders.pipelines.SQLAlchemyPipeline` so scraped items are saved to the Flask DB.

## Programmatic usage
The `runner.py` module is designed as a CLI entrypoint. If you need to launch spiders programmatically from your Flask app (the project already contains logic to do this), call into the project's runner or use Scrapy's `CrawlerProcess` directly and pass the Spider classes that live under `scrapy_spiders.spiders`.

Example (conceptual):
```python
# inside your Flask view / background task
from scrapy_spiders.spiders.pna import PNASpider
from scrapy.crawler import CrawlerProcess

process = CrawlerProcess(settings)
process.crawl(PNASpider, pages=1, limit=5, job_id=42)
process.start()
```

Note: The project already contains a tested programmatic runner and a Flask view that launches spiders in background processes.

## Troubleshooting
- Import-time errors complaining about missing DB drivers (e.g. "No module named 'mysql'"): install the appropriate DB driver or set `SKIP_DB_CREATE=1` in your environment when running simple import-tests.

- Twisted reactor errors on Windows: use the provided `runner.py` (it guards against missing `_handleSignals`) or run spiders in separate processes (the Flask views in this project spawn separate processes per spider to avoid reactor conflicts).

- If spider imports fail after moving code, ensure `bs4` (BeautifulSoup) and `scrapy` are installed in the environment.

## Where to look next
- `scrapy_spiders/pipelines.py` — pipeline-to-DB wiring and any site-specific item normalization
- `scrapy_spiders/db.py` — url normalization and caching behavior
- `scrapy_spiders/runner.py` — runner CLI, Scrapy settings and Twisted compatibility
- `scrapy_spiders/spiders/*.py` — site-specific extraction logic

## Summary
This package provides a compact, maintainable Scrapy-based scraping layer that re-uses the Flask app's database and models via an SQLAlchemy pipeline. Spiders are now self-contained and ready to run either from the included `runner.py` or from the Flask app entrypoints.
