import scrapy
from urllib.parse import urljoin, urlparse
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio
try:
    from scrapy_playwright.page import PageMethod
    try:
        from scrapy_playwright.request import PlaywrightRequest  # type: ignore
    except Exception:
        PlaywrightRequest = None
except Exception:
    PageMethod = None
    PlaywrightRequest = None

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
        # If Playwright is available, render listings and simulate scrolling
        if PageMethod:
            # helper PageMethod will scroll the page 'cap' times (or pages argument)
            # until articles load. Use a simple selector that matches article nodes.
            pm = PageMethod(self._scroll_and_wait, 'article', cap, 1000)
            meta = {'playwright': True, 'playwright_page_methods': [pm]}
            # yield the homepage and let the page method perform scrolling to load more
            yield (PlaywrightRequest(self.LISTING_URL, callback=self.parse_listing, meta=meta)
                   if PlaywrightRequest else scrapy.Request(self.LISTING_URL, callback=self.parse_listing, meta=meta))
        else:
            # fallback: existing lazy.php pagination
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
            # For categories prefer Playwright scrolling as well when available
            if PageMethod:
                pm = PageMethod(self._scroll_and_wait, 'article', cap, 1000)
                meta = {'playwright': True, 'playwright_page_methods': [pm]}
                yield (PlaywrightRequest(cat, callback=self.parse_listing, meta=meta)
                       if PlaywrightRequest else scrapy.Request(cat, callback=self.parse_listing, meta=meta))
            else:
                for p in range(1, cap + 1):
                    if p == 1:
                        url = cat
                    else:
                        url = f"{cat}?page={p}"
                    yield scrapy.Request(url, callback=self.parse_listing)


    async def _scroll_and_wait(self, page, selector, max_scrolls=2, pause_ms=1000):
        """Scroll the page up to max_scrolls times, waiting pause_ms between scrolls.

        Return True when an element matching `selector` is present, else None.
        This is intended to be passed to Playwright PageMethod so listings loaded by
        infinite-scroll get appended before Scrapy parses the rendered HTML.
        """
        for i in range(int(max_scrolls) if max_scrolls else 1):
            try:
                # small wait to allow initial content
                await asyncio.sleep(pause_ms / 1000)
                found = await page.query_selector(selector)
                if found:
                    return True
                # scroll to bottom and wait for network/activity
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(pause_ms / 1000)
                found = await page.query_selector(selector)
                if found:
                    return True
            except Exception:
                continue
        return None

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

            # Prefer Playwright for article pages so client-side markup (article body, date)
            # is available. If Playwright isn't installed the meta flags are harmless.
            if PageMethod:
                # use the same scrolling/wait helper to ensure article body exists
                pm_article = PageMethod(self._scroll_and_wait, '.article__writeup, #sports_article_writeup, .article__writeup p', 2, 800)
                meta = {'playwright': True, 'playwright_page_methods': [pm_article]}
                if PlaywrightRequest:
                    yield PlaywrightRequest(link, callback=self.parse_article, meta=meta)
                else:
                    yield scrapy.Request(link, callback=self.parse_article, meta=meta)
            else:
                yield scrapy.Request(link, callback=self.parse_article)

    def parse_article(self, response):
        """Parse individual Philstar article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1') or soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else "No title"
        
        # Get content — prefer the site-specific article writeup container used on Philstar
        content = None
        # Try JSON-LD articleBody first
        try:
            import json
            ld = soup.find('script', type='application/ld+json')
            if ld:
                data = json.loads(ld.string)
                # JSON-LD can be a list or dict
                if isinstance(data, list):
                    for entry in data:
                        if entry.get('@type') in ('NewsArticle', 'Article'):
                            content = entry.get('articleBody') or content
                            break
                elif isinstance(data, dict) and data.get('@type') in ('NewsArticle', 'Article'):
                    content = data.get('articleBody') or content
        except Exception:
            content = content

        if not content:
            content_div = (soup.find(id='sports_article_writeup')
                           or soup.find('div', class_='article__writeup')
                           or soup.find('div', class_='article-writeup')
                           or soup.find('div', class_='article-content')
                           or soup.find('div', class_='content'))
            if content_div:
                # join paragraph texts to preserve spacing
                ps = content_div.find_all('p')
                if ps:
                    content = '\n\n'.join(p.get_text(strip=True) for p in ps if p.get_text(strip=True))
                else:
                    content = content_div.get_text(separator=' ', strip=True)

        if not content:
            content = "No content"
        
        # Get author
        author_tag = soup.find('span', class_='author') or soup.find('div', class_='byline')
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"
        
        # Get date — prefer JSON-LD or the article__date-published text
        published_date = None
        date_iso = None
        # try JSON-LD first
        try:
            import json
            ld = soup.find('script', type='application/ld+json')
            if ld:
                data = json.loads(ld.string)
                if isinstance(data, list):
                    for entry in data:
                        if entry.get('@type') in ('NewsArticle', 'Article'):
                            date_iso = entry.get('datePublished') or date_iso
                            break
                elif isinstance(data, dict) and data.get('@type') in ('NewsArticle', 'Article'):
                    date_iso = data.get('datePublished') or date_iso
        except Exception:
            date_iso = date_iso

        if not date_iso:
            # look for site-specific date string
            date_tag = soup.find('div', class_='article__date-published') or soup.find('time') or soup.find('span', class_='date')
            if date_tag:
                date_str = date_tag.get_text(strip=True)
                # common format: "August 30, 2025 | 2:01pm"
                try:
                    if '|' in date_str:
                        left, right = [s.strip() for s in date_str.split('|', 1)]
                        # parse left as date and right as time
                        dt = datetime.strptime(f"{left} {right}", '%B %d, %Y %I:%M%p')
                        date_iso = dt.isoformat()
                    else:
                        # try with only date
                        dt = datetime.strptime(date_str, '%B %d, %Y')
                        date_iso = dt.date().isoformat()
                except Exception:
                    date_iso = None

        # Normalize published_date into Python date (kept for backward compatibility) and set ISO `date`
        if date_iso:
            try:
                # if already ISO-like including time
                if 'T' in date_iso:
                    dt = datetime.fromisoformat(date_iso.replace('Z', '+00:00'))
                    published_date = dt
                    date_iso = dt.isoformat()
                else:
                    # date only
                    published_date = datetime.fromisoformat(date_iso).date()
            except Exception:
                published_date = None
        
        yield {
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            'date': date_iso,
            'published_date': published_date,
            'source': 'Philstar'
        }
