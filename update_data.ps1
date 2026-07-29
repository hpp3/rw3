# One-click data update after a game patch.
#
#   .\update_data.ps1              # detect branch, rebuild, commit, push
#   .\update_data.ps1 -DryRun      # rebuild + show what would be committed, no commit/push
#   .\update_data.ps1 -NoPush      # commit locally only
#   .\update_data.ps1 -Force       # rebuild even if the installed build is already recorded
#
# Steam only ever has ONE branch checked out, so this handles whichever branch is
# installed right now: live -> site/data.json, beta -> site/data.beta.json (see
# gameinfo.py). To update both, run it once per branch with a Steam branch switch
# in between.
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoPush,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Info($msg) { Write-Host "   $msg" }
function Warn($msg) { Write-Host "   $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "`nFAILED: $msg" -ForegroundColor Red; exit 1 }
# Named RunGit, not Git: a function named `git` would shadow git.exe and recurse.
function RunGit { $out = & git @args; if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') exited $LASTEXITCODE" }; return $out }

Push-Location $Root
try {

# ---------------------------------------------------------------- preflight --
Step "Checking environment"

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Fail "venv not found at $Python. Create it per README (python -m venv .venv; pip install tcod==18.1.0 numpy==2.2.6 pygame==2.6.1 dill==0.4.0)."
}

# Single source of truth for the install path / app id: read them out of the
# Python that actually does the extraction, so this script can't drift from it.
$extractSrc = Get-Content (Join-Path $Root 'extract.py') -Raw
$m = [regex]::Match($extractSrc, '(?m)^GAME\s*=\s*r"([^"]+)"')
if (-not $m.Success) { Fail "Could not find the GAME = r`"...`" line in extract.py." }
$GameDir = $m.Groups[1].Value
if (-not (Test-Path $GameDir)) { Fail "Game install dir not found: $GameDir (fix GAME in extract.py / copy_icons.py)." }
Info "game install : $GameDir"

$gameinfoSrc = Get-Content (Join-Path $Root 'gameinfo.py') -Raw
$m = [regex]::Match($gameinfoSrc, '(?m)^APP_ID\s*=\s*"(\d+)"')
if (-not $m.Success) { Fail "Could not find APP_ID in gameinfo.py." }
$AppId = $m.Groups[1].Value

# ------------------------------------------------------------ steam manifest --
# <steamapps>/common/<game>  ->  <steamapps>/appmanifest_<appid>.acf
$SteamApps = Split-Path (Split-Path $GameDir -Parent) -Parent
$Acf = Join-Path $SteamApps "appmanifest_$AppId.acf"
if (-not (Test-Path $Acf)) { Fail "Steam app manifest not found: $Acf" }
$acfText = Get-Content $Acf -Raw

function AcfValue($key) {
    $mm = [regex]::Matches($acfText, ('"{0}"\s+"([^"]*)"' -f [regex]::Escape($key)), 'IgnoreCase')
    if ($mm.Count -eq 0) { return '' }
    return $mm[$mm.Count - 1].Groups[1].Value
}

# StateFlags is a bitfield: 4 = fully installed, 2 = update required. Anything
# else means Steam is mid-download and the files on disk are a mix of versions.
function AcfInt($key) {
    $v = AcfValue $key
    $n = [int64]0
    if ([int64]::TryParse($v, [ref]$n)) { return $n }
    return [int64]0   # key absent/garbled: treat as 0 so the checks below no-op
}

$flags = AcfInt 'StateFlags'
$toDl = AcfInt 'BytesToDownload'
$dled = AcfInt 'BytesDownloaded'
$stateKnown = (AcfValue 'StateFlags') -ne ''
if (($stateKnown -and (($flags -band 4) -eq 0 -or ($flags -band 2) -ne 0)) -or ($toDl -gt 0 -and $dled -lt $toDl)) {
    $msg = "Steam reports the install is not settled (StateFlags=$flags, downloaded $dled/$toDl bytes). Let the update finish in Steam first."
    if (-not $Force) { Fail $msg }
    Warn $msg
    Warn "-Force given: continuing anyway."
}

# ------------------------------------------------------------------- branch --
Step "Detecting installed branch"

# Ask gameinfo.py itself, so branch naming matches exactly what extract.py stamps.
$branchJson = & $Python -c "import json,sys,gameinfo;print(json.dumps(gameinfo.branch_info(sys.argv[1])))" $GameDir
if ($LASTEXITCODE -ne 0) { Fail "gameinfo.branch_info failed." }
$branch = $branchJson | ConvertFrom-Json
$dataFile = & $Python -c "import sys,gameinfo;print(gameinfo.data_filename(sys.argv[1]))" $branch.id
if ($LASTEXITCODE -ne 0) { Fail "gameinfo.data_filename failed." }

Info "branch   : $($branch.id) ($($branch.label))"
Info "build id : $($branch.build_id)"
Info "target   : site/$dataFile"

if (-not $branch.build_id) { Warn "Steam did not report a build id; the commit message will say 'unknown'." }

# Already-built this build? Two very different cases:
#   - working tree clean  -> nothing to do; a rebuild would only churn 'generated'.
#   - data files dirty    -> a previous run built but never committed (interrupted,
#                            or it died before the commit). Resume: skip the slow
#                            rebuild and just commit what's already on disk.
$versionsPath = Join-Path $Root 'site\versions.json'
$SkipBuild = $false
if ((Test-Path $versionsPath) -and $branch.build_id -and -not $Force) {
    $existing = (Get-Content $versionsPath -Raw | ConvertFrom-Json) | Where-Object { $_.id -eq $branch.id }
    if ($existing -and $existing.build_id -eq $branch.build_id) {
        $dirty = RunGit status --porcelain -- site ids.json
        if ($dirty) {
            Warn "Build $($branch.build_id) is already extracted but uncommitted - a previous run was interrupted."
            Warn "Resuming from those files (skipping the rebuild). Use -Force to rebuild from scratch instead."
            $SkipBuild = $true
        } else {
            Write-Host "`nAlready up to date: $($branch.label) build $($branch.build_id) is what's committed (generated $($existing.generated))." -ForegroundColor Green
            Write-Host "Nothing to do. Re-run with -Force to rebuild anyway."
            exit 0
        }
    }
}

# ---------------------------------------------------------------------- git --
Step "Checking git state"

$gitBranch = RunGit rev-parse --abbrev-ref HEAD
if ($gitBranch -eq 'HEAD') { Fail "Repo is in detached HEAD; check out a branch first." }
Info "on branch : $gitBranch"

# Refuse to run with anything already staged: the commit below is built by
# staging site/ + ids.json, and unrelated staged work would be swept into it.
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    Fail "You have staged changes. Commit or unstage them first (git status) so this script's commit stays data-only."
}

