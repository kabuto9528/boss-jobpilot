$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$localRuntime = Join-Path $projectRoot 'runtime\local-app'
$node = Get-Command node.exe -CommandType Application | Select-Object -First 1
$services = @(
    @{
        Name = 'frontend'
        PidFile = Join-Path $localRuntime 'frontend.pid'
        Executable = if ($node) { $node.Source } else { '' }
        RequiredCommand = (Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js')
    },
    @{
        Name = 'API'
        PidFile = Join-Path $localRuntime 'api.pid'
        Executable = Join-Path $projectRoot '.venv\Scripts\python.exe'
        RequiredCommand = 'backend.app.main:app'
    }
)

try {
    foreach ($service in $services) {
        if (-not (Test-Path -LiteralPath $service.PidFile -PathType Leaf)) { continue }
        $servicePid = 0
        $pidText = (Get-Content -LiteralPath $service.PidFile -Raw).Trim()
        if (-not [int]::TryParse($pidText, [ref]$servicePid) -or $servicePid -lt 1) {
            throw "Invalid $($service.Name) process record. Check $($service.PidFile)."
        }

        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid" -ErrorAction SilentlyContinue
        if ($process) {
            if (-not $service.Executable) { throw 'Node.js is unavailable. The frontend was left running.' }
            $expectedPath = [IO.Path]::GetFullPath($service.Executable)
            $actualPath = [IO.Path]::GetFullPath($process.ExecutablePath)
            if ($actualPath -ine $expectedPath -or -not $process.CommandLine.Contains($service.RequiredCommand)) {
                throw "The recorded $($service.Name) PID no longer belongs to this project. It was left running."
            }
            Stop-Process -Id $servicePid -Force
            Write-Host "Stopped local $($service.Name) service."
        } else {
            Write-Host "Local $($service.Name) service was already stopped."
        }
        Remove-Item -LiteralPath $service.PidFile -Force
    }
} catch {
    [Console]::Error.WriteLine("Local app shutdown failed: $($_.Exception.Message)")
    exit 1
}
