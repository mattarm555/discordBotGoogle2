# Hosting JengBot 24/7

Target: **Oracle Cloud Always Free** Ampere A1 VM (Ubuntu 24.04, ARM). Cost: $0.
Fallback: any Ubuntu VPS (Hetzner CX22 ≈ €4/mo) — the steps are identical.

## 1. Create the VM (Oracle Cloud)
1. Sign up at cloud.oracle.com (needs a card for verification; Always Free resources are never billed).
   Pick a home region close to you — you can't change it later.
2. **Compute → Instances → Create instance**
   - Image: **Canonical Ubuntu 24.04**
   - Shape: **Ampere → VM.Standard.A1.Flex**, 2 OCPU / 12 GB is plenty (free up to 4 / 24).
   - Networking: defaults (public IPv4 on). No inbound ports are needed besides SSH — the bot only makes outbound connections.
   - SSH keys: "Generate a key pair" and **download the private key**.
3. If you get **"Out of capacity"**: try another availability domain, try again later, or upgrade the
   account to *Pay As You Go* (still $0 for Always Free shapes, and A1 capacity is much easier to get).

## 2. Set up the server
From Windows PowerShell:
```powershell
ssh -i C:\path\to\ssh-key.key ubuntu@<VM_PUBLIC_IP>
```
Then on the VM:
```bash
curl -fsSL https://raw.githubusercontent.com/mattarm555/discordBotGoogle2/main/deploy/setup.sh | BRANCH=main bash
```
This installs Python, FFmpeg, Opus, Deno, Docker + the PO-token provider, clones the repo, creates the
venv, installs the systemd service and a weekly auto-update cron job.

## 3. Copy the bot's memory (data files) from this PC
From the repo folder on Windows:
```powershell
.\deploy\migrate.ps1 -Server ubuntu@<VM_PUBLIC_IP> -Key C:\path\to\ssh-key.key
```
Copies `.env`, every `*.json` data file, and `cards/`, then starts the bot.
**Only run the bot in one place at a time** — stop the copy on your PC, or the two will fight over the token
and the JSON files will diverge.

## 4. Day-to-day
| Task | Command (on the VM) |
| --- | --- |
| Live logs | `journalctl -u jengbot -f` |
| Restart | `sudo systemctl restart jengbot` |
| Stop / start | `sudo systemctl stop jengbot` / `start` |
| Update now | `bash ~/discordBotGoogle2/deploy/update.sh` |
| Back up data to PC | `scp -i key ubuntu@IP:~/discordBotGoogle2/*.json .` (from Windows) |

The service restarts on crash and on reboot. `update.sh` runs every Monday 05:00 (pulls git, upgrades
yt-dlp — YouTube breaks old versions often).

## 5. Check YouTube works from the VM
```bash
cd ~/discordBotGoogle2 && venv/bin/yt-dlp -v -F "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>&1 | grep -Ei "pot|deno|jsc|error|sign in" ; venv/bin/yt-dlp -F "https://www.youtube.com/watch?v=dQw4w9WgXcQ" | tail -5
```
- A list of audio formats → you're good.
- `Sign in to confirm you're not a bot` → YouTube is blocking the VM's IP. In order:
  1. Make sure the provider is running: `docker ps` should show `bgutil-provider`.
  2. Export cookies from a **throwaway** Google account (browser extension "Get cookies.txt LOCALLY",
     while logged in on youtube.com, in a private window you then close). Copy to the VM as
     `~/discordBotGoogle2/yt_cookies.txt` and add `YT_COOKIES=/home/ubuntu/discordBotGoogle2/yt_cookies.txt`
     to `.env`, then restart. (Google may eventually flag that account — never use your main one.)
  3. The bot already falls back to SoundCloud automatically when a YouTube stream can't be resolved,
     and `/play sc:<song>` searches SoundCloud directly.
