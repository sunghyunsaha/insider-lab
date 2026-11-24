<#
Full research run on your own Windows PC.

Why on your PC: the SEC refuses requests from GitHub's servers ("Request Rate Threshold
Exceeded" on the first request, 2026-11-25), so the SEC data must come from a home
connection. Prices (Yahoo) and USD/KRW (FRED) work from anywhere.

Usage, in PowerShell:
    git clone https://github.com/sunghyunsaha/insider-lab
    cd insider-lab
    powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Email you@example.com

-Email is sent to the SEC as your contact in the User-Agent header, as the SEC asks of
automated clients. It is kept in this PowerShell session only and never written to disk.
Add -NoPush to skip committing and pushing the generated reports.
Takes roughly 1 to 2 hours (about 1 GB of SEC downloads, then prices for several thousand
tickers). Keep the PC awake. Re-running resumes where it stopped: everything is cached in data\.
#>
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [switch]$NoPush
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }

Step "Python environment"
if (-not (Test-Path ".venv")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    else { python -m venv .venv }
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt
& $py -m pip install --quiet -e . --no-deps
$cli = ".\.venv\Scripts\insiderlab.exe"

$env:SEC_USER_AGENT = "insider-lab $Email"
$env:PYTHONUNBUFFERED = "1"

Step "Reachability"
& $cli data-check

Step "SEC insider data sets (2006 onwards)"
& $cli fetch-sec
if ($LASTEXITCODE -ne 0) { throw "fetch-sec failed; re-run the script to resume" }

Step "Prices and USD/KRW"
& $cli fetch-prices
if ($LASTEXITCODE -ne 0) { throw "fetch-prices failed; re-run the script to resume" }

Step "Pre-registered backtest"
& $cli backtest
if ($LASTEXITCODE -ne 0) { throw "backtest failed" }

if ($NoPush) {
    Write-Host "`nDone. Open reports\REPORT.md. Nothing was committed (-NoPush)."
    exit 0
}

Step "Commit and push the generated reports"
git add reports/REPORT.md reports/results reports/figures README.md
git -c user.name="Sunghyun Hur" -c user.email="198362482+sunghyunsaha@users.noreply.github.com" `
    commit -m "Research run on local PC: regenerate reports from real data"
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "Push failed (git may not be signed in on this PC). The reports are in reports\;" `
        "run 'git push' after signing in, or tell Claude." -ForegroundColor Yellow
}
Write-Host "`nDone. Open reports\REPORT.md."
