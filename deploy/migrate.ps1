# Copy the bot's untracked data (.env, *.json memory files, card images) to the server.
# Run from the repo root on Windows:
#   .\deploy\migrate.ps1 -Server ubuntu@<server-ip> -Key C:\path\to\ssh-key
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Key = "",
    [string]$RemoteDir = "~/discordBotGoogle2"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sshArgs = @()
if ($Key) { $sshArgs = @("-i", $Key) }

$files = @(Get-ChildItem -Path $root -Filter *.json -File | ForEach-Object { $_.FullName })
$files += Join-Path $root ".env"

Write-Host "Stopping bot on server (if running)..."
ssh @sshArgs $Server "sudo systemctl stop jengbot 2>/dev/null || true; mkdir -p $RemoteDir"

Write-Host "Copying $($files.Count) data files..."
scp @sshArgs $files "${Server}:$RemoteDir/"

if (Test-Path (Join-Path $root "cards")) {
    Write-Host "Copying cards/ ..."
    scp @sshArgs -r (Join-Path $root "cards") "${Server}:$RemoteDir/"
}

Write-Host "Starting bot..."
ssh @sshArgs $Server "sudo systemctl start jengbot && sleep 5 && systemctl --no-pager status jengbot | head -n 15"
