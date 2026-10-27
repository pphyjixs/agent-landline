param([switch]$TextOnly, [Parameter(ValueFromRemainingArguments=$true)][string[]]$ScriptArgs)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
try {
    $taskConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskPython = $taskConfig.runtime.python
    if (-not (Test-Path -LiteralPath $taskPython)) { throw "Python 不存在：$taskPython" }
    $taskEntry = if ($TextOnly) { 'text_gateway.py' } else { 'app.py' }
    & $taskPython (Join-Path $PSScriptRoot $taskEntry) @ScriptArgs
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
