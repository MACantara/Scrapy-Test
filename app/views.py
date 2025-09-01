from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from .models import Article, ScrapeJob
from .db import db
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import sys
from sqlalchemy import func

main_bp = Blueprint("main", __name__)

# allowed scraper names are the keys from the Scrapy runner
# Allowed scraper names (kept static to avoid importing Scrapy at module import time)
SCRAPERS = {"philstar", "rappler", "manilabulletin", "pna"}

@main_bp.route("/")
def index():
    q = request.args.get("q")
    page = int(request.args.get("page", 1))
    per = 10
    query = Article.query
    if q:
        query = query.filter(Article.title.ilike(f"%{q}%") | Article.content.ilike(f"%{q}%"))
    # Some SQL dialects (MySQL) don't support NULLS LAST. Emit a dialect-aware
    # ordering: for MySQL, order by IS NULL (so non-null first) then date desc.
    dialect = None
    try:
        dialect = db.engine.dialect.name
    except Exception:
        pass

    if dialect == 'mysql':
        # (Article.date IS NULL) ASC -> non-null (0) before null (1)
        items = query.order_by(Article.date.is_(None).asc(), Article.date.desc(), Article.created_at.desc()).paginate(page=page, per_page=per, error_out=False)
    else:
        items = query.order_by(Article.date.desc().nullslast(), Article.created_at.desc()).paginate(page=page, per_page=per, error_out=False)
    # flash any finished, unnotified scrape jobs
    from .models import ScrapeJob
    jobs = ScrapeJob.query.filter_by(status="finished", notified=False).all()
    for j in jobs:
        flash(f"Scrape job {j.id} finished: {j.items_count} items", "info")
        j.notified = True
        db.session.add(j)
    if jobs:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # also collect currently running jobs to show progress on the UI
    running_jobs = ScrapeJob.query.filter_by(status="running").all()

    return render_template("index.html", articles=items.items, pagination=items, q=q, running_jobs=running_jobs)

@main_bp.route("/scrape", methods=[GET, POST] if False else ["GET", "POST"]) 
@main_bp.route("/scrape", methods=["GET", "POST"]) 
def scrape():
    if request.method == "POST":
        site = request.form.get("site")
        # allow empty pages to mean 'unlimited' (None)
        pages_raw = request.form.get("pages", "").strip()
        try:
            pages = int(pages_raw) if pages_raw != "" else None
        except Exception:
            pages = None
        limit = int(request.form.get("limit", 0))  # 0 means no limit
        run_all = bool(request.form.get("run_all"))
        use_scrapy = bool(request.form.get("use_scrapy"))

        # If run_all is requested we won't require a specific site value.
        if not run_all and site not in SCRAPERS:
            flash("Unknown site", "danger")
            return redirect(url_for("main.index"))
        # We now use the Scrapy-based runner exclusively. Start it as a
        # background process so the web request returns immediately.

        # Always use Scrapy runner
        import subprocess
        # If run_all is requested the form may omit or hide the `site` field;
        # treat that case as if the requested site is 'all' and skip validation.
        if run_all:
            site = "all"
        elif site != "all" and site not in SCRAPERS:
            flash("Unknown site", "danger")
            return redirect(url_for("main.index"))

        # If run_all is requested, start one background process per scraper
        # so they run in parallel. Create a ScrapeJob per scraper for tracking.
        started = 0
        if run_all:
            for name in SCRAPERS:
                job = ScrapeJob(spider=name, status="running")
                db.session.add(job)
                db.session.commit()

                cmd = [
                    sys.executable,
                    "-m",
                    "scrapy_spiders.runner",
                    name,
                    "--pages",
                    str(pages if pages is not None else 0),
                    "--limit",
                    str(limit),
                    "--job-id",
                    str(job.id),
                ]
                subprocess.Popen(cmd, shell=False)
                started += 1
            flash(f"Started {started} Scrapy jobs in background", "info")
        else:
            # single-site run: create one job and start one process
            job = ScrapeJob(spider=site, status="running")
            db.session.add(job)
            db.session.commit()

            cmd = [
                sys.executable,
                "-m",
                "scrapy_spiders.runner",
                site,
                "--pages",
                str(pages if pages is not None else 0),
                "--limit",
                str(limit),
                "--job-id",
                str(job.id),
            ]
            subprocess.Popen(cmd, shell=False)
            flash("Scrapy job started in background", "info")
        return redirect(url_for("main.index"))
    return render_template("scrape.html", sites=list(SCRAPERS))

