from app import create_app
from app.models import Article
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from functools import lru_cache


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


# Module-level cache of existing URLs (normalized), populated by preload_existing_urls()
EXISTING_URLS = None


def get_existing_urls() -> set:
    """Load all Article.url values from the DB and return a set of normalized URLs."""
    app = create_app()
    with app.app_context():
        rows = Article.query.with_entities(Article.url).all()
        return set(r[0] for r in rows if r[0])


def preload_existing_urls():
    """Populate the module-level EXISTING_URLS set and return it."""
    global EXISTING_URLS
    if EXISTING_URLS is None:
        EXISTING_URLS = set(_normalize_url(u) for u in get_existing_urls())
    return EXISTING_URLS


@lru_cache(maxsize=8192)
def url_exists(url: str) -> bool:
    """Return True if the given URL exists in DB or in the preloaded set.

    The function normalizes the URL first. If `preload_existing_urls` has been
    called, the check is O(1) against the in-memory set. Otherwise, it falls
    back to a DB query and caches the result.
    """
    if not url:
        return False
    n = _normalize_url(url)
    if EXISTING_URLS is not None:
        return n in EXISTING_URLS
    # fallback to DB query
    app = create_app()
    with app.app_context():
        return Article.query.filter_by(url=n).first() is not None
