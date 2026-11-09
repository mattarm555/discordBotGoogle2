# Supervisor loop started by the "JengBot" scheduled task. Keeps the bot running:
# restarts it if it exits, upgrades yt-dlp and restarts once a day at 05:00.
# Create a file named STOP in the bot folder (or use stop.ps1) to make it quit.
param([string]$BotArgs = "-u main.py")
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$mutex = New-Object System.Threading.Mutex($false, "Local\JengBotRunner")
try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { exit 0 }  # another runner is already active

$py = Join-Path $root "venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$log = Join-Path $logDir "bot.log"
$stopFile = Join-Path $root "STOP"
$stamp = Join-Path $logDir ".ytdlp-updated"
New-Item -ItemType Directory -Force $logDir | Out-Null

# The bot prints emoji; without UTF-8 mode Python crashes writing them to a log file.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

function Write-Log([string]$msg) {
    Add-Content -Path $log -Value "[runner $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" -Encoding UTF8
}

# Run "<venv python> <pyArgs>" hidden through cmd.exe, appending stdout+stderr to the log.
function Start-Python([string]$pyArgs) {
    $cmdLine = "/c `"`"$py`" $pyArgs >> `"$log`" 2>&1`""
    return Start-Process -FilePath "cmd.exe" -ArgumentList $cmdLine -WorkingDirectory $root -WindowStyle Hidden -PassThru
}

function Next-DailyRestart {
    $t = (Get-Date).Date.AddHours(5)
    if ($t -le (Get-Date)) { $t = $t.AddDays(1) }
    return $t
}

while (-not (Test-Path $stopFile)) {
    # Rotate the log at ~10 MB
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 10MB)) {
        Move-Item $log (Join-Path $logDir "bot.old.log") -Force
    }

    # Upgrade yt-dlp at most once a day (YouTube breaks old versions often)
    if (-not (Test-Path $stamp) -or ((Get-Item $stamp).LastWriteTime -lt (Get-Date).AddHours(-20))) {
        Write-Log "upgrading yt-dlp"
        (Start-Python "-m pip install -q -U `"yt-dlp[default]`"").WaitForExit()
        Set-Content -Path $stamp -Value (Get-Date) -Encoding ASCII
    }

    Write-Log "starting bot"
    $proc = Start-Python $BotArgs
    $restartAt = Next-DailyRestart
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 15
        if ((Test-Path $stopFile) -or ((Get-Date) -ge $restartAt)) {
            Write-Log "stopping bot (stop requested or daily restart)"
            & taskkill.exe /T /F /PID $proc.Id | Out-Null
            break
        }
    }
    if (Test-Path $stopFile) { break }
    Write-Log "bot exited; restarting in 10 seconds"
    Start-Sleep -Seconds 10
}
Write-Log "runner exiting (STOP file present)"
$mutex.ReleaseMutex()
