#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Refresh Upcoming Match Predictions

.DESCRIPTION
    Scrapes Flashscore for upcoming fixtures (today → today + DaysAhead),
    runs the precompute enrichment, then commits and pushes the updated
    processed/upcoming_enriched.json to GitHub so Streamlit Cloud shows
    fresh data.

    Designed to be run daily via Windows Task Scheduler.
    
    Note: As of June 2026, SofaScore is blocked by Cloudflare.
    This script now uses Flashscore which has a rolling 7-day window.

.PARAMETER DaysAhead
    Number of days beyond today to scrape. Default is 3 (today → today+3).

.PARAMETER SkipScrape
    Skip the scraping step and go straight to precompute.
    Useful when you already have fresh data in data/flashscore/.

.PARAMETER SkipPush
    Run scrape + precompute but do not commit or push. Useful for testing.

.EXAMPLE
    .\refresh_predictions.ps1

.EXAMPLE
    .\refresh_predictions.ps1 -DaysAhead 5

.EXAMPLE
    .\refresh_predictions.ps1 -SkipScrape

.EXAMPLE
    .\refresh_predictions.ps1 -SkipPush
#>

param(
    [int]$DaysAhead = 3,
    [string]$Branch = "main",
    [switch]$SkipScrape,
    [switch]$SkipPush
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TotalStart = Get-Date

# ── Repo root ─────────────────────────────────────────────────────────────────
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

# ── Color helpers ─────────────────────────────────────────────────────────────
function Write-Step   { param([string]$M) Write-Host "`n  ▶  $M" -ForegroundColor Cyan }
function Write-OK     { param([string]$M) Write-Host "  ✓  $M" -ForegroundColor Green }
function Write-Info   { param([string]$M) Write-Host "  ℹ  $M" -ForegroundColor DarkGray }
function Write-Fail   { param([string]$M) Write-Host "  ✗  $M" -ForegroundColor Red }

Write-Host @"

╔══════════════════════════════════════════════════════╗
║        Table Tennis — Predictions Refresh            ║
╚══════════════════════════════════════════════════════╝
"@ -ForegroundColor Yellow
Write-Info "Started at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Info "Repo root:  $RepoRoot"

# ── Activate venv ─────────────────────────────────────────────────────────────
$VenvActivate = Join-Path $RepoRoot "venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    Write-Info "Activating venv…"
    & $VenvActivate
} else {
    Write-Fail "venv not found at $VenvActivate — run 'python -m venv venv && pip install -r requirements.txt' first."
    exit 1
}

# ── Date range ────────────────────────────────────────────────────────────────
$Today    = (Get-Date).ToString("yyyy-MM-dd")
$EndDate  = (Get-Date).AddDays($DaysAhead).ToString("yyyy-MM-dd")
Write-Info "Date range: $Today → $EndDate"

$Branch = $Branch.Trim()
Write-Info "Target git branch: $Branch"

Write-Step "Ensuring repo is on branch '$Branch'"
$checkout = git checkout $Branch 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Unable to checkout branch '$Branch'. Ensure the branch exists and the working tree is clean."
    exit 1
}

function Resolve-GitRebaseConflict {
    param([string]$File)

    while ($true) {
        $unmergedFiles = @(git diff --name-only --diff-filter=U 2>$null | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        if (-not $unmergedFiles) {
            $rebaseInProgress = (Test-Path ".git/rebase-merge") -or (Test-Path ".git/rebase-apply")
            if (-not $rebaseInProgress) {
                return
            }

            git rebase --continue
            if ($LASTEXITCODE -ne 0) {
                throw "git rebase --continue failed"
            }
            continue
        }

        if ($unmergedFiles.Count -eq 1 -and $unmergedFiles[0] -eq $File) {
            Write-Info "Auto-resolving conflict for $File using the locally generated version."
            git checkout --ours $File
            if ($LASTEXITCODE -ne 0) {
                throw "git checkout --ours failed"
            }
            git add $File
            if ($LASTEXITCODE -ne 0) {
                throw "git add failed while resolving conflict"
            }
            git rebase --continue
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            continue
        }

        throw "Unexpected merge conflict(s) during rebase: $($unmergedFiles -join ', ')"
    }
}

function Ensure-GitRemoteSynced {
    param([string]$Branch)

    Write-Info "Checking remote status for branch '$Branch'..."
    git fetch origin --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch failed"
    }

    $upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $upstream) {
        Write-Info "No upstream tracking branch configured for '$Branch'. Skipping remote sync."
        return
    }

    $counts = git rev-list --left-right --count 'HEAD...@{u}' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to compare local and upstream branch."
    }

    $parts = $counts -split "\t"
    if ($parts.Count -ne 2) {
        throw "Unexpected git rev-list output: $counts"
    }

    $behind = [int]$parts[0]
    $ahead = [int]$parts[1]

    if ($behind -gt 0) {
        Write-Info "Local branch is behind origin/$Branch by $behind commit(s). Pulling remote changes..."
        git pull --rebase --autostash origin $Branch
        if ($LASTEXITCODE -ne 0) {
            $status = git status --porcelain
            if ($LASTEXITCODE -eq 0 -and $status -match 'UU processed/upcoming_enriched.json') {
                Resolve-GitRebaseConflict -File 'processed/upcoming_enriched.json'
                return
            }
            throw "git pull --rebase failed"
        }
    } elseif ($ahead -gt 0) {
        Write-Info "Local branch is ahead of origin/$Branch by $ahead commit(s)."
    } else {
        Write-Info "Local branch is up to date with origin/$Branch."
    }
}

