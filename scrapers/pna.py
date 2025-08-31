from .base import BaseScraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from datetime import datetime


class PNAScraper(BaseScraper):
    LISTING_URL = "https://www.pna.gov.ph/"

    def list_pages(self, max_pages=2):
        """Yield HTML for the homepage and common category archive pages.

        Pagination is attempted with common patterns like /page/N/ under
        category paths.
        """
        # homepage
        resp = self.get(self.LISTING_URL)
        if resp is not None:
            yield resp.text

        # include category index pages seen in the site's nav
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
            "categories/foi"
        ]

        for slug in categories:
            for p in range(1, max_pages + 1):
                if p == 1:
                    url = urljoin(self.LISTING_URL, slug)
                else:
                    # PNA uses query-style paging like ?p=2
                    url = urljoin(self.LISTING_URL, f"{slug}?p={p}")

                resp = self.get(url)
                if resp is None:
                    continue
                yield resp.text

    def parse_listing(self, html):
        s = BeautifulSoup(html, "lxml")
        seen = set()

        # Primary: links under /articles/ which are standard news items
        for a in s.select("a[href]"):
            href = a.get("href")
            if not href:
                continue

            # normalize relative URLs
            full = urljoin(self.LISTING_URL, href)

            # skip external/social links
            if any(domain in full for domain in ("facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be", "t.co")):
                continue

            # Accept article URLs (pattern /articles/<id>) or opinion pieces
            if re.search(r"/articles/\d+", full) or re.search(r"/opinion/pieces/", full) or re.search(r"/opinion/", full):
                if full not in seen:
                    seen.add(full)
                    yield full

        # Fallback: find anchors that look like article detail pages based on path length
        for a in s.find_all("a", href=True):
            href = a.get("href")
            full = urljoin(self.LISTING_URL, href)
            if full in seen:
                continue
            # quick heuristic: /articles/<numeric> or paths with 'articles' segment
            if "/articles/" in full:
                seen.add(full)
                yield full

    def parse_article(self, html, url):
        s = BeautifulSoup(html, "lxml")

        # Title: prefer og:title then h1
        title = None
        t_meta = s.find("meta", property="og:title") or s.find("meta", attrs={"name": "og:title"})
        if t_meta and t_meta.get("content"):
            title = t_meta.get("content")
        else:
            h1 = s.find("h1")
            title = h1.get_text(strip=True) if h1 else None

        # Description
        description = None
        desc = s.find("meta", attrs={"name": "description"}) or s.find("meta", property="og:description")
        if desc and desc.get("content"):
            description = desc.get("content")

        # Author: meta author or common byline selectors.
        # If missing, look inside the article title area for a paragraph or span
        # that begins with 'By ' and extract the remainder as the author name.
        author = None
        a_meta = s.find("meta", attrs={"name": "author"})
        if a_meta and a_meta.get("content"):
            author = a_meta.get("content")
        else:
            a_tag = s.select_one(".author, .byline, .credit, .article-author, .writer")
            if a_tag:
                author = a_tag.get_text(strip=True)
            else:
                # scan the article-title area first for 'By ...' patterns
                container = s.select_one(".article-title, #article-view, .article, main")
                if container:
                    for el in container.find_all(["p", "div", "span"], recursive=True):
                        txt = el.get_text(" ", strip=True)
                        m = re.match(r"^\s*By\s+(.+)$", txt, re.I)
                        if m:
                            author = m.group(1).strip()
                            break

                # fallback: search anywhere on the page for a 'By ' text node
                if not author:
                    by = s.find(text=re.compile(r"^\s*By\s+", re.I))
                    if by:
                        m = re.match(r"^\s*By\s+(.+)$", by.strip(), re.I)
                        if m:
                            author = m.group(1).strip()

        # Date: look for meta article:published_time, time tags, or 'Date Posted:' text
        date = None
        d_meta = s.find("meta", property="article:published_time") or s.find("meta", attrs={"name": "article:published_time"})
        if d_meta and d_meta.get("content"):
            date = d_meta.get("content")
        else:
            time_tag = s.find("time")
            if time_tag and time_tag.get("datetime"):
                date = time_tag.get("datetime")
            elif time_tag:
                date = time_tag.get_text(strip=True)
            else:
                # search for 'Date Posted:' label shown on the homepage snippets
                label = s.find(text=re.compile(r"Date Posted:\s*", re.I))
                if label:
                    # label may be "Date Posted: August 31, 2025, 9:12 am"
                    m = re.search(r"Date Posted:\s*(.+)", label)
                    if m:
                        date = m.group(1).strip()
                    else:
                        # maybe sibling contains the actual text
                        parent = label.parent
                        if parent and parent.get_text(strip=True):
                            date = parent.get_text(strip=True)

        # Additional fallback: many PNA article pages render the date as plain
        # text near the title (e.g. "August 31, 2025, 9:12 am"). Prefer looking
        # at small, nearby elements (p/span) before searching the whole page.
        if not date:
            date_re = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}(?:[,\s]+\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)?")
            container = s.select_one(".article-title, #article-view, .article, main")
            found = None
            if container:
                # check immediate p/span children first
                for el in container.find_all(["p", "span", "div"], recursive=True):
                    txt = el.get_text(" ", strip=True)
                    if not txt:
                        continue
                    m = date_re.search(txt)
                    if m:
                        found = m.group(0).strip()
                        break
            if not found:
                # last resort: search whole page text
                m = date_re.search(s.get_text(" ", strip=True))
                if m:
                    found = m.group(0).strip()
            if found:
                date = found

        # Content: try common article body selectors, then fallback to many <p>
        content_selectors = [
            "div.article-body",
            "div.article-content",
            "div[itemprop='articleBody']",
            "article .entry-content",
            "main article",
            "article",
        ]
        p_tags = []
        for sel in content_selectors:
            p_tags = s.select(f"{sel} p")
            if p_tags:
                break

        if not p_tags:
            p_tags = s.find_all("p")[:60]

        # filter out short/boilerplate paragraphs
        paragraphs = []
        for p in p_tags:
            text = p.get_text(" ", strip=True)
            if not text:
                continue
            if len(text) < 40:
                # skip tiny bits that are likely navigation/labels
                continue
            # skip repeated social or related prompts
            if re.search(r"(Read more|Related|Subscribe|Follow us)", text, re.I):
                continue
            paragraphs.append(text)

        content = "\n\n".join(paragraphs)

        # normalize date into ISO 8601-like string when possible
        try:
            normalized = self._normalize_date(date)
        except Exception:
            normalized = date

        return {
            "url": url,
            "title": title,
            "author": author,
            "date": normalized,
            "description": description,
            "content": content,
            "source": "pna",
        }

    def _normalize_date(self, date_str):
        """Convert common PNA date strings into ISO 8601 (string) or return original."""
        if not date_str:
            return None
        date_str = date_str.strip()
        # try ISO first
        try:
            # datetime.fromisoformat supports many ISO formats
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            pass

        # common patterns like: August 31, 2025, 9:12 am
        patterns = [
            "%B %d, %Y, %I:%M %p",
            "%B %d, %Y %I:%M %p",
            "%b %d, %Y, %I:%M %p",
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y",
            "%b %d, %Y",
        ]
        for p in patterns:
            try:
                dt = datetime.strptime(date_str, p)
                return dt.isoformat()
            except Exception:
                continue

        # regex fallback to extract components
        m = re.search(r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?P<day>\d{1,2}),?\s*(?P<year>\d{4})(?:[,\s]+(?P<hour>\d{1,2}):(?P<min>\d{2})\s*(?P<ampm>am|pm|AM|PM)?)?")
        if m:
            month = m.group('month')
            day = int(m.group('day'))
            year = int(m.group('year'))
            hour = 0
            minute = 0
            if m.group('hour'):
                hour = int(m.group('hour'))
                minute = int(m.group('min') or 0)
                ampm = m.group('ampm')
                if ampm:
                    if ampm.lower() == 'pm' and hour != 12:
                        hour += 12
                    if ampm.lower() == 'am' and hour == 12:
                        hour = 0
            # resolve month name
            try:
                month_num = datetime.strptime(month, "%B").month
            except Exception:
                try:
                    month_num = datetime.strptime(month, "%b").month
                except Exception:
                    month_num = 1
            try:
                dt = datetime(year, month_num, day, hour, minute)
                return dt.isoformat()
            except Exception:
                return date_str

        # give up and return original
        return date_str
