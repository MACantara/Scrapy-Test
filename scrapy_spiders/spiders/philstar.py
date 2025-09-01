import scrapy
from urllib.parse import urljoin, urlparse
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime

class PhilstarSpider(scrapy.Spider):
    name = "philstar"
    LISTING_URL = "https://www.philstar.com/"
    DEFAULT_MAX_PAGES = 10000

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.DEFAULT_MAX_PAGES 
        # homepage and lazy loader style
        for p in range(1, cap + 1):
            if p == 1:
                url = self.LISTING_URL
            else:
                url = urljoin(self.LISTING_URL, f"lazy.php?page={p}&pubid=1")
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
        """Parse Philstar listing page and extract article URLs"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        EXCLUDE_SECTIONS = ("/other-sections/", "/forex-stocks/", "/lotto-results/")
        
        # Find all article links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('https://www.philstar.com/') and '/20' in href:
                links.append(href)
        
        for link in links:
            # filter out non-article sections by path
            try:
                p = urlparse(link)
                path = p.path or ""
            except Exception:
                path = ""

            if any(ex in path for ex in EXCLUDE_SECTIONS):
                continue

            # skip scheduling if URL already exists in DB
            if url_exists(link):
                continue

            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        """Parse individual Philstar article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1') or soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else "No title"
        
        # Get content
        content_div = soup.find('div', class_='article-content') or soup.find('div', class_='content')
        content = content_div.get_text(strip=True) if content_div else "No content"
        
        # Get author
        author_tag = soup.find('span', class_='author') or soup.find('div', class_='byline')
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"
        
        # Get date
        date_tag = soup.find('time') or soup.find('span', class_='date')
        published_date = None
        if date_tag:
            date_str = date_tag.get('datetime') or date_tag.get_text(strip=True)
            try:
                if 'T' in date_str:
                    published_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                else:
                    # Try parsing as date string
                    published_date = datetime.strptime(date_str, '%B %d, %Y').date()
            except (ValueError, AttributeError):
                pass
        
        yield {
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            # pipeline expects key 'date'
            'date': published_date,
            'published_date': published_date,
            'source': 'Philstar'
        }
