import scrapy
from scrapers.rappler import RapplerScraper
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls

class RapplerSpider(scrapy.Spider):
    name = "rappler"

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        self.scraper = RapplerScraper()
    preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.scraper.DEFAULT_MAX_PAGES
        # homepage/root
        for p in range(1, cap + 1):
            if p == 1:
                url = self.scraper.LISTING_URL
            else:
                url = urljoin(self.scraper.LISTING_URL, f"page/{p}/")
            yield scrapy.Request(url, callback=self.parse_listing)

        # latest section
        for p in range(1, cap + 1):
            if p == 1:
                url = urljoin(self.scraper.LISTING_URL, "latest")
            else:
                url = urljoin(self.scraper.LISTING_URL, f"latest/page/{p}/")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        html = response.text
        for link in self.scraper.parse_listing(html):
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        data = self.scraper.parse_article(response.text, response.url)
        yield data
