import scrapy
from scrapers.philstar import PhilstarScraper
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists
from scrapy_spiders.db import preload_existing_urls

class PhilstarSpider(scrapy.Spider):
    name = "philstar"

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        self.scraper = PhilstarScraper()
    # preload existing URLs into memory for fast checks
    preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.scraper.DEFAULT_MAX_PAGES
        # homepage and lazy loader style
        for p in range(1, cap + 1):
            if p == 1:
                url = self.scraper.LISTING_URL
            else:
                url = urljoin(self.scraper.LISTING_URL, f"lazy.php?page={p}&pubid=1")
            yield scrapy.Request(url, callback=self.parse_listing)

        # categories
        categories = [
            "https://www.philstar.com/headlines",
            "https://www.philstar.com/nation",
            "https://www.philstar.com/world",
            "https://www.philstar.com/business",
            "https://www.philstar.com/sports",
            "https://www.philstar.com/entertainment",
            "https://www.philstar.com/lifestyle",
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
            # skip scheduling if URL already exists in DB
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        data = self.scraper.parse_article(response.text, response.url)
        yield data