@main_bp.route("/api/articles")
def api_articles():
    articles = Article.query.order_by(Article.created_at.desc()).limit(100).all()
    return jsonify([a.to_dict() for a in articles])


@main_bp.route("/api/jobs")
def api_jobs():
    # return currently running scrape jobs for frontend polling
    jobs = ScrapeJob.query.filter_by(status="running").all()
    return jsonify([j.to_dict() for j in jobs])


@main_bp.route("/analytics")
def analytics():
    # Basic analytics dashboard using Article and ScrapeJob models
    total_articles = Article.query.count()
    # articles per source
    per_source = db.session.query(Article.source, func.count(Article.id)).group_by(Article.source).all()

    job_counts = {
        'running': ScrapeJob.query.filter_by(status='running').count(),
        'finished': ScrapeJob.query.filter_by(status='finished').count(),
        'total': ScrapeJob.query.count(),
    }

    recent_jobs = ScrapeJob.query.order_by(ScrapeJob.started_at.desc()).limit(10).all()
    recent_articles = Article.query.order_by(Article.created_at.desc()).limit(10).all()

    # prepare JSON-friendly lists for charts
    source_labels = [s or 'unknown' for s, c in per_source]
    source_counts = [c for s, c in per_source]

    # scraping speed: compute overall average articles/hour and recent 24h rate
    try:
        min_created, max_created = db.session.query(func.min(Article.created_at), func.max(Article.created_at)).one()
        if min_created and max_created and max_created > min_created:
            hours = (max_created - min_created).total_seconds() / 3600.0
        else:
            hours = 1.0
        avg_per_hour = total_articles / max(1.0, hours)
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(days=1)
        last_24h = Article.query.filter(Article.created_at >= since).count()
        last_24h_per_hour = last_24h / 24.0
    except Exception:
        avg_per_hour = 0.0
        last_24h = 0
        last_24h_per_hour = 0.0

    scraping_stats = {
        'avg_per_hour': avg_per_hour,
        'last_24h': last_24h,
        'last_24h_per_hour': last_24h_per_hour,
    }

    # per-spider statistics: total, avg/hr (based on min/max created_at per source), last 24h counts
    try:
        src_rows = db.session.query(Article.source, func.count(Article.id), func.min(Article.created_at), func.max(Article.created_at)).group_by(Article.source).all()
        per_spider_stats = {}
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(days=1)
        for source, cnt, min_c, max_c in src_rows:
            name = source or 'unknown'
            if min_c and max_c and max_c > min_c:
                hrs = (max_c - min_c).total_seconds() / 3600.0
            else:
                hrs = 1.0
            avg = cnt / max(1.0, hrs)
            last_24h_cnt = db.session.query(func.count(Article.id)).filter(Article.source == source, Article.created_at >= since).scalar() or 0
            per_spider_stats[name] = {
                'total': cnt,
                'avg_per_hour': avg,
                'last_24h': last_24h_cnt,
                'last_24h_per_hour': last_24h_cnt / 24.0,
            }
    except Exception:
        per_spider_stats = {}

    return render_template('analytics.html', total_articles=total_articles, per_source=per_source,
                           job_counts=job_counts, recent_jobs=recent_jobs, recent_articles=recent_articles,
                           source_labels=source_labels, source_counts=source_counts,
                           scraping_stats=scraping_stats, per_spider_stats=per_spider_stats)
