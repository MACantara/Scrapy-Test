"""Simple runner to execute Scrapy spiders programmatically and reuse existing scrapers.

This runner is optional — you can also run Scrapy from the command line once
Scrapy is installed (`scrapy runspider ...`). The spiders below import the
existing `scrapers` package and use their `parse_listing` and `parse_article`
helpers to build items.

Usage (after installing requirements):
    python -m scrapy_spiders.runner <spider_name> [--pages N] [--limit M]

Note: Running Scrapy in the same process as Flask can be tricky due to
Twisted's reactor; use this runner separately.
"""
import sys
import argparse

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Import spider classes directly so we can pass the class to CrawlerProcess.crawl
from scrapy_spiders.spiders.philstar import PhilstarSpider
from scrapy_spiders.spiders.rappler import RapplerSpider
from scrapy_spiders.spiders.manilabulletin import ManilaBulletinSpider
from scrapy_spiders.spiders.pna import PNASpider

AVAILABLE = {
    "philstar": PhilstarSpider,
    "rappler": RapplerSpider,
    "manilabulletin": ManilaBulletinSpider,
    "pna": PNASpider,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spider", choices=list(AVAILABLE.keys()) + ["all"]) 
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--job-id", type=int, default=0)
    args = parser.parse_args()

    # override/add Scrapy settings: enable our pipeline and set conservative concurrency
    settings = get_project_settings()
    custom = {
        "ITEM_PIPELINES": {
            "scrapy_spiders.pipelines.SQLAlchemyPipeline": 300,
        },
        "CONCURRENT_REQUESTS": 8,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 0.5,
    }
    settings.setdict(custom, priority="cmdline")
    process = CrawlerProcess(settings)

    pages_arg = None if args.pages == 0 else args.pages
    if args.spider == "all":
        for name, cls in AVAILABLE.items():
            process.crawl(cls, pages=pages_arg, limit=args.limit, job_id=args.job_id)
    else:
        process.crawl(AVAILABLE[args.spider], pages=pages_arg, limit=args.limit, job_id=args.job_id)

    # Some Twisted reactor implementations (notably on Windows) don't provide
    # a `_handleSignals` method which `install_shutdown_handlers` expects.
    # To avoid the AttributeError observed when starting the process, ensure
    # the reactor has a no-op `_handleSignals` before calling start().
    try:
        # import reactor here to avoid importing Twisted at module import time
        # if the runner is merely inspected.
        from twisted.internet import reactor as _reactor
        if not hasattr(_reactor, "_handleSignals"):
            _reactor._handleSignals = lambda *a, **kw: None
    except Exception:
        # If Twisted isn't available at this point, allow the error to surface
        # when the runner actually runs; don't mask unrelated problems.
        pass

    process.start()


if __name__ == "__main__":
    main()
