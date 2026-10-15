# Start Core to Map from this package.
# Author: Ding Qing
# Date: 2026-10-15

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$executable = Join-Path $PSScriptRoot 'CoreToMap.exe'
if (Test-Path -LiteralPath $executable) {
    & $executable
    exit $LASTEXITCODE
}
$env:HYLOGGER_DATA_ROOT = Join-Path $PSScriptRoot 'data'
$env:PYTHONDONTWRITEBYTECODE = '1'
$pythonPath = Join-Path $PSScriptRoot 'runtime\python.exe'
$pythonArgs = @()
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonPath = $pythonCommand.Source
    } else {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw 'Install Python 3.12 or newer, then follow runtime/README.md.'
        }
        $pythonPath = $pythonCommand.Source
        $pythonArgs = @('-3')
    }
}
& $pythonPath @pythonArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
& $pythonPath @pythonArgs -B (Join-Path $PSScriptRoot 'code\launch.py')
exit $LASTEXITCODE
