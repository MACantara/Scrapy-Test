from app import create_app
from app.models import Article
from app.db import db
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def _normalize_url(u: str) -> str:
    if not u:
        return u
    try:
        p = urlparse(u)
    except Exception:
        return u
    scheme = (p.scheme or "http").lower()
    netloc = (p.netloc or "").lower()
    qs = parse_qsl(p.query, keep_blank_values=True)
    filtered = [(k, v) for (k, v) in qs if not (k.startswith("utm_") or k in ("fbclid", "gclid"))]
    query = urlencode(filtered)
    path = p.path or ""
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", query, ""))


class SQLAlchemyPipeline:
    def __init__(self):
        self.app = None
        self.job_id = None

    def open_spider(self, spider):
        # create but don't push the app context here; use a context manager
        # inside process_item because Scrapy may process items in different
        # threads or deferred callbacks.
        self.app = create_app()
        # spider may set job_id attribute when created by the runner
        try:
            self.job_id = getattr(spider, "job_id", None) or (spider.crawler.settings.get("job_id") if getattr(spider, "crawler", None) else None)
        except Exception:
            self.job_id = getattr(spider, "job_id", None)

    def close_spider(self, spider):
        # mark job finished if we have a job id
        if not self.job_id:
            return
        with self.app.app_context():
            from app.models import ScrapeJob
            job = ScrapeJob.query.get(self.job_id)
            if job:
                job.status = "finished"
                job.finished_at = datetime.utcnow()
                db.session.add(job)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    def process_item(self, item, spider):
        # item is expected to be a dict with keys similar to Article fields
        url = item.get("url") or item.get("source_url")
        if not url:
            return item

        normalized = _normalize_url(url)

        # Use a fresh app context for each item to ensure db.session works
        with self.app.app_context():
            # dedupe: skip if we already have this URL
            if Article.query.filter_by(url=normalized).first():
                return item

            art = Article(
                url=normalized,
                title=item.get("title"),
                author=item.get("author"),
                description=item.get("description"),
                content=item.get("content"),
                source=item.get("source") or getattr(spider, "name", None),
            )
            # try parse date
            try:
                if item.get("date"):
                    art.date = datetime.fromisoformat(item.get("date"))
            except Exception:
                pass

            db.session.add(art)
            try:
                db.session.commit()
                # update job count
                if self.job_id:
                    from app.models import ScrapeJob
                    job = ScrapeJob.query.get(self.job_id)
                    if job:
                        job.items_count = (job.items_count or 0) + 1
                        db.session.add(job)
                        try:
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
            except Exception:
                db.session.rollback()

        return item
