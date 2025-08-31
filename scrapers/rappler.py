from .base import BaseScraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class RapplerScraper(BaseScraper):
    LISTING_URL = "https://www.rappler.com/"

    def list_pages(self, max_pages=2):
        # If max_pages is None, treat as unlimited up to DEFAULT_MAX_PAGES
        cap = max_pages if max_pages is not None else self.DEFAULT_MAX_PAGES
        # homepage / root pages
        p = 1
        while p <= cap:
            if p == 1:
                url = self.LISTING_URL
            else:
                url = urljoin(self.LISTING_URL, f"page/{p}/")

            resp = self.get(url)
            if resp is None or not resp.text.strip():
                break
            yield resp.text
            p += 1

        # Include the /latest section which paginates using /latest/page/N/
        p = 1
        while p <= cap:
            if p == 1:
                url = urljoin(self.LISTING_URL, "latest")
            else:
                url = urljoin(self.LISTING_URL, f"latest/page/{p}/")

            resp = self.get(url)
            if resp is None or not resp.text.strip():
                break
            yield resp.text
            p += 1

    def parse_listing(self, html):
        s = BeautifulSoup(html, "lxml")
        seen = set()

        # Rappler renders articles as .post-card elements on category pages
        for card in s.select(".post-card"):
            link = None
            # common title anchor locations
            title_a = card.select_one(
                "h3.post-card__title a, h2.post-card__title a, h3 a, h2 a"
            )
            if title_a and title_a.get("href"):
                link = title_a.get("href")
            else:
                a = card.find("a", href=True)
                if a:
                    link = a.get("href")

            if not link:
                continue

            link = urljoin("https://www.rappler.com", link)
            if link in seen:
                continue
            seen.add(link)
            yield link

    def parse_article(self, html, url):
        s = BeautifulSoup(html, "lxml")

        # Title: prefer og:title meta, then h1
        title = None
        t_meta = s.find("meta", property="og:title")
        if t_meta and t_meta.get("content"):
            title = t_meta.get("content")
        else:
            h1 = s.find("h1")
            title = h1.get_text(strip=True) if h1 else None

        # Author
        author = None
        a_meta = s.find("meta", attrs={"name": "author"})
        if a_meta and a_meta.get("content"):
            author = a_meta.get("content")
        else:
            a_tag = s.select_one(".author, .byline, .byline a, .article-author")
            if a_tag:
                author = a_tag.get_text(strip=True)

        # Published date: try several common metadata locations
        date = None
        d_meta = s.find("meta", property="article:published_time")
        if d_meta and d_meta.get("content"):
            date = d_meta.get("content")
        else:
            time_tag = s.find("time")
            if time_tag and time_tag.get("datetime"):
                date = time_tag.get("datetime")
            elif time_tag:
                date = time_tag.get_text(strip=True)

        # Content: prefer article body selectors used by Rappler, fallback to generic paragraphs
        p_tags = (
            s.select("div[itemprop='articleBody'] p")
            or s.select(".article__content p")
            or s.select("article p")
        )
        content = "\n\n".join(p.get_text(strip=True) for p in p_tags) if p_tags else ""

        if not content:
            # fallback: pick up to the first 40 <p> elements on the page
            ps = s.find_all("p")
            content = "\n\n".join(p.get_text(strip=True) for p in ps[:40])

        # Description: meta description or og:description
        description = None
        desc_tag = s.find("meta", attrs={"name": "description"}) or s.find("meta", property="og:description")
        if desc_tag and desc_tag.get("content"):
            description = desc_tag.get("content")

        return {
            "url": url,
            "title": title,
            "author": author,
            "date": date,
            "description": description,
            "content": content,
            "source": "rappler",
        }
