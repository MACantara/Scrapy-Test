import time
import requests
from bs4 import BeautifulSoup


class BaseScraper:
    """Base scraper helpers. Site-specific scrapers should inherit this."""

    USER_AGENT = "ScrapyTestBot/1.0 (+https://example.com)"
    RATE_LIMIT = 1.5  # seconds per request
    # safety cap when a caller requests 'unlimited' paging
    DEFAULT_MAX_PAGES = 10000

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def get(self, url):
        time.sleep(self.RATE_LIMIT)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp

    def soup(self, text):
        return BeautifulSoup(text, "lxml")
