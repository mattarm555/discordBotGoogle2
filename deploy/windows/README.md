# Running JengBot on a Windows laptop

The bot runs hidden in the background, starts when you log in, restarts itself if it crashes, and
upgrades yt-dlp and restarts once a day at 05:00. A home internet connection means YouTube rarely
blocks it.

## 1. On the old PC: pack the bot's data
Stop the bot here first (close its window). Then, from the repo folder:
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\pack-data.ps1
```
This makes `jengbot-data.zip` (`.env`, every `*.json` data file, `cards\`). Move it to the laptop with a
USB stick or OneDrive. **It contains your bot token, so don't share it or post it anywhere.**

## 2. On the laptop: install
Open **PowerShell as Administrator** (Start → type "PowerShell" → right-click → Run as administrator):
```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
irm https://raw.githubusercontent.com/mattarm555/discordBotGoogle2/main/deploy/windows/install.ps1 -OutFile $env:TEMP\install.ps1
& $env:TEMP\install.ps1 -DataZip "$HOME\Downloads\jengbot-data.zip"
```
(Change the zip path to wherever you put it.) The script:
- installs Python 3.12, Git, FFmpeg and Deno with `winget`
- clones the bot into `C:\JengBot` (deliberately **not** under OneDrive: OneDrive syncing fights with the
  JSON files the bot writes all the time)
- creates the Python environment and restores your data
- registers the **JengBot** scheduled task (runs at log on)
- sets the power plan so the laptop never sleeps when plugged in and closing the lid does nothing
- starts the bot

If it says a command "is not on PATH yet", close the window, open a new Admin PowerShell, and run the
last line again. That's normal right after winget installs things.

## 3. Day-to-day
**Redeploy from Discord (no need to touch the laptop):** merge or push your changes to `main` on GitHub,
then run **`/redeploy`** in any server. It's owner-only. The bot pulls the new code, restarts, and installs
any new packages by itself. **`/musicdebug`** (owner-only) shows FFmpeg/Deno/voice status and runs a
5-second YouTube → FFmpeg audio test on the laptop.

| Task | Command (PowerShell, in `C:\JengBot`) |
| --- | --- |
| Watch the log live | `Get-Content logs\bot.log -Wait -Tail 50` |
| Restart | `powershell -ExecutionPolicy Bypass -File deploy\windows\start.ps1` |
| Stop | `powershell -ExecutionPolicy Bypass -File deploy\windows\stop.ps1` |
| Pull new code + restart | `powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1` |
| Back up data | copy `C:\JengBot\*.json` and `.env` somewhere safe |

`stop.ps1` keeps the bot stopped until `start.ps1` runs or you next log in.

## Laptop checklist
- **Keep it plugged in.** The power settings only stop sleep on AC power. Ethernet is better than Wi-Fi
  for voice quality.
- **Reboots:** Windows Update sometimes restarts overnight. The bot only starts again once someone logs
  in. To make that automatic, turn on auto-login: press Win+R, run `netplwiz`, and untick "Users must
  enter a user name and password". On newer Windows you may first need to turn off *Settings → Accounts
  → Sign-in options → "For improved security, only allow Windows Hello sign-in"*.
- **Only one copy of the bot at a time.** If it also runs on another PC, the two fight over the token
  and the data files drift apart.
- Windows Defender/SmartScreen may ask about Python or FFmpeg the first time. Allow them.

## Troubleshooting
- Bot offline: check `logs\bot.log`. Check that the task exists with `Get-ScheduledTask JengBot`, and
  that there's no leftover `STOP` file in `C:\JengBot`.
- Music: `ffmpeg -version` and `deno --version` must both work in a new PowerShell window.
  `venv\Scripts\yt-dlp -F "https://www.youtube.com/watch?v=dQw4w9WgXcQ"` should list audio formats.
