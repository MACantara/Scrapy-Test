# run_scrapers_hourly.ps1
# Adjust these paths if needed
$python = 'C:\Users\macan\AppData\Local\Programs\Python\Python312\python.exe'
$project = 'C:\Programming-Projects\Scrapy-Test'
$logDir = Join-Path $project 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$ts = (Get-Date).ToString('yyyyMMdd-HHmmss')
$log = Join-Path $logDir "scrape-$ts.log"

# If you use a venv, uncomment and update the Activate path
# & "$project\venv\Scripts\Activate.ps1"

# Run each scraper in parallel as a separate process (non-blocking).
# This will start one process per scraper and return immediately.
Set-Location $project
$spiders = @('philstar','rappler','manilabulletin','pna')
foreach ($s in $spiders) {
    $spiderLog = Join-Path $logDir "scrape-$s-$ts.log"
    $spiderErr = Join-Path $logDir "scrape-$s-$ts.err.log"
    "Starting $s at $(Get-Date)" | Out-File -FilePath $spiderLog -Append
    Start-Process -FilePath $python -ArgumentList "-m","scrapy_spiders.runner",$s,"--pages","0","--limit","0" -RedirectStandardOutput $spiderLog -RedirectStandardError $spiderErr -WindowStyle Hidden
}

# Optional: write a short marker to the log
"`nStarted scrapers at $(Get-Date)`n" | Out-File -FilePath $log -Append