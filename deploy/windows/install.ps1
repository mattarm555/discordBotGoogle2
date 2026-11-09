# One-time setup of JengBot on a Windows laptop. Run in an ADMIN PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   irm https://raw.githubusercontent.com/mattarm555/discordBotGoogle2/main/deploy/windows/install.ps1 -OutFile $env:TEMP\install.ps1
#   & $env:TEMP\install.ps1 -DataZip C:\path\to\jengbot-data.zip [-Branch main]
param(
    [string]$Branch = "main",
    [string]$InstallDir = "C:\JengBot",
    [string]$DataZip = "",
    [string]$RepoUrl = "https://github.com/mattarm555/discordBotGoogle2.git"
)
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Please run this script from an Administrator PowerShell window." }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "==> Installing Python 3.12, Git, FFmpeg, Deno (winget)"
foreach ($id in @("Python.Python.3.12", "Git.Git", "Gyan.FFmpeg", "DenoLand.Deno")) {
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
    # winget returns non-zero when the package is already installed; that's fine
}
Refresh-Path

foreach ($cmd in @("py", "git", "ffmpeg", "deno")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "'$cmd' is not on PATH yet. Close this window, open a new Admin PowerShell, and run the script again."
    }
}

Write-Host "==> Getting the code ($Branch) into $InstallDir"
if (Test-Path (Join-Path $InstallDir ".git")) {
    git -C $InstallDir fetch origin
    git -C $InstallDir checkout $Branch
    git -C $InstallDir pull --ff-only
} else {
    git clone --branch $Branch $RepoUrl $InstallDir
}

Write-Host "==> Python virtual environment + packages"
$venvPy = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { py -3.12 -m venv (Join-Path $InstallDir "venv") }
& $venvPy -m pip install -U pip
& $venvPy -m pip install -U -r (Join-Path $InstallDir "requirements.txt")

if ($DataZip) {
    Write-Host "==> Restoring bot data from $DataZip"
    Expand-Archive -Path $DataZip -DestinationPath $InstallDir -Force
}
if (-not (Test-Path (Join-Path $InstallDir ".env"))) {
    Write-Warning ".env is missing in $InstallDir - the bot can't log in without it. Re-run with -DataZip."
}

Write-Host "==> Registering scheduled task 'JengBot' (starts hidden at log on)"
$runScript = Join-Path $InstallDir "deploy\windows\run.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`"" `
    -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "JengBot" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "==> Power settings: never sleep on AC power, closing the lid does nothing on AC"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT

Write-Host "==> Starting the bot"
Remove-Item (Join-Path $InstallDir "STOP") -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "JengBot"
Write-Host ""
Write-Host "Done. Logs: $InstallDir\logs\bot.log"
Write-Host "Watch live:  Get-Content $InstallDir\logs\bot.log -Wait -Tail 50"
