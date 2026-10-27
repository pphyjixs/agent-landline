$ErrorActionPreference = 'Stop'
$taskConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskRule = 'DSH-Phone-Chat-HT802-UDP'
$taskExisting = Get-NetFirewallRule -DisplayName $taskRule -ErrorAction SilentlyContinue
if ($taskExisting) { $taskExisting | Remove-NetFirewallRule }
New-NetFirewallRule -DisplayName $taskRule -Direction Inbound -Action Allow -Protocol UDP `
    -Program $taskConfig.runtime.node -LocalAddress $taskConfig.phone.local_address `
    -RemoteAddress $taskConfig.phone.device_address `
    -LocalPort @($taskConfig.phone.sip_port, $taskConfig.phone.rtp_port) | Out-Null
Write-Host '已允许配置中的 HT802 访问本机 SIP/RTP 端口。'
