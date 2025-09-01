import scrapy
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
import re
from datetime import datetime

class PNASpider(scrapy.Spider):
    name = "pna"
    LISTING_URL = "https://www.pna.gov.ph/"
    DEFAULT_MAX_PAGES = 10000

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.DEFAULT_MAX_PAGES
        # homepage
        yield scrapy.Request(self.LISTING_URL, callback=self.parse_listing)

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
                    url = urljoin(self.LISTING_URL, slug)
                else:
                    url = urljoin(self.LISTING_URL, f"{slug}?p={p}")
                yield scrapy.Request(url, callback=self.parse_listing)

        # latest
        for p in range(1, cap + 1):
            if p == 1:
                url = urljoin(self.LISTING_URL, "latest")
            else:
                url = urljoin(self.LISTING_URL, f"latest?p={p}")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        """Parse PNA listing page and extract article URLs"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links in the listing
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/news/' in href and href.startswith('https://www.pna.gov.ph/'):
                links.append(href)
        
        for link in links:
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        """Parse individual PNA article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1', class_='entry-title')
        title = title_tag.get_text(strip=True) if title_tag else "No title"
        
        # Get content
        content_div = soup.find('div', class_='entry-content')
        content = content_div.get_text(strip=True) if content_div else "No content"
        
        # Get author
        author_tag = soup.find('span', class_='author')
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"
        
        # Get date
        date_tag = soup.find('time', class_='entry-date')
        published_date = None
        if date_tag:
            date_str = date_tag.get('datetime', '').strip()
            try:
                published_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
            except ValueError:
                pass
        
        # Clean author field: remove trailing dates and sharing UI text
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
            m = re.search(r"\d{4}", s)
            if m:
                s = s[:m.start()].strip(' ,;')

            author = s or "Unknown"
        
        yield {
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            'published_date': published_date,
            'source': 'PNA'
        }