Ensure-GitRemoteSynced -Branch $Branch

# ── Step 1: Scrape Flashscore ────────────────────────────────────────────────
if (-not $SkipScrape) {
    Write-Step "STEP 1/3: Scrape Flashscore ($Today → $EndDate)"
    $Step1Start = Get-Date
    try {
        # Use Flashscore instead of SofaScore (SofaScore blocked by Cloudflare as of June 2026)
        python scripts/tt_scraper.py flash --start $Today --end $EndDate
        if ($LASTEXITCODE -ne 0) { throw "Exit code $LASTEXITCODE" }
        $Step1Duration = (Get-Date) - $Step1Start
        Write-OK "Scrape completed in $($Step1Duration.TotalSeconds.ToString('0')) sec"
    } catch {
        Write-Fail "Scrape failed: $_"
        exit 1
    }
} else {
    Write-Info "Skipping scrape (-SkipScrape flag set)"
}

# ── Step 2: Precompute enrichment ─────────────────────────────────────────────
Write-Step "STEP 2/3: Enrich fixtures (tt_precompute.py)"
$Step2Start = Get-Date
try {
    # Keep upcoming feed resilient when SofaScore is Cloudflare-blocked.
    python scripts/tt_precompute.py --flash-only
    if ($LASTEXITCODE -ne 0) { throw "Exit code $LASTEXITCODE" }
    $Step2Duration = (Get-Date) - $Step2Start
    Write-OK "Precompute completed in $($Step2Duration.TotalSeconds.ToString('0')) sec"
} catch {
    Write-Fail "Precompute failed: $_"
    exit 1
}

# Quick sanity check — did we actually get fixtures?
$JsonPath = Join-Path $RepoRoot "processed\upcoming_enriched.json"
$FixtureCount = 0
if (Test-Path $JsonPath) {
    try {
        $Data = Get-Content $JsonPath -Raw | ConvertFrom-Json
        $FixtureCount = $Data.fixtures.Count
    } catch { }
}
if ($FixtureCount -eq 0) {
    Write-Fail "upcoming_enriched.json has 0 fixtures — skipping git push to avoid overwriting good data."
    exit 1
}
Write-Info "$FixtureCount fixtures written to upcoming_enriched.json"

# ── Step 3: Commit + push ─────────────────────────────────────────────────────
if (-not $SkipPush) {
    Write-Step "STEP 3/3: Commit and push"
    $Step3Start = Get-Date

    $CommitMsg = "data: predictions refresh $(Get-Date -Format 'yyyy-MM-dd') — $FixtureCount fixtures [skip ci]"

    try {
        Ensure-GitRemoteSynced -Branch $Branch

        git add processed/upcoming_enriched.json
        if ($LASTEXITCODE -ne 0) { throw "git add failed" }

        # Only commit if there are staged changes
        $Staged = git diff --cached --name-only
        if ($Staged) {
            git commit -m $CommitMsg
            if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

            git push origin $Branch
            if ($LASTEXITCODE -ne 0) { throw "git push failed" }

            $Step3Duration = (Get-Date) - $Step3Start
            Write-OK "Pushed in $($Step3Duration.TotalSeconds.ToString('0')) sec"
        } else {
            Write-Info "No changes to commit — upcoming_enriched.json is already up to date."
        }
    } catch {
        Write-Fail "Git step failed: $_"
        exit 1
    }
} else {
    Write-Info "Skipping git push (-SkipPush flag set)"
}

# ── Summary ───────────────────────────────────────────────────────────────────
$TotalDuration = (Get-Date) - $TotalStart

Write-Host @"

╔══════════════════════════════════════════════════════╗
║          ✅  REFRESH COMPLETED SUCCESSFULLY           ║
╚══════════════════════════════════════════════════════╝
"@ -ForegroundColor Green

if (-not $SkipScrape) {
    Write-Host "   Step 1 (Scrape):      $($Step1Duration.TotalSeconds.ToString('0.0')) sec" -ForegroundColor White
}
Write-Host "   Step 2 (Precompute):  $($Step2Duration.TotalSeconds.ToString('0.0')) sec" -ForegroundColor White
if (-not $SkipPush) {
    Write-Host "   Step 3 (Git push):    $($Step3Duration.TotalSeconds.ToString('0.0')) sec" -ForegroundColor White
}
Write-Host "   ──────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "   TOTAL:                $($TotalDuration.TotalMinutes.ToString('0.00')) min" -ForegroundColor Yellow
Write-Host ""
Write-OK "Finished at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""
