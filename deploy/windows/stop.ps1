# Stop the bot (it stays stopped until start.ps1, or the next log on).
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
New-Item -ItemType File -Force (Join-Path $root "STOP") | Out-Null
Stop-ScheduledTask -TaskName "JengBot" -ErrorAction SilentlyContinue
# The runner launches: cmd.exe -> venv python.exe -> real python.exe. Kill each tree from the top.
$venvPy = Join-Path $root "venv\Scripts\python.exe"
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($venvPy) } |
    ForEach-Object { & taskkill.exe /T /F /PID $_.ProcessId 2>$null | Out-Null }
Write-Host "JengBot stopped."
