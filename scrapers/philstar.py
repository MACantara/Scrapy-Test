from .base import BaseScraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import json


class PhilstarScraper(BaseScraper):
    LISTING_URL = "https://www.philstar.com/"

    def list_pages(self, max_pages=2):
        """Yield listing page HTML. Philstar uses lazy pagination; try lazy.php first,
        fall back to simple ?page= query when needed.
        """
        # yield homepage first
        resp = self.get(self.LISTING_URL)
        if resp is not None and resp.text:
            yield resp.text
        cap = max_pages if max_pages is not None else self.DEFAULT_MAX_PAGES
        p = 1
        while p < cap:
            # try the lazy loader endpoint which the homepage references
            lazy_url = urljoin(self.LISTING_URL, f"lazy.php?page={p}&pubid=1")
            resp = self.get(lazy_url)
            # if the lazy loader returns something useful, yield it; otherwise try ?page=
            if resp is None:
                break
            text = resp.text
            if not text.strip():
                # fallback to ?page= style
                fallback = urljoin(self.LISTING_URL, f"?page={p+1}")
                resp = self.get(fallback)
                if not resp:
                    break
                text = resp.text
            yield text
            p += 1

        # Add common section/category listing pages and paginate them
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
            try:
                resp = self.get(cat)
            except Exception:
                continue
            if resp and resp.text.strip():
                yield resp.text

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
        """Extract probable article URLs from a homepage/listing HTML.
        Use a set to dedupe and heuristic URL patterns that match article paths.
        """
        s = BeautifulSoup(html, "lxml")
        seen = set()

        # Candidate selectors that commonly contain article links on the homepage
        selectors = [
            ".carousel__item__title a",
            ".carousel__item a",
            ".news_title a",
            ".ribbon_title a",
            ".tiles a",
            ".ribbon a",
            ".inside_cell a",
            ".TilesText a",
            ".carousel__item__title h2 a",
            ".ribbon_content a",
        ]

        # Regex for typical article URL path (contains a date and/or numeric id)
        article_path_re = re.compile(r"/\d{4}/\d{2}/\d{2}/\d+")
        numeric_id_re = re.compile(r"/\d{6,}")

        def normalize(href):
            if href.startswith("//"):
                return "https:" + href
            if href.startswith("/"):
                return urljoin(self.LISTING_URL, href)
            if href.startswith("http://") or href.startswith("https://"):
                return href
            return urljoin(self.LISTING_URL, href)

        # Sections or prefixes that are not article content and should be skipped
        EXCLUDE_SECTIONS = {"forex-stocks", "market-data", "tools", "ads", "amp"}

        # First, prefer anchors inside known article containers
        for sel in selectors:
            for a in s.select(sel):
                href = a.get("href")
                if not href:
                    continue
                href = normalize(href)
                if href in seen:
                    continue
                # normalized host must be philstar domain
                parsed = urlparse(href)
                host = parsed.netloc.lower()
                # quick exclusion by first path segment (e.g. /forex-stocks/...)
                parts = [p for p in parsed.path.split("/") if p]
                if parts and parts[0] in EXCLUDE_SECTIONS:
                    continue
                # exclude social platforms and shorteners
                if any(social in host for social in ("facebook.com", "twitter.com", "x.com", "t.co", "instagram.com", "youtube.com", "youtu.be")):
                    continue
                # exclude author profile pages and columnist pages
                if "/authors/" in parsed.path or parsed.path.startswith("/columns/") or "/columns/" in parsed.path:
                    continue
                # exclude obvious share/dialog links
                if any(x in href for x in ("/dialog/", "intent/", "share?", "sharethis", "share-button")):
                    continue
                # accept only philstar links
                if "philstar.com" not in host:
                    continue

                # filter to likely article URLs (but avoid known non-article sections)
                if (article_path_re.search(href) or numeric_id_re.search(href)):
                    seen.add(href)
                    yield href

        # As a fallback, scan all anchors and accept ones that match the article heuristics
        for a in s.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            href = normalize(href)
            if href in seen:
                continue
            parsed = urlparse(href)
            host = parsed.netloc.lower()
            parts = [p for p in parsed.path.split("/") if p]
            if parts and parts[0] in EXCLUDE_SECTIONS:
                continue
            if any(social in host for social in ("facebook.com", "twitter.com", "x.com", "t.co", "instagram.com", "youtube.com", "youtu.be")):
                continue
            if "/authors/" in parsed.path or parsed.path.startswith("/columns/") or "/columns/" in parsed.path:
                continue
            if any(x in href for x in ("/dialog/", "intent/", "share?", "sharethis", "share-button")):
                continue
            if "philstar.com" not in host:
                continue
            if article_path_re.search(href) or numeric_id_re.search(href):
                seen.add(href)
                yield href

    def parse_article(self, html, url):
        """Parse an article page and return a dict with fields.
        Uses meta tags as primary source, falls back to common article selectors.
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

        # initialize fields
        description = None
        date = None
        try:
            for js in s.find_all("script", attrs={"type": "application/ld+json"}):
                txt = js.string
                if not txt:
                    continue
                try:
                    data = json.loads(txt)
                except Exception:
                    # sometimes multiple JSON objects or malformed; try to find datePublished by brute force
                    continue
                # data might be a list or dict
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("datePublished"):
                            date = item.get("datePublished")
                            if not title and item.get("headline"):
                                title = item.get("headline")
                            if not description and item.get("description"):
                                description = item.get("description")
                            break
                elif isinstance(data, dict):
                    if data.get("datePublished"):
                        date = data.get("datePublished")
                        if not title and data.get("headline"):
                            title = data.get("headline")
                        if not description and data.get("description"):
                            description = data.get("description")
                if date:
                    break
        except Exception:
            date = None

        # fallback to meta property and visible selectors
        if not date:
            date = meta("article:published_time")
            if not date:
                time_tag = s.find("time")
                if time_tag:
                    date = time_tag.get_text(strip=True)
                else:
                    # look for common date containers
                    date_el = s.select_one(".article__date-published, .dateOfFeature, .inside_cell_elapsed, .article__time, .publish_date, .published")
                    if date_el:
                        date = date_el.get_text(strip=True)

        # Author
        author = meta(name="author")
        if not author:
            # many article pages include author inside credits
            by_el = s.select_one(".article__credits-author-pub, .article__credits, .dateOfFeature, .author, .byline, .article__credits, .credit")
            if by_el:
                a = by_el.find("a")
                author = a.get_text(strip=True) if a else by_el.get_text(strip=True)
        # if author looks like a URL (defensive), null it
        if author and author.strip().startswith("http"):
            author = None

        # Description (meta fallback)
        if not description:
            description = meta("og:description") or meta(name="description")

        # Content: try a list of likely selectors and collect <p> tags
        content_selectors = [
            "#article_body",
            "#article_writeup",
            ".article__writeup",
            ".sports_article_writeup",
            ".news_article_writeup",
            ".article-content",
            ".entry-content",
            ".theContent",
            "article",
            ".post-content",
        ]

        paragraphs = []
        for sel in content_selectors:
            container = s.select_one(sel)
            if container:
                for p in container.find_all("p"):
                    text = p.get_text(strip=True)
                    if text:
                        paragraphs.append(text)
                if paragraphs:
                    break

        # fallback: collect first many <p> on the page (avoid headers/menus)
        if not paragraphs:
            for p in s.find_all("p")[:40]:
                text = p.get_text(strip=True)
                if text:
                    # skip paragraphs that are purely social/embed links
                    if "facebook.com" in text.lower() or "twitter.com" in text.lower() or "philstar.com/authors/" in text:
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
            "source": "philstar",
        }
