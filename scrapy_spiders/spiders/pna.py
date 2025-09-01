import scrapy
from scrapers.pna import PNAScraper
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls

class PNASpider(scrapy.Spider):
    name = "pna"

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        self.scraper = PNAScraper()
    preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.scraper.DEFAULT_MAX_PAGES
        # homepage
        yield scrapy.Request(self.scraper.LISTING_URL, callback=self.parse_listing)

        # categories
        categories = [
            "categories/national",
            "categories/provincial",
            "categories/business",
            "categories/features",
            "categories/health-and-lifestyle",
            "categories/foreign",
            "categories/sports",
            "categories/travel-and-tourism",
            "categories/environment",
            "categories/science-and-technology",
            "categories/arts-and-entertainment",
            "categories/sona-2025",
            "categories/bagong-pilipinas",
            "categories/events",
            "categories/media-security",
            "categories/foi",
        ]
        for slug in categories:
            for p in range(1, cap + 1):
                if p == 1:
                    url = urljoin(self.scraper.LISTING_URL, slug)
                else:
                    url = urljoin(self.scraper.LISTING_URL, f"{slug}?p={p}")
                yield scrapy.Request(url, callback=self.parse_listing)

        # latest
        for p in range(1, cap + 1):
            if p == 1:
                url = urljoin(self.scraper.LISTING_URL, "latest")
            else:
                url = urljoin(self.scraper.LISTING_URL, f"latest?p={p}")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        html = response.text
        for link in self.scraper.parse_listing(html):
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        data = self.scraper.parse_article(response.text, response.url)
        # Clean author field: remove trailing dates and sharing UI text
        try:
            author = data.get('author') if isinstance(data, dict) else None
            if author and isinstance(author, str):
                s = author.strip()
                # normalize nbsp
                s = s.replace('\u00a0', ' ')
                # drop leading 'By '
                if s.lower().startswith('by '):
                    s = s[3:].strip()

                lower = s.lower()
                months = [
                    'january', 'february', 'march', 'april', 'may', 'june',
                    'july', 'august', 'september', 'october', 'november', 'december'
                ]
                markers = ['share', 'x (formerly', 'viber', 'email'] + months
                # find earliest marker occurrence
                idxs = [lower.find(m) for m in markers if lower.find(m) != -1]
                if idxs:
                    cut = min(idxs)
                    s = s[:cut].strip(' ,;-–—')

                # final safety: if the remaining string still contains a 4-digit year,
                # cut at the first digit occurrence
                import re
                m = re.search(r"\d{4}", s)
                if m:
                    s = s[:m.start()].strip(' ,;')

                data['author'] = s or None
        except Exception:
            # non-fatal: keep original author if cleanup fails
            pass

        yield data
