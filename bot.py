"""Octo — a single-server Discord bot with AI chat, interactive cards,
admin video reposting and scheduled messages."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from db import Database
from openrouter import OpenRouterClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("octo")

INITIAL_COGS = (
    "cogs.ai_chat",
    "cogs.cards",
    "cogs.video_repost",
    "cogs.scheduler",
)


class Octo(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read @mentions and attachments
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

        self.db = Database()
        self.ai = OpenRouterClient()

    async def setup_hook(self) -> None:
        await self.db.connect()

        for cog in INITIAL_COGS:
            await self.load_extension(cog)
            log.info("Loaded cog: %s", cog)

        # Sync slash commands to the single guild for instant availability.
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d slash commands to guild %s", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global slash commands", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        activity = discord.Activity(type=discord.ActivityType.listening, name="@Octo")
        await self.change_presence(activity=activity)

    async def close(self) -> None:
        await self.ai.close()
        await self.db.close()
        await super().close()


def main() -> None:
    problems = config.validate()
    for problem in problems:
        log.warning("Config: %s", problem)
    if not config.DISCORD_TOKEN:
        raise SystemExit("Cannot start: DISCORD_TOKEN is required.")

    bot = Octo()
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
