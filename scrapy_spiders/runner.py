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
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime as _dt
import os
import sys
import threading
import subprocess
import tempfile
import zipfile
import time
from urllib.parse import urlparse

from scrapy import signals
from pydispatch import dispatcher

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
        "CONCURRENT_REQUESTS": 16,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 2,
        # scrapy-playwright integration
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
    }
    settings.setdict(custom, priority="cmdline")
    process = CrawlerProcess(settings)

    # Backup policy: create a zipped MySQL dump every BACKUP_EVERY items scraped
    BACKUP_EVERY = 5000
    _scraped_count = {"count": 0}
    _backup_lock = threading.Lock()
    _is_backing_up = {"val": False}

    def _parse_db_uri(dburi: str):
        """Parse a SQLAlchemy- or mysql-style URI into components.

        Returns dict with keys: user, password, host, port, dbname
        """
        if not dburi:
            return None
        try:
            # strip SQLAlchemy prefix if present (mysql+pymysql://user:pw@host:port/db)
            if '://' in dburi:
                parsed = urlparse(dburi)
                user = parsed.username
                password = parsed.password
                host = parsed.hostname or 'localhost'
                port = parsed.port or 3306
                dbname = parsed.path.lstrip('/') if parsed.path else None
                return {"user": user, "password": password, "host": host, "port": port, "dbname": dbname}
        except Exception:
            return None

    def _create_zipped_backup(user, password, host, port, dbname, job_id=None):
        """Run mysqldump and zip the result into backups/ with a timestamp.

        Runs in a background thread to avoid blocking the reactor.
        """
        try:
            os.makedirs('backups', exist_ok=True)
            ts = _dt.utcnow().strftime('%Y%m%dT%H%M%SZ')
            base_name = f"backup_{dbname}_{ts}"
            if job_id:
                base_name += f"_job{job_id}"
            dump_path = os.path.join(tempfile.gettempdir(), base_name + '.sql')
            zip_path = os.path.join('backups', base_name + '.zip')

            cmd = [
                'mysqldump',
                '-h', str(host),
                '-P', str(port),
                '-u', str(user),
                f"-p{password}" if password is not None and password != '' else '-p',
                dbname,
            ]

            # If password empty string, avoid leaving '-p' without value which prompts; instead omit -p
            if password is None or password == '':
                cmd = [c for c in cmd if not (isinstance(c, str) and c.startswith('-p'))]

            with open(dump_path, 'wb') as dumpf:
                proc = subprocess.Popen(cmd, stdout=dumpf, stderr=subprocess.PIPE)
                _, stderr = proc.communicate()
                if proc.returncode != 0:
                    print(f"mysqldump failed: {stderr.decode(errors='ignore')}", file=sys.stderr)
                    try:
                        os.remove(dump_path)
                    except Exception:
                        pass
                    return False

            # Zip the dump
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(dump_path, arcname=os.path.basename(dump_path))

            # remove temporary dump
            try:
                os.remove(dump_path)
            except Exception:
                pass

            print(f"Created DB backup {zip_path}")
            return True
        except FileNotFoundError:
            print("mysqldump not found; skipping DB backup", file=sys.stderr)
            return False
        except Exception as exc:
            print(f"DB backup failed: {exc}", file=sys.stderr)
            return False

    def _maybe_trigger_backup(job_id=None):
        # Try to discover DB URI from Flask app config first, then environment
        dburi = None
        try:
            from app import create_app
            app = create_app()
            dburi = app.config.get('SQLALCHEMY_DATABASE_URI')
        except Exception:
            dburi = os.environ.get('SQLALCHEMY_DATABASE_URI') or os.environ.get('DATABASE_URL')

        creds = _parse_db_uri(dburi) if dburi else None
        if not creds:
            # look for individual env vars
            user = os.environ.get('MYSQL_USER') or os.environ.get('DB_USER')
            password = os.environ.get('MYSQL_PASSWORD') or os.environ.get('DB_PASSWORD')
            host = os.environ.get('MYSQL_HOST') or os.environ.get('DB_HOST') or 'localhost'
            port = int(os.environ.get('MYSQL_PORT') or os.environ.get('DB_PORT') or 3306)
            dbname = os.environ.get('MYSQL_DB') or os.environ.get('DB_NAME')
            if user and dbname:
                creds = {"user": user, "password": password, "host": host, "port": port, "dbname": dbname}

        if not creds:
            print('No DB credentials available, skipping backup', file=sys.stderr)
            return False

        # Run backup in a background thread
        def _run():
            with _backup_lock:
                _is_backing_up['val'] = True
            try:
                _create_zipped_backup(creds['user'], creds.get('password'), creds['host'], creds.get('port', 3306), creds['dbname'], job_id=job_id)
            finally:
                _is_backing_up['val'] = False

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return True

    # Signal handler for item_scraped
    def _on_item_scraped(item, response, spider):
        try:
            _scraped_count['count'] += 1
            count = _scraped_count['count']
            if count % BACKUP_EVERY == 0:
                # avoid overlapping backups
                if not _is_backing_up['val']:
                    print(f"Scraped {count} items — triggering DB backup...")
                    _maybe_trigger_backup(job_id=args.job_id)
        except Exception as exc:
            print(f"Error in item_scraped handler: {exc}", file=sys.stderr)

    # connect the handler
    dispatcher.connect(_on_item_scraped, signal=signals.item_scraped)

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

    # Start crawling. Capture exceptions so we can mark the ScrapeJob as failed
    success = True
    try:
        process.start()
    except Exception as exc:
        success = False
        print(f"Scrapy runner encountered an error: {exc}", file=sys.stderr)

    # If a job id was provided, update the ScrapeJob status in the Flask DB
    if args.job_id:
        try:
            # Import app factory and models here to avoid importing Flask when not needed
            from app import create_app
            from app.db import db
            from app.models import ScrapeJob
            from datetime import datetime

            app = create_app()
            with app.app_context():
                job = ScrapeJob.query.get(args.job_id)
                if job:
                    job.status = 'finished' if success else 'failed'
                    job.finished_at = datetime.utcnow()
                    # Mark as notified by default; adjust if you have other notification logic
                    try:
                        job.notified = 1
                    except Exception:
                        # If the model doesn't have 'notified', ignore
                        pass
                # Attempt a MySQL backup (zipped) if database config or env vars are available
                def _parse_db_uri(uri: str):
                    # Very small parser for common SQLAlchemy mysql URIs:
                    # mysql://user:pass@host:port/dbname or mysql+pymysql://...
                    try:
                        # strip dialect+driver if present
                        if '://' in uri:
                            scheme, rest = uri.split('://', 1)
                        else:
                            rest = uri
                        # use urlparse for the rest
                        from urllib.parse import urlparse
                        parsed = urlparse('//' + rest)
                        user = parsed.username
                        password = parsed.password
                        host = parsed.hostname or 'localhost'
                        port = str(parsed.port or 3306)
                        db = parsed.path.lstrip('/') if parsed.path else None
                        return user, password, host, port, db
                    except Exception:
                        return (None, None, None, None, None)

                def _create_backup(user, password, host, port, dbname):
                    if not all([user, password, host, port, dbname]):
                        return None
                    backups_dir = Path.cwd() / 'backups'
                    backups_dir.mkdir(parents=True, exist_ok=True)
                    ts = _dt.utcnow().strftime('%Y%m%dT%H%M%SZ')
                    dump_name = f"{dbname}-{ts}.sql"
                    dump_path = backups_dir / dump_name
                    zip_path = backups_dir / f"{dbname}-{ts}.zip"

                    # Build mysqldump command. Prefer MYSQL_PWD in env to avoid leaking in process list
                    env = os.environ.copy()
                    env['MYSQL_PWD'] = password
                    cmd = [
                        'mysqldump',
                        '-h', host,
                        '-P', port,
                        '-u', user,
                        dbname,
                    ]

                    try:
                        with open(dump_path, 'wb') as fh:
                            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=env, check=False)
                        if proc.returncode != 0:
                            # cleanup partial dump
                            try:
                                dump_path.unlink()
                            except Exception:
                                pass
                            return None

                        # zip the dump
                        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                            zf.write(dump_path, arcname=dump_name)

                        # remove plain dump
                        try:
                            dump_path.unlink()
                        except Exception:
                            pass

                        return str(zip_path)
                    except FileNotFoundError:
                        # mysqldump not found
                        return None
                    except Exception:
                        return None

                backed = None
                # First try to read SQLALCHEMY_DATABASE_URI from app config
                dburi = None
                try:
                    dburi = app.config.get('SQLALCHEMY_DATABASE_URI')
                except Exception:
                    dburi = None

                if dburi:
                    u, p, h, po, dbn = _parse_db_uri(dburi)
                    backed = _create_backup(u, p, h, po, dbn)

                # If that failed, fall back to environment variables
                if not backed:
                    u = os.environ.get('MYSQL_USER')
                    p = os.environ.get('MYSQL_PASSWORD') or os.environ.get('MYSQL_PWD')
                    h = os.environ.get('MYSQL_HOST', 'localhost')
                    po = os.environ.get('MYSQL_PORT', '3306')
                    dbn = os.environ.get('MYSQL_DB') or os.environ.get('MYSQL_DATABASE')
                    if u and p and dbn:
                        backed = _create_backup(u, p, h, po, dbn)

                if backed:
                    print(f"Database backup created: {backed}")
                    db.session.commit()
        except Exception as exc:
            print(f"Warning: failed to update ScrapeJob {args.job_id}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
