from .base import BaseScraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import json


class ManilaBulletinScraper(BaseScraper):
    LISTING_URL = "https://mb.com.ph/"

    def list_pages(self, max_pages=2):
        """Yield HTML for listing pages.

        Strategy:
        - yield the homepage
        - yield a simple homepage ?page=N fallback
        - yield several category listing pages (first page + ?page=N up to max_pages)
        """
        # yield homepage first
        resp = self.get(self.LISTING_URL)
        yield resp.text

        # Simple pagination fallback for homepage
        cap = max_pages if max_pages is not None else self.DEFAULT_MAX_PAGES
        p = 2
        while p <= cap:
            paged = urljoin(self.LISTING_URL, f"?page={p}")
            try:
                resp = self.get(paged)
            except Exception:
                break
            if not resp or not resp.text.strip():
                break
            yield resp.text
            p += 1

        # Additional category listing pages provided by the user
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
            # first page (category root)
            try:
                resp = self.get(cat)
            except Exception:
                continue
            if resp and resp.text.strip():
                yield resp.text

            # subsequent pages for each category
            cap = max_pages if max_pages is not None else self.DEFAULT_MAX_PAGES
            p = 2
            while p <= cap:
                paged = f"{cat}?page={p}"
                try:
                    resp = self.get(paged)
                except Exception:
                    break
                if not resp or not resp.text.strip():
                    break
                yield resp.text
                p += 1

    def parse_listing(self, html):
        """Extract probable article URLs from listing/homepage HTML.
        Apply dedupe and filters: exclude social domains, /author/ paths, and share links.
        """
        s = BeautifulSoup(html, "lxml")
        seen = set()

        article_path_re = re.compile(r"/\d{4}/\d{2}/\d{2}/")
        numeric_id_re = re.compile(r"/\d{6,}")

        def normalize(href):
            if not href:
                return None
            href = href.strip()
            if href.startswith("//"):
                return "https:" + href
            if href.startswith("/"):
                return urljoin(self.LISTING_URL, href)
            if href.startswith("http://") or href.startswith("https://"):
                return href
            return urljoin(self.LISTING_URL, href)

        # Prefer anchors that look like headlines/widgets
        for a in s.select("a[href]"):
            href = a.get("href")
            href = normalize(href)
            if not href:
                continue
            if href in seen:
                continue
            parsed = urlparse(href)
            host = (parsed.netloc or "").lower()

            # exclude social platforms and shorteners
            if any(social in host for social in ("facebook.com", "twitter.com", "x.com", "t.co", "instagram.com", "youtube.com", "youtu.be")):
                continue
            # exclude author profile pages
            if "/author/" in parsed.path:
                continue
            # exclude obvious share/dialog links
            if any(x in href for x in ("/dialog/", "intent/", "share?", "sharethis", "share-button")):
                continue
            # accept only site links
            if "mb.com.ph" not in host and "manilabulletin" not in host:
                continue

            # Heuristics: date path or numeric id
            if article_path_re.search(parsed.path) or numeric_id_re.search(parsed.path):
                seen.add(href)
                yield href

        # As fallback, yield any unique mb links that look promising by path length
        for a in s.select("a[href]"):
            href = a.get("href")
            href = normalize(href)
            if not href or href in seen:
                continue
            parsed = urlparse(href)
            host = (parsed.netloc or "").lower()
            if "mb.com.ph" not in host and "manilabulletin" not in host:
                continue
            if "/author/" in parsed.path:
                continue
            if any(social in host for social in ("facebook.com", "twitter.com", "x.com", "t.co", "instagram.com", "youtube.com", "youtu.be")):
                continue
            # accept paths that have at least two slashes and not root
            if parsed.path and parsed.path.count("/") >= 3:
                seen.add(href)
                yield href

    def parse_article(self, html, url):
        """Parse an article page and return dict with keys expected by the app.
        Prefer JSON-LD for datePublished; fallback to meta tags and visible selectors.
        """
        s = BeautifulSoup(html, "lxml")

        def meta(prop=None, name=None):
            if prop:
                tag = s.find("meta", attrs={"property": prop})
            elif name:
                tag = s.find("meta", attrs={"name": name})
            else:
                return None
            return tag.get("content") if tag and tag.get("content") else None

        title = meta("og:title") or meta(name="title")
        if not title:
            h1 = s.find("h1")
            title = h1.get_text(strip=True) if h1 else (s.title.string.strip() if s.title and s.title.string else None)

        description = None
        date = None
        author = None

        # JSON-LD parsing (prefer article schema)
        try:
            for js in s.find_all("script", attrs={"type": "application/ld+json"}):
                txt = js.string
                if not txt:
                    continue
                try:
                    data = json.loads(txt)
                except Exception:
                    # sometimes there is multiple JSON objects concatenated; try safe extraction
                    try:
                        data = json.loads(re.sub(r"[^\x00-\x7f]", "", txt))
                    except Exception:
                        continue

                def handle_item(item):
                    nonlocal date, title, description, author
                    if not isinstance(item, dict):
                        return
                    typ = item.get("@type") or item.get("type")
                    if isinstance(typ, list):
                        typ = typ[0]
                    if typ and ("Article" in typ or "NewsArticle" in typ or "WebPage" in typ):
                        if not date and item.get("datePublished"):
                            date = item.get("datePublished")
                        if not title and item.get("headline"):
                            title = item.get("headline")
                        if not description and item.get("description"):
                            description = item.get("description")
                        # author may be dict or string
                        a = item.get("author")
                        if a:
                            if isinstance(a, str):
                                author = a
                            elif isinstance(a, dict):
                                author = a.get("name") or author
                            elif isinstance(a, list) and a:
                                first = a[0]
                                if isinstance(first, dict):
                                    author = first.get("name") or author

                if isinstance(data, list):
                    for it in data:
                        handle_item(it)
                else:
                    handle_item(data)

                if date:
                    break
        except Exception:
            date = date or None

        # fallback meta tags and visible selectors
        if not date:
            date = meta("article:published_time") or meta("og:updated_time") or meta(name="DC.date")
            if not date:
                time_tag = s.find("time")
                if time_tag and time_tag.get("datetime"):
                    date = time_tag.get("datetime")
                elif time_tag:
                    date = time_tag.get_text(strip=True)
                else:
                    date_el = s.select_one(".article-date, .publish_date, .published, .date, .post-meta time")
                    if date_el:
                        date = date_el.get_text(strip=True)

        # author fallback
        if not author:
            author = meta(name="author")
            if not author:
                a_el = s.select_one("a[rel=author], .author a, .byline a, .widget-item-author a, .article-author, .author-name")
                if a_el:
                    author = a_el.get_text(strip=True)
                else:
                    # sometimes author is in a span
                    span = s.select_one(".byline, .author, .article__author, .credit")
                    if span:
                        author = span.get_text(strip=True)

        if author and author.strip().startswith("http"):
            author = None

        # description fallback
        if not description:
            description = meta("og:description") or meta(name="description")

        # Content extraction
        content_selectors = [
            ".article-body",
            ".article-content",
            ".entry-content",
            ".post-content",
            ".content",
            "article",
            "#content",
            "#article_body",
        ]

        paragraphs = []
        for sel in content_selectors:
            container = s.select_one(sel)
            if container:
                for p in container.find_all("p"):
                    text = p.get_text(strip=True)
                    if not text:
                        continue
                    # skip common noise
                    low = text.lower()
                    if any(no in low for no in ("advertise", "subscribe", "follow us", "share this", "read more")):
                        continue
                    paragraphs.append(text)
                if paragraphs:
                    break

        if not paragraphs:
            for p in s.find_all("p")[:60]:
                text = p.get_text(strip=True)
                if not text:
                    continue
                low = text.lower()
                if any(no in low for no in ("advertise", "subscribe", "follow us", "share this", "read more")):
                    continue
                paragraphs.append(text)

        content = "\n\n".join(paragraphs)

        return {
            "url": url,
            "title": title,
            "author": author,
            "date": date,
            "description": description,
            "content": content,
            "source": "manilabulletin",
        }
