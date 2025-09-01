import scrapy
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime

class ManilaBulletinSpider(scrapy.Spider):
    name = "manilabulletin"
    LISTING_URL = "https://mb.com.ph/"
    DEFAULT_MAX_PAGES = 10000

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.DEFAULT_MAX_PAGES
        # homepage
        for p in range(1, cap + 1):
            if p == 1:
                url = self.LISTING_URL
            else:
                url = urljoin(self.LISTING_URL, f"?page={p}")
            yield scrapy.Request(url, callback=self.parse_listing)

        # categories
        categories = [
            "https://mb.com.ph/category/philippines",
            "https://mb.com.ph/category/world",
            "https://mb.com.ph/category/business",
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
        """Parse ManilaBulletin listing page and extract article URLs"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('https://mb.com.ph/') and '/20' in href:
                links.append(href)
        
        for link in links:
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        """Parse individual ManilaBulletin article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1') or soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else "No title"
        
        # Get content
        content_div = soup.find('div', class_='post-content') or soup.find('div', class_='content')
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
            'published_date': published_date,
            'source': 'Manila Bulletin'
        }
