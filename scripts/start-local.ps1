param([switch]$SkipBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$vite = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$localRuntime = Join-Path $projectRoot 'runtime\local-app'
$apiPidFile = Join-Path $localRuntime 'api.pid'
$frontendPidFile = Join-Path $localRuntime 'frontend.pid'
$playwrightCache = $null
$previousPlaywrightCache = [Environment]::GetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', 'Process')
$apiPort = 8000
$frontendPort = 5173
$apiBase = "http://127.0.0.1:$apiPort"
$frontendBase = "http://127.0.0.1:$frontendPort"
$apiArguments = @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', "$apiPort", '--workers', '1')
$frontendArguments = @($vite, '--host', '127.0.0.1', '--port', "$frontendPort", '--strictPort')
$apiProcess = $null
$frontendProcess = $null
$node = $null
$apiCreated = $false
$frontendCreated = $false

function Test-Listener($Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Test-ApiReady {
    try {
        $ready = Invoke-RestMethod -Uri "$apiBase/api/ready" -TimeoutSec 2
        $settings = Invoke-RestMethod -Uri "$apiBase/api/settings" -TimeoutSec 3
        return $ready.status -eq 'ready' -and $settings.capabilities.fixture.auto_preview_enabled -eq $true
    } catch {
        return $false
    }
}

function Test-FrontendReady {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri "$frontendBase/" -TimeoutSec 3
        if ($page.StatusCode -ne 200 -or -not $page.Content.Contains('BOSS 职位管理台')) { return $false }
        $dashboard = Invoke-RestMethod -Uri "$frontendBase/api/dashboard?source=fixture" -TimeoutSec 3
        return $dashboard.source -eq 'fixture' -and $null -ne $dashboard.jobs_total -and $null -ne $dashboard.applications
    } catch {
        return $false
    }
}

function Stop-StartedProcess($Process, $Executable) {
    if ($null -eq $Process) { return }
    $current = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if ($current -and [IO.Path]::GetFullPath($current.Path) -ieq [IO.Path]::GetFullPath($Executable)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    Push-Location $projectRoot

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env') -PathType Leaf)) {
        throw 'Missing .env. Copy .env.example to .env and configure the local boss_jobs database first.'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Missing .venv. Run scripts/check-env.ps1 to create and verify the Python environment.'
    }
    if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
        throw 'Missing frontend dependencies. Run npm.cmd --prefix .\frontend ci first.'
    }
    $node = Get-Command node.exe -CommandType Application | Select-Object -First 1
    if (-not $node) { throw 'Node.js is missing. Install the Windows environment listed in README.md.' }
    $nodeVersion = & $node.Source --version
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v24\.') {
        throw 'Vite 8 requires the project Node.js 24 LTS baseline.'
    }

    $browserCandidates = @(
        $previousPlaywrightCache,
        'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright',
        (Join-Path $env:LOCALAPPDATA 'boss-jobs-stage-06-playwright')
    )
    foreach ($candidate in $browserCandidates) {
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate 'chromium-1248') -PathType Container)) {
            $playwrightCache = (Resolve-Path -LiteralPath $candidate).Path
            break
        }
    }
    if (-not $playwrightCache) {
        throw 'Playwright Chromium 1248 is missing from the verified browser cache. See docs\acceptance\stage-06.md before starting.'
    }

    $browserProbe = @'
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chromium", headless=True)
    browser.close()
'@
    [Environment]::SetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', $playwrightCache, 'Process')
    & $python -c $browserProbe
    $browserProbeExitCode = $LASTEXITCODE
    [Environment]::SetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', $previousPlaywrightCache, 'Process')
    if ($browserProbeExitCode -ne 0) {
        throw 'Chromium failed its startup check. See docs\acceptance\stage-06.md.'
    }

    if ((Test-Listener $apiPort) -or (Test-Listener $frontendPort)) {
        if ((Test-ApiReady) -and (Test-FrontendReady)) {
            Write-Host "The local app is already available at $frontendBase"
            if (-not $SkipBrowser) { Start-Process $frontendBase }
            exit 0
        }
        throw 'Port 8000 or 5173 is already in use and the app did not pass its end-to-end check. Close the existing service and retry.'
    }

    & $python -c "from sqlalchemy import text; from backend.app.config import load_database_settings; from backend.app.db import create_database_engine; engine=create_database_engine(load_database_settings()); connection=engine.connect(); connection.execute(text('SELECT 1')); connection.close(); engine.dispose()"
    if ($LASTEXITCODE -ne 0) {
        throw 'The local MySQL database is not ready. Check .env and start the boss_jobs database.'
    }

    New-Item -ItemType Directory -Path $localRuntime -Force | Out-Null
    foreach ($pidFile in @($apiPidFile, $frontendPidFile)) {
        if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force }
    }

    $apiOutput = Join-Path $localRuntime 'api.out.log'
    $apiErrors = Join-Path $localRuntime 'api.err.log'
    $frontendOutput = Join-Path $localRuntime 'frontend.out.log'
    $frontendErrors = Join-Path $localRuntime 'frontend.err.log'

    [Environment]::SetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', $playwrightCache, 'Process')
    $apiProcess = Start-Process -FilePath $python -ArgumentList $apiArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $apiOutput -RedirectStandardError $apiErrors
    [Environment]::SetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', $previousPlaywrightCache, 'Process')
    $apiCreated = $true
    Set-Content -LiteralPath $apiPidFile -Value $apiProcess.Id -Encoding ASCII

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if ($apiProcess.HasExited) { throw 'The API process exited during startup. See runtime\local-app\api.err.log.' }
        if (Test-ApiReady) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-ApiReady)) { throw 'The API did not become ready in 30 seconds. See runtime\local-app\api.err.log.' }

    $frontendRoot = Join-Path $projectRoot 'frontend'
    $previousProxyTarget = [Environment]::GetEnvironmentVariable('VITE_API_PROXY_TARGET', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('VITE_API_PROXY_TARGET', $apiBase, 'Process')
        $frontendProcess = Start-Process -FilePath $node.Source -ArgumentList $frontendArguments -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendOutput -RedirectStandardError $frontendErrors
        $frontendCreated = $true
    } finally {
        [Environment]::SetEnvironmentVariable('VITE_API_PROXY_TARGET', $previousProxyTarget, 'Process')
    }
    Set-Content -LiteralPath $frontendPidFile -Value $frontendProcess.Id -Encoding ASCII

    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if ($frontendProcess.HasExited) { throw 'The Vite process exited during startup. See runtime\local-app\frontend.err.log.' }
        if (Test-FrontendReady) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-FrontendReady)) { throw 'The frontend or its API proxy did not become ready in 20 seconds. See runtime\local-app\frontend.err.log and api.err.log.' }

    if (-not $SkipBrowser) { Start-Process $frontendBase }
    Write-Host "Local app is ready at $frontendBase"
    Write-Host 'Use stop-local.cmd to stop the services started by this launcher.'
} catch {
    if ($frontendCreated) {
        Stop-StartedProcess $frontendProcess $node.Source
        if (Test-Path -LiteralPath $frontendPidFile) { Remove-Item -LiteralPath $frontendPidFile -Force }
    }
    if ($apiCreated) {
        Stop-StartedProcess $apiProcess $python
        if (Test-Path -LiteralPath $apiPidFile) { Remove-Item -LiteralPath $apiPidFile -Force }
    }
    [Console]::Error.WriteLine("Local app startup failed: $($_.Exception.Message)")
    exit 1
} finally {
    [Environment]::SetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', $previousPlaywrightCache, 'Process')
    if ((Get-Location).Path -eq $projectRoot) { Pop-Location }
}
