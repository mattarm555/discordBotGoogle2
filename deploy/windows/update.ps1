# Pull the latest code + packages, then restart the bot.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
& (Join-Path $PSScriptRoot "stop.ps1")
git -C $root pull --ff-only
& (Join-Path $root "venv\Scripts\python.exe") -m pip install -U -r (Join-Path $root "requirements.txt")
& (Join-Path $PSScriptRoot "start.ps1")
