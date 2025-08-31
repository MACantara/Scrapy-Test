import scrapy
from scrapers.manilabulletin import ManilaBulletinScraper
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls

class ManilaBulletinSpider(scrapy.Spider):
    name = "manilabulletin"

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        self.scraper = ManilaBulletinScraper()
    preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.scraper.DEFAULT_MAX_PAGES
        # homepage
        for p in range(1, cap + 1):
            if p == 1:
                url = self.scraper.LISTING_URL
            else:
                url = urljoin(self.scraper.LISTING_URL, f"?page={p}")
            yield scrapy.Request(url, callback=self.parse_listing)

        # categories
        categories = [
            "https://mb.com.ph/category/philippines",
            "https://mb.com.ph/category/world",
            "https://mb.com.ph/category/business",
            "https://mb.com.ph/category/opinion",
            "https://mb.com.ph/category/lifestyle",
            "https://mb.com.ph/category/entertainment",
            "https://mb.com.ph/category/sports",
        ]
        for cat in categories:
            for p in range(1, cap + 1):
                if p == 1:
                    url = cat
                else:
                    url = f"{cat}?page={p}"
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
