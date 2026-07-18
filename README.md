# 🐙 Octo — Discord Bot

A single-server Discord bot with AI chat (via OpenRouter), interactive cards,
admin video reposting, and scheduled messages.

## Features

| Feature | How it works |
|---|---|
| **AI chat** | Mention `@Octo` in any channel and it replies using OpenRouter. Recent channel messages are included as context. |
| **Live model switching** | `/model set` changes the AI model at runtime — no restart, no code change. Only whitelisted models are selectable. |
| **Interactive cards** | Hand-write a card in a popup form — title, body text, image, and one link button per line. Cards are saved, reusable, and **editable**: change the form and any posted card updates live. |
| **Video reposting** | Admins upload a marketing video to a source channel; Octo reposts it to a target channel with an optional caption. |
| **Scheduled messages** | `/schedule add` posts a message once, hourly, daily, or weekly in the server's timezone. |

## Slash commands

- `/model show` · `/model set <model>` — view / change the AI model (admins)
- `/card edit <name>` — create/edit a card in a popup form (admins); reopen to edit later
- `/card post <name> [channel]` — post a saved card; later edits update it in place
- `/card show <name>` · `/card list` · `/card delete <name>` — preview / list / remove cards
- `/repost setup <source> <target>` · `/repost status` — configure video reposting (admins)
- `/schedule add <when> <message> [repeat] [channel]` · `/schedule list` · `/schedule remove <id>` — scheduled messages

`when` accepts `HH:MM` (next occurrence) or `YYYY-MM-DD HH:MM`, interpreted in `TIMEZONE`.

## Setup

1. **Create the bot** at <https://discord.com/developers/applications>.
   - Under **Bot**, enable the **Message Content Intent** and **Server Members Intent**.
   - Copy the bot token.
   - Invite it with the `bot` and `applications.commands` scopes and permissions to
     read/send messages, embed links, attach files, and add reactions.

2. **Get an OpenRouter key** at <https://openrouter.ai/keys>. Set a spend limit there
   to cap costs.

3. **Configure**:
   ```bash
   cp .env.example .env      # then fill in DISCORD_TOKEN, GUILD_ID, OPENROUTER_API_KEY
   ```

4. **Install & run**:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```

## Cost notes

Octo defaults to a **cheap model** (`deepseek/deepseek-chat`) on purpose. For a
single server this typically runs **a few dollars a month**. Switch to a premium
model with `/model set` only when you need it, and keep the OpenRouter spend limit
on as a safety net.

## Configuration reference

See [`.env.example`](.env.example) for every variable and its default.