if (-not $DryRun) {
    & git ls-remote --exit-code --heads origin $gitBranch *> $null
    if ($LASTEXITCODE -eq 0) {
        RunGit fetch origin $gitBranch | Out-Null
        $behind = [int](RunGit rev-list --count "HEAD..origin/$gitBranch")
        if ($behind -gt 0) {
            Info "$behind commit(s) behind origin/$gitBranch; rebasing first."
            RunGit pull --rebase --autostash origin $gitBranch | Out-Null
        }
    } else {
        Warn "origin/$gitBranch not found; will push with -u."
    }
}

# -------------------------------------------------------------------- build --
$sw = [Diagnostics.Stopwatch]::StartNew()
if ($SkipBuild) {
    # Resuming an interrupted run: the data is on disk, but the verifiers may
    # never have run, so never commit it unverified - run tests.py alone.
    Step "Verifying the already-built data (tests.py)"
    Info "extract/icons skipped; just re-checking the existing data against the game."
    & $Python (Join-Path $Root 'tests.py')
    if ($LASTEXITCODE -ne 0) { Fail "Verifiers failed on the existing data. Re-run with -Force for a clean rebuild." }
} else {
    Step "Rebuilding data (extract + icons + verifiers)"
    Info "Imports the game headlessly, copies icons, then verifies (a few seconds)."
    Info "If it is interrupted, just re-run - it resumes from the extracted files."
    & $Python (Join-Path $Root 'build.py')
    if ($LASTEXITCODE -ne 0) { Fail "build.py failed (see output above). Nothing was committed." }
}
Info ("build step took {0:n0}s" -f $sw.Elapsed.TotalSeconds)

# Sanity: the build should have stamped the build we detected.
$after = (Get-Content $versionsPath -Raw | ConvertFrom-Json) | Where-Object { $_.id -eq $branch.id }
if (-not $after) { Fail "versions.json has no '$($branch.id)' entry after the build." }
if ($branch.build_id -and $after.build_id -ne $branch.build_id) {
    Fail "versions.json says build $($after.build_id) but Steam says $($branch.build_id) - did Steam update mid-build? Re-run."
}

# ------------------------------------------------------------------- commit --
Step "Staging data changes"

# Only the build's own outputs: the site payload plus the append-only id map.
# Everything else in the working tree is left alone.
RunGit add -- site ids.json | Out-Null

& git diff --cached --quiet -- site ids.json
if ($LASTEXITCODE -eq 0) {
    RunGit reset | Out-Null
    Write-Host "`nBuild succeeded but produced no changes to commit." -ForegroundColor Green
    exit 0
}

& git diff --cached --stat -- site ids.json
$buildLabel = $branch.build_id
if (-not $buildLabel) { $buildLabel = 'unknown' }
$message = "Rebuild $($branch.id) data for new patch (build $buildLabel)"

if ($DryRun) {
    RunGit reset | Out-Null
    Write-Host "`n-DryRun: nothing committed. Would have committed:" -ForegroundColor Yellow
    Write-Host "  $message"
    exit 0
}

Step "Committing"
RunGit commit -m $message | Out-Null
Info (RunGit log -1 --oneline)

if ($NoPush) {
    Write-Host "`n-NoPush: committed locally. Push with: git push" -ForegroundColor Yellow
    exit 0
}

Step "Pushing to origin/$gitBranch"
& git push -u origin $gitBranch
if ($LASTEXITCODE -ne 0) {
    Fail "Push failed. The commit is safe locally - resolve the remote state and run: git push"
}

Write-Host "`nDone: $($branch.label) build $($buildLabel) rebuilt, committed, and pushed." -ForegroundColor Green

}
finally {
    Pop-Location -ErrorAction SilentlyContinue
}
