# Start (or restart) the bot in the background.
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
& (Join-Path $PSScriptRoot "stop.ps1") | Out-Null
Start-Sleep -Seconds 2
Remove-Item (Join-Path $root "STOP") -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "JengBot"
Write-Host "JengBot started. Logs: $root\logs\bot.log"
