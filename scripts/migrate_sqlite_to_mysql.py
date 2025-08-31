"""Migration helper: copy data from the project's SQLite DB (instance/articles.db)
into a target MySQL database configured via DATABASE_URL.

Usage:
    set DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname
    python scripts/migrate_sqlite_to_mysql.py

This script uses the app's ORM models and does a best-effort migration suitable
for small development datasets. For larger or production datasets, prefer
database-specific bulk import tools (mysqldump, mysqlpump, or ETL tools).
"""
import os
import sys
from urllib.parse import urlparse

# ensure we import the app factory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import importlib

# Prevent the app factory from calling init_db() (which runs db.create_all())
# during import so we can control table creation for MySQL targets.
import app.db as app_db
_original_init_db = getattr(app_db, 'init_db', None)
app_db.init_db = lambda app: None

# Also set an env var to tell app.db.init_db to skip create_all() as a secondary guard
os.environ['SKIP_DB_CREATE'] = '1'

from app import create_app

# Now import db and models; we will call db.init_app(app) manually later
from app.db import db
from app.models import Article, ScrapeJob

# restore original init_db to avoid side-effects for other code
if _original_init_db is not None:
    app_db.init_db = _original_init_db


def migrate():

    # ensure DATABASE_URL is set and points to MySQL (or other supported SQL)
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('Please set DATABASE_URL to your target DSN, e.g. mysql+mysqlconnector://user:pass@host:3306/db')
        return
    p = urlparse(db_url)
    # accept mysql (with a driver) or postgres schemes
    scheme = p.scheme or ''
    if not (scheme.startswith('mysql') or scheme.startswith('postgres')):
        print('DATABASE_URL must be a MySQL or Postgres DSN (mysql+driver:// or postgresql://). Aborting.')
        return

    # If the user supplied a pymysql DSN, prefer mysql-connector-python instead
    # and rewrite the URL automatically to reduce friction on MySQL 8+ servers.
    if 'pymysql' in db_url and 'mysql' in scheme:
        new_db_url = db_url.replace('pymysql', 'mysqlconnector')
        print('Detected mysql+pymysql DSN; rewriting to use mysql+mysqlconnector for better compatibility with MySQL 8+.')
        print('If you prefer to keep pymysql, set DATABASE_URL explicitly to a pymysql URL before running this script.')
        os.environ['DATABASE_URL'] = new_db_url
        db_url = new_db_url

    # Source SQLite path inside the project 'instance' folder
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    sqlite_path = os.path.abspath(os.path.join(project_root, 'instance', 'articles.db'))
    if not os.path.exists(sqlite_path):
        print('Local SQLite DB not found at', sqlite_path)
        return

    # Create app bound to target DB (Postgres or MySQL)
    os.environ['DATABASE_URL'] = db_url
    app = create_app()

    # initialize SQLAlchemy extension now (app.init_db was monkeypatched earlier)
    try:
        db.init_app(app)
    except RuntimeError as e:
        # If SQLAlchemy was already registered on this app (possible when
        # imports triggered init), continue — we just need a working app context.
        if 'already been registered' in str(e):
            print('SQLAlchemy instance already registered on app; continuing')
        else:
            raise

    # Load data from SQLite using a separate engine
    from sqlalchemy import create_engine
    src_engine = create_engine(f'sqlite:///{sqlite_path}')
    src_conn = src_engine.connect()

    # text() helper for portable SQL execution
    from sqlalchemy import text

    # reflect tables for direct reading if needed
    src_meta = None

    # small helper to coerce various SQLite date formats into Python datetimes
    from datetime import datetime
    try:
        from dateutil import parser as _dateutil_parser  # optional dependency
    except Exception:
        _dateutil_parser = None

    def parse_sqlite_datetime(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        # numeric epoch
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(v)
            except Exception:
                return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            # try ISO first
            try:
                return datetime.fromisoformat(s)
            except Exception:
                pass
            # try dateutil if available
            if _dateutil_parser is not None:
                try:
                    return _dateutil_parser.parse(s)
                except Exception:
                    pass
            # common fallback formats
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue
        return None

    with app.app_context():
        # If target is MySQL, adjust the Article.url column length so the
        # UNIQUE index fits MySQL's index-size limits (utf8mb4 uses 4 bytes/char).
        # Max index bytes for InnoDB is typically 3072, so max chars ≈ 768.
        try:
            if db.engine.dialect.name == 'mysql':
                col = Article.__table__.c.get('url')
                if col is not None:
                    # assign a fresh String(767) to ensure the CREATE TABLE DDL uses
                    # the shorter length (modifying .type.length in-place may not affect DDL).
                    if not getattr(col.type, 'length', None) or getattr(col.type, 'length', 0) > 767:
                        print('Target DB is MySQL: setting Article.url column type to VARCHAR(767) to avoid index size errors')
                        col.type = db.String(767)
        except Exception:
            # if anything goes wrong inspecting the engine, fall back to default behavior
            pass

        # Ensure target DB has tables. For MySQL, create tables with conservative
        # column lengths via raw DDL to avoid index-size problems.
        from sqlalchemy import text
        if db.engine.dialect.name == 'mysql':
            print('Target DB is MySQL: creating tables with adjusted column lengths (url VARCHAR(767))')
            conn = db.engine.connect()
            # Article table with url length 767 (safe for utf8mb4 indexes)
            conn.execute(text('''
            CREATE TABLE IF NOT EXISTS article (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                url VARCHAR(767) NOT NULL,
                title VARCHAR(1000),
                author TEXT,
                date DATETIME,
                description TEXT,
                content TEXT,
                source VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_article_url (url)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            '''))

            # ScrapeJob table
            conn.execute(text('''
            CREATE TABLE IF NOT EXISTS scrape_job (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                spider VARCHAR(200),
                status VARCHAR(50) DEFAULT 'running',
                items_count INT DEFAULT 0,
                notified TINYINT(1) DEFAULT 0,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            '''))
            conn.close()
        else:
            db.create_all()

        # Copy Articles
        src_articles = src_conn.execute(text('SELECT id, url, title, author, date, description, content, source, created_at FROM article')).fetchall()
        print(f'Found {len(src_articles)} articles in SQLite')
        for row in src_articles:
            # row keys may be index-based
            a = Article(
                url=row['url'] if 'url' in row else row[1],
                title=row['title'] if 'title' in row else row[2],
                author=row['author'] if 'author' in row else row[3],
                description=row['description'] if 'description' in row else row[5],
                content=row['content'] if 'content' in row else row[6],
                source=row['source'] if 'source' in row else row[7],
            )
            # copy date/created_at where possible
            try:
                # date is column 4 in our SELECT; use mapping or index fallback
                date_val = row['date'] if 'date' in row else row[4]
                if date_val:
                    parsed = parse_sqlite_datetime(date_val)
                    if parsed is None:
                        print('Warning: could not parse date for URL', a.url, 'value:', repr(date_val))
                    a.date = parsed
            except Exception:
                pass
            try:
                # created_at is column 8 in our SELECT
                created_val = row['created_at'] if 'created_at' in row else row[8]
                if created_val:
                    parsed_created = parse_sqlite_datetime(created_val)
                    if parsed_created is None:
                        print('Warning: could not parse created_at for URL', a.url, 'value:', repr(created_val))
                    a.created_at = parsed_created
            except Exception:
                pass

            # upsert by URL: skip if exists
            # Defensive truncation for target schema limits
            if a.url and len(a.url) > 767:
                print('Truncating URL to 767 chars for', a.url[:80])
                a.url = a.url[:767]
            if a.title and len(a.title) > 1000:
                a.title = a.title[:1000]

            existing = Article.query.filter_by(url=a.url).first()
            if existing:
                print('Skipping existing', a.url)
                continue
            db.session.add(a)
        try:
            db.session.commit()
        except Exception as e:
            print('Error committing articles:', e)
            db.session.rollback()

        # Copy ScrapeJob table if exists
        try:
            src_jobs = src_conn.execute(text('SELECT id, spider, status, items_count, notified, started_at, finished_at FROM scrape_job')).fetchall()
            print(f'Found {len(src_jobs)} jobs in SQLite')
            for row in src_jobs:
                j = ScrapeJob(
                    spider=row['spider'] if 'spider' in row else row[1],
                    status=row['status'] if 'status' in row else row[2],
                    items_count=row['items_count'] if 'items_count' in row else row[3],
                    notified=row['notified'] if 'notified' in row else row[4],
                )
                try:
                    # started_at is column 5 in the scrape_job SELECT
                    started_val = row['started_at'] if 'started_at' in row else row[5]
                    if started_val:
                        parsed_start = parse_sqlite_datetime(started_val)
                        if parsed_start is None:
                            print('Warning: could not parse scrape_job.started_at for job', j.spider, 'value:', repr(started_val))
                        j.started_at = parsed_start
                except Exception:
                    pass
                try:
                    # finished_at is column 6
                    finished_val = row['finished_at'] if 'finished_at' in row else row[6]
                    if finished_val:
                        parsed_finished = parse_sqlite_datetime(finished_val)
                        if parsed_finished is None:
                            print('Warning: could not parse scrape_job.finished_at for job', j.spider, 'value:', repr(finished_val))
                        j.finished_at = parsed_finished
                except Exception:
                    pass

                db.session.add(j)
            try:
                db.session.commit()
            except Exception as e:
                print('Error committing jobs:', e)
                db.session.rollback()
        except Exception:
            print('No scrape_job table found in source DB; skipping jobs migration')

    src_conn.close()
    print('Migration complete')


if __name__ == '__main__':
    migrate()
