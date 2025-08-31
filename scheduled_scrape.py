"""scheduled_scrape.py
Create ScrapeJob rows and launch one Scrapy runner per scraper (parallel).
Intended to be run by Task Scheduler or manually.
"""
import os
import sys
import subprocess
import datetime

# import the Flask app factory and models
from app import create_app
from app.db import db
from app.models import ScrapeJob

# Keep the same scraper names as in the web UI
SCRAPERS = ["philstar", "rappler", "manilabulletin", "pna"]


def main(pages=0, limit=0):
    project = os.path.dirname(os.path.abspath(__file__))
    logdir = os.path.join(project, "logs")
    os.makedirs(logdir, exist_ok=True)

    app = create_app()

    # create one ScrapeJob per scraper and launch runner with that job id
    for name in SCRAPERS:
        with app.app_context():
            job = ScrapeJob(spider=name, status="running")
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(logdir, f"scheduled-{name}-{ts}.log")
        err_path = os.path.join(logdir, f"scheduled-{name}-{ts}.err.log")

        # open log files (append) and launch process
        f_out = open(out_path, "a", encoding="utf-8")
        f_err = open(err_path, "a", encoding="utf-8")
        f_out.write(f"Starting {name} job {job_id} at {datetime.datetime.utcnow().isoformat()}\n")
        f_out.flush()

        cmd = [sys.executable, "-m", "scrapy_spiders.runner", name, "--pages", str(pages), "--limit", str(limit), "--job-id", str(job_id)]
        popen_kwargs = {"stdout": f_out, "stderr": f_err}
        # on Windows keep the process window hidden
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        subprocess.Popen(cmd, **popen_kwargs)

    print("Launched all scrapers")


if __name__ == "__main__":
    # simple CLI parsing: optional pages and limit
    try:
        pages = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    except Exception:
        pages = 0
    try:
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    except Exception:
        limit = 0

    main(pages=pages, limit=limit)
