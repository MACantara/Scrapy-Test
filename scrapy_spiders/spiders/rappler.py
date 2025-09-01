import scrapy
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime

class RapplerSpider(scrapy.Spider):
    name = "rappler"
    LISTING_URL = "https://rappler.com/"
    DEFAULT_MAX_PAGES = 10000

    def __init__(self, pages=2, limit=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = None if pages is None else int(pages)
        self.limit = int(limit)
        preload_existing_urls()

    def start_requests(self):
        cap = self.pages if self.pages is not None else self.DEFAULT_MAX_PAGES
        # homepage/root
        for p in range(1, cap + 1):
            if p == 1:
                url = self.LISTING_URL
            else:
                url = urljoin(self.LISTING_URL, f"page/{p}/")
            yield scrapy.Request(url, callback=self.parse_listing)

        # latest section
        for p in range(1, cap + 1):
            if p == 1:
                url = urljoin(self.LISTING_URL, "latest")
            else:
                url = urljoin(self.LISTING_URL, f"latest/page/{p}/")
            yield scrapy.Request(url, callback=self.parse_listing)

    def parse_listing(self, response):
        """Parse Rappler listing page and extract article URLs"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('https://www.rappler.com/') and '/20' in href:
                links.append(href)
        
        for link in links:
            if url_exists(link):
                continue
            yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        """Parse individual Rappler article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1', class_='post-single__header-title') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "No title"
        
        # Get content
        content_div = soup.find('div', class_='post-content') or soup.find('div', class_='content')
        content = content_div.get_text(strip=True) if content_div else "No content"
        
        # Get author
        author_tag = soup.find('span', class_='post-single__header-reporter') or soup.find('span', class_='author')
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"
        
        # Get date
        date_tag = soup.find('time') or soup.find('span', class_='post-single__header-datetime')
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
            'source': 'Rappler'
        }
