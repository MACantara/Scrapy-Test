"""Scaffold a new spider file in scrapy_spiders/spiders

Usage:
    python scripts/create_spider.py name --listing-url URL [--source NAME] [--force]

This will create: scrapy_spiders/spiders/<name>.py

It does not automatically register the spider with runner.py; see printed next steps.
"""
from __future__ import annotations
import argparse
import os
import re

TEMPLATE = '''import scrapy
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime

class {class_name}(scrapy.Spider):
    name = "{name}"
    LISTING_URL = "{listing_url}"

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
                url = urljoin(self.LISTING_URL, "page/{{p}}/")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(self.LISTING_URL, href)
            if url_exists(href):
                continue
            yield scrapy.Request(href, callback=self.parse_article)

    def parse_article(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        title = (soup.find('h1') or soup.find('title')).get_text(strip=True) if soup else 'No title'
        content = (soup.find('div', class_='article-body') or soup).get_text(strip=True) if soup else ''
        author = None
        published_date = None
        # TODO: customize selectors and normalization for this site
        yield {{
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            'date': published_date,
            'published_date': published_date,
            'source': '{source}'
        }}
'''


def slug_to_class(name: str) -> str:
    # convert snake/hyphen to CamelCase and append Spider
    name = name.strip().replace('-', '_')
    parts = [p for p in re.split('[^a-zA-Z0-9]', name) if p]
    camel = ''.join(p.capitalize() for p in parts) or 'New'
    return f"{camel}Spider"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name', help='spider name (file will be name.py and spider.name will be this)')
    parser.add_argument('--listing-url', '-u', required=True, help='base listing URL')
    parser.add_argument('--source', '-s', default=None, help='human-readable source name used in items')
    parser.add_argument('--force', '-f', action='store_true', help='overwrite existing spider file')
    args = parser.parse_args()

    spiders_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scrapy_spiders', 'spiders')
    os.makedirs(spiders_dir, exist_ok=True)

    filename = f"{args.name}.py"
    path = os.path.join(spiders_dir, filename)

    if os.path.exists(path) and not args.force:
        print(f"Error: {path} already exists. Use --force to overwrite.")
        raise SystemExit(1)

    class_name = slug_to_class(args.name)
    source = args.source if args.source is not None else args.name.capitalize()

    content = TEMPLATE.format(class_name=class_name, name=args.name, listing_url=args.listing_url, source=source)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Created spider file: {path}")
    print("Next steps:")
    print(f"  - Open {path} and update selectors in parse_listing/parse_article as needed.")
    print("  - Optionally import and register the spider in scrapy_spiders/runner.py by adding:")
    print(f"      from scrapy_spiders.spiders.{args.name} import {class_name}")
    print("    and adding an entry to AVAILABLE mapping: 'yourname': YourClass")


if __name__ == '__main__':
    main()
