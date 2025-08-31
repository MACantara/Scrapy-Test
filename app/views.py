from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from .models import Article, ScrapeJob
from .db import db
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import sys

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

    return render_template("index.html", articles=items.items, pagination=items, q=q)

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

        if site not in SCRAPERS:
            flash("Unknown site", "danger")
            return redirect(url_for("main.index"))
    # We now use the Scrapy-based runner exclusively. Start it as a
    # background process so the web request returns immediately.

        # Always use Scrapy runner
        import subprocess
        if site != "all" and site not in SCRAPERS:
            flash("Unknown site", "danger")
            return redirect(url_for("main.index"))

        # create a ScrapeJob row to track the background run
        job = ScrapeJob(spider="all" if run_all else site, status="running")
        db.session.add(job)
        db.session.commit()

        cmd = [
            sys.executable,
            "-m",
            "scrapy_spiders.runner",
            "all" if run_all else site,
            "--pages",
            str(pages if pages is not None else 0),
            "--limit",
            str(limit),
            "--job-id",
            str(job.id),
        ]
        # Windows: start background process without waiting
        subprocess.Popen(cmd, shell=False)
        flash("Scrapy job started in background", "info")
        return redirect(url_for("main.index"))
    return render_template("scrape.html", sites=list(SCRAPERS))

@main_bp.route("/api/articles")
def api_articles():
    articles = Article.query.order_by(Article.created_at.desc()).limit(100).all()
    return jsonify([a.to_dict() for a in articles])
