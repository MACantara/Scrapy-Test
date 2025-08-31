Scrapy-Test Flask scraper demo

This is a minimal Flask web app that demonstrates a configurable scraper for Philippine news sites.

Setup (Windows PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_APP = "app:create_app()"
python -m flask run
```

The app uses SQLite for demo purposes. Add site parsers in `scrapers/`.
