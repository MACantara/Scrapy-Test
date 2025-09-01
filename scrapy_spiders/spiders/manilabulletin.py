import scrapy
try:
    from scrapy_playwright.page import PageMethod
    # some versions of scrapy-playwright expose PlaywrightRequest, others expect
    # you to set the 'playwright' meta on a normal scrapy.Request. Detect availability.
    try:
        from scrapy_playwright.request import PlaywrightRequest  # type: ignore
    except Exception:
        PlaywrightRequest = None
except Exception:
    # scrapy-playwright not installed at all
    PageMethod = None
    PlaywrightRequest = None
from urllib.parse import urljoin
from scrapy_spiders.db import url_exists, preload_existing_urls
from bs4 import BeautifulSoup
from datetime import datetime
import re


async def _wait_for_any_selector(page, selectors, timeout=5000):
    """Playwright page init helper: wait for any selector in the list.

    This is passed to PageMethod as a callable so the download handler
    won't raise if a selector isn't present — it will try each selector
    and return once one is visible.
    """
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout)
            return True
        except Exception:
            continue
    return None

class ManilaBulletinSpider(scrapy.Spider):
    name = "manilabulletin"
    LISTING_URL = "https://mb.com.ph/"
    DEFAULT_MAX_PAGES = 100

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
            # Listings are client-side rendered; prefer Playwright so widgets load
            listing_selectors = [
                '.sw-list-a',
                '.mb-top-headings',
                '.widget-item-headline',
                '.most-popular',
                '#widget_1561',
                '.sw-list-a a',
            ]
            # If PlaywrightRequest class is available use it; otherwise a normal
            # scrapy.Request with meta={'playwright': True, 'playwright_page_methods': [...]}
            if PageMethod:
                pm = PageMethod(_wait_for_any_selector, listing_selectors, 8000)
                meta = {'playwright': True, 'playwright_page_methods': [pm]}
            else:
                meta = {}
            yield (PlaywrightRequest(url, callback=self.parse_listing, meta=meta, dont_filter=True)
                   if PlaywrightRequest else scrapy.Request(url, callback=self.parse_listing, meta=meta))

        # categories
        categories = [
            "https://mb.com.ph/category/national",
            "https://mb.com.ph/category/metro-manila",
            "https://mb.com.ph/category/luzon",
            "https://mb.com.ph/category/visayas",
            "https://mb.com.ph/category/mindanao",
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
                listing_selectors = [
                    '.sw-list-a',
                    '.mb-top-headings',
                    '.widget-item-headline',
                    '.most-popular',
                    '.sw-list-a a',
                ]
                if PageMethod:
                    pm = PageMethod(_wait_for_any_selector, listing_selectors, 8000)
                    meta = {'playwright': True, 'playwright_page_methods': [pm]}
                else:
                    meta = {}
                yield (PlaywrightRequest(url, callback=self.parse_listing, meta=meta, dont_filter=True)
                       if PlaywrightRequest else scrapy.Request(url, callback=self.parse_listing, meta=meta))

    def parse_listing(self, response):
        """Parse ManilaBulletin listing page and extract article URLs"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('https://mb.com.ph/') and '/20' in href:
                links.append(href)
        
        # candidate article-body selectors to wait for before parsing
        candidate_selectors = [
            'div.post-content',
            'div.entry-content',
            'div.article-content',
            'div.article-full-body',
            'div.article-text',
            'article .content',
            'div[itemprop="articleBody"]',
            'div.content',
        ]

        for link in links:
            if url_exists(link):
                continue
            # prefer Playwright if available
            if PageMethod:
                pm = PageMethod(_wait_for_any_selector, candidate_selectors, 8000)
                meta = {'playwright': True, 'playwright_page_methods': [pm]}
            else:
                meta = {}
            yield (PlaywrightRequest(link, callback=self.parse_article, meta=meta, dont_filter=True)
                   if PlaywrightRequest else scrapy.Request(link, callback=self.parse_article, meta=meta))

    def parse_article(self, response):
        """Parse individual ManilaBulletin article"""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Title
        title_tag = soup.find('h1') or soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else "No title"

        # Content: try several selectors and fall back to joining <p> elements
        content = None
        content_selectors = [
            ('div', {'class': 'post-content'}),
            ('div', {'class': 'entry-content'}),
            ('div', {'class': 'article-content'}),
            ('div', {'class': 'article-full-body'}),
            ('article', {}),
            ('div', {'itemprop': 'articleBody'}),
            ('div', {'class': 'content'}),
        ]
        for name, attrs in content_selectors:
            tag = soup.find(name, attrs=attrs if attrs else None)
            if tag:
                # prefer article-text blocks which site uses
                article_texts = tag.find_all('div', class_='article-text')
                if article_texts:
                    parts = []
                    for a in article_texts:
                        t = a.get_text(separator=' ', strip=True)
                        if t:
                            parts.append(t)
                    text = '\n\n'.join(parts).strip()
                    if text:
                        content = text
                        break

                # fallback: gather <p> tags
                ps = tag.find_all('p')
                if ps:
                    text = '\n\n'.join(p.get_text(strip=True) for p in ps if p.get_text(strip=True))
                    if text:
                        content = text
                        break

                txt = tag.get_text(separator=' ', strip=True)
                if txt:
                    content = txt
                    break
        if not content:
            ps = soup.find_all('p')
            if ps:
                content = '\n\n'.join(p.get_text(strip=True) for p in ps if p.get_text(strip=True))
        if not content:
            content = 'No content'

        # Author: meta tag or common selectors
        author = None
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            author = meta_author['content'].strip()
        if not author:
            at = soup.find('span', class_='author') or soup.find('a', rel='author') or soup.find('div', class_='byline')
            if at:
                author = at.get_text(strip=True)
        if not author:
            author = 'Unknown'

        # Date: produce ISO 8601 datetime string where possible
        published_date = None
        date_str = None
        time_tag = soup.find('time')
        if time_tag and (time_tag.get('datetime') or time_tag.get_text(strip=True)):
            date_str = time_tag.get('datetime') or time_tag.get_text(strip=True)
        if not date_str:
            meta_dt = soup.find('meta', attrs={'property': 'article:published_time'})
            if meta_dt and meta_dt.get('content'):
                date_str = meta_dt['content']
        if not date_str:
            # some articles use a span.issue_date containing text like
            # "Published Sep 1, 2025 12:16 pm" — prefer that first
            issue_span = soup.find('span', class_='issue_date')
            if issue_span and issue_span.get_text(strip=True):
                # strip leading 'Published' and similar prefixes
                raw = issue_span.get_text(separator=' ', strip=True)
                date_str = re.sub(r'(?i)^\s*published[:\s\u00A0]*', '', raw).strip()
        if not date_str:
            span_date = soup.find('span', class_='date')
            if span_date:
                date_str = span_date.get_text(strip=True)

        if date_str:
            try:
                dt = None
                # ISO-like strings
                if 'T' in date_str or re.search(r"\d{4}-\d{2}-\d{2}", date_str):
                    # support Z timezone by normalizing to +00:00 for fromisoformat
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    except Exception:
                        dt = None

                if dt is None:
                    # Try a few common human-readable formats, including ones
                    # with time of day like "Sep 1, 2025 12:16 pm".
                    fmts = (
                        '%B %d, %Y %I:%M %p',
                        '%b %d, %Y %I:%M %p',
                        '%B %d, %Y',
                        '%b %d, %Y',
                        '%Y/%m/%d',
                        '%Y-%m-%d',
                    )
                    for fmt in fmts:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            break
                        except Exception:
                            continue

                if dt:
                    # Convert to ISO 8601 string; keep tz if present else naive ISO
                    published_date = dt.isoformat()
            except Exception:
                published_date = None
        
        yield {
            'title': title,
            'url': response.url,
            'content': content,
            'author': author,
            'date': published_date,
            'source': 'Manila Bulletin'
        }
