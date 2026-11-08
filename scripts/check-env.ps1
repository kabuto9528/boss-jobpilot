$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

try {
    Write-Output "Project root: $projectRoot"
    Write-Output "Windows: $([Environment]::OSVersion.VersionString)"
    Write-Output "PowerShell: $($PSVersionTable.PSVersion)"

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Project .venv is missing. Create it with Python 3.12 first.'
    }

    $pythonCheck = @'
from pathlib import Path
import sys

print(f'Python {sys.version.split()[0]}', flush=True)
print(f'Python executable: {sys.executable}', flush=True)
expected_root = Path(sys.argv[1]).resolve()
if sys.version_info[:2] != (3, 12):
    raise SystemExit('Expected Python 3.12.x.')
if Path(sys.prefix).resolve() != expected_root or sys.prefix == sys.base_prefix:
    raise SystemExit('Expected an active interpreter from the project .venv.')
if Path(sys.executable).resolve() != (expected_root / 'Scripts' / 'python.exe').resolve():
    raise SystemExit('Unexpected virtual environment executable path.')
'@
    & $venvPython -I -X utf8 -c $pythonCheck $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment check failed.' }

    & $venvPython -I -X utf8 -m pip --version
    if ($LASTEXITCODE -ne 0) { throw 'pip is unavailable in the project .venv.' }

    $node = Get-Command node.exe -CommandType Application | Select-Object -First 1
    $nodeVersion = & $node.Source --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js version check failed.' }
    $nodeLts = & $node.Source -p 'process.release.lts || false'
    if ($LASTEXITCODE -ne 0) { throw 'Node.js LTS check failed.' }
    Write-Output "Node.js: $nodeVersion ($nodeLts) - $($node.Source)"
    if ($nodeVersion -notmatch '^v24\.\d+\.\d+$' -or $nodeLts -eq 'false') {
        throw 'Expected the project baseline Node.js 24 LTS for Vite 8.'
    }

    $npmVersion = & npm.cmd --version
    if ($LASTEXITCODE -ne 0) { throw 'npm version check failed.' }
    Write-Output "npm: $npmVersion"

    & git.exe --version
    if ($LASTEXITCODE -ne 0) { throw 'Git version check failed.' }

    Write-Output 'Environment check passed.'
    exit 0
} catch {
    [Console]::Error.WriteLine("Environment check failed: $($_.Exception.Message)")
    exit 1
}
