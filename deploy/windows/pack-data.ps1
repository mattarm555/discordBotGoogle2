# Run on the OLD PC (from the repo folder) to bundle the bot's untracked data:
#   powershell -ExecutionPolicy Bypass -File .\deploy\windows\pack-data.ps1
# Produces jengbot-data.zip (.env + all *.json data files + cards\). Move it to the laptop.
# Stop the bot on this PC first so the JSON files are not mid-write.
param([string]$OutFile = "")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $OutFile) { $OutFile = Join-Path $root "jengbot-data.zip" }

$items = @()
$items += Get-ChildItem -Path $root -Filter *.json -File | ForEach-Object { $_.FullName }
foreach ($name in @(".env", "cards")) {
    $p = Join-Path $root $name
    if (Test-Path $p) { $items += $p } else { Write-Warning "$name not found, skipping" }
}
if (Test-Path $OutFile) { Remove-Item $OutFile -Force }
Compress-Archive -Path $items -DestinationPath $OutFile
Write-Host "Packed $($items.Count) items into $OutFile"
