$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskConfigFile = Join-Path $PSScriptRoot 'config.json'
$taskConfig = Get-Content -LiteralPath $taskConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
$taskVenv = Join-Path $PSScriptRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $taskVenv 'Scripts/python.exe'))) {
    & $taskConfig.runtime.python -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败' }
}
$taskPython = Join-Path $taskVenv 'Scripts/python.exe'
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
$taskConfig.runtime.python = $taskPython
$taskConfig | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $taskConfigFile -Encoding UTF8
Write-Host '依赖已安装，双击 start.cmd 启动。TTS 继续使用 D:\AI\Qwen3-TTS 的环境。'
