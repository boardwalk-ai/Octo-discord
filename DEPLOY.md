# Deploying Octo

Octo is a Discord bot: it opens an **outbound** WebSocket to Discord and does
**not** listen on any port, so you don't need to open or forward a port on the
server. It just needs to keep running. The steps below use `systemd` so it
restarts on crash and on reboot.

## Prerequisites

- A Linux server you can SSH into.
- Python 3.11+ (`apt install -y python3 python3-venv`).
- Your **Discord bot token** and **OpenRouter API key**.

## Get the code onto the server

**Option A — git (once the repo is pushed):**
```bash
git clone <repo-url> /opt/octo
cd /opt/octo
git checkout claude/octo-discord-ai-bot-k75fas
```

**Option B — git bundle (no GitHub access needed):**
Copy the `octo.bundle` file to the server, then:
```bash
git clone octo.bundle /opt/octo
cd /opt/octo
git checkout claude/octo-discord-ai-bot-k75fas
```

## Install & run (systemd)

```bash
cd /opt/octo
bash deploy/setup.sh          # venv + deps + systemd service
nano .env                     # add DISCORD_TOKEN, GUILD_ID, OPENROUTER_API_KEY
systemctl start octo          # start it
journalctl -u octo -f         # watch the logs
```

To apply later changes: `git pull && systemctl restart octo`.

## Alternative: Docker

```bash
cp .env.example .env          # then edit it
docker build -t octo .
docker run -d --name octo --restart unless-stopped \
  --env-file .env \
  -v octo-data:/app \
  octo
docker logs -f octo
```

## Security notes

- **Rotate any password shared in plain text**, and prefer SSH keys over
  password login for root.
- Keep `.env` private — it holds your bot token and API key. It is
  git-ignored by default.
- Set a **spend limit** on your OpenRouter key as a cost safety net.
