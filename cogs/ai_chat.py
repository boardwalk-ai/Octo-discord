"""@Octo mention → AI reply, plus live model switching."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from openrouter import OpenRouterError

log = logging.getLogger("octo.ai")

_MODEL_SETTING_KEY = "ai_model"
_MAX_DISCORD_LEN = 2000


class AIChat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _current_model(self, guild_id: int) -> str:
        """Model chosen by an admin at runtime, else the configured default."""
        stored = await self.bot.db.get_setting(guild_id, _MODEL_SETTING_KEY)
        return stored or config.OPENROUTER_MODEL

    # ── Mention → chat ───────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not self.bot.user:
            return
        if self.bot.user not in message.mentions:
            return
        if not config.OPENROUTER_API_KEY:
            await message.reply("AI is not configured yet (missing OpenRouter key).")
            return

        history = await self._build_history(message)
        model = await self._current_model(message.guild.id if message.guild else 0)

        async with message.channel.typing():
            try:
                reply = await self.bot.ai.chat(history, model=model)
            except OpenRouterError as exc:
                log.warning("OpenRouter failed: %s", exc)
                await message.reply("Sorry, I couldn't reach the AI right now. Try again shortly.")
                return

        for chunk in _chunk(reply, _MAX_DISCORD_LEN):
            await message.reply(chunk, mention_author=False)

    async def _build_history(self, message: discord.Message) -> list[dict[str, str]]:
        """Assemble a system prompt + recent channel context for the model."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": config.OCTO_SYSTEM_PROMPT}
        ]

        recent: list[dict[str, str]] = []
        async for past in message.channel.history(limit=config.AI_HISTORY_LIMIT):
            if past.id == message.id:
                continue
            content = _clean(past, self.bot.user)
            if not content:
                continue
            role = "assistant" if past.author == self.bot.user else "user"
            recent.append({"role": role, "content": content})
        recent.reverse()  # history() returns newest-first
        messages.extend(recent)

        messages.append({"role": "user", "content": _clean(message, self.bot.user)})
        return messages

    # ── /model commands ──────────────────────────────────────
    model_group = app_commands.Group(
        name="model", description="View or change the AI model Octo uses."
    )

    @model_group.command(name="show", description="Show the current AI model.")
    async def model_show(self, interaction: discord.Interaction) -> None:
        model = await self._current_model(interaction.guild_id or 0)
        allowed = "\n".join(f"• `{m}`" for m in config.OPENROUTER_ALLOWED_MODELS)
        await interaction.response.send_message(
            f"**Current model:** `{model}`\n\n**Allowed models:**\n{allowed}",
            ephemeral=True,
        )

    @model_group.command(name="set", description="Switch the AI model (admins only).")
    @app_commands.describe(model="One of the whitelisted models.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def model_set(self, interaction: discord.Interaction, model: str) -> None:
        if model not in config.OPENROUTER_ALLOWED_MODELS:
            await interaction.response.send_message(
                f"`{model}` is not in the allowed list. Use `/model show` to see valid options.",
                ephemeral=True,
            )
            return
        await self.bot.db.set_setting(interaction.guild_id or 0, _MODEL_SETTING_KEY, model)
        await interaction.response.send_message(f"✅ AI model switched to `{model}`.", ephemeral=True)

    @model_set.autocomplete("model")
    async def _model_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=m, value=m)
            for m in config.OPENROUTER_ALLOWED_MODELS
            if current.lower() in m.lower()
        ][:25]


def _clean(message: discord.Message, bot_user: discord.abc.User | None) -> str:
    """Strip the bot mention and collapse whitespace."""
    content = message.content
    if bot_user:
        content = content.replace(f"<@{bot_user.id}>", "").replace(f"<@!{bot_user.id}>", "")
    return content.strip()


def _chunk(text: str, size: int) -> list[str]:
    if not text:
        return ["(no response)"]
    return [text[i : i + size] for i in range(0, len(text), size)]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChat(bot))
