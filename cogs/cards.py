"""Interactive marketing cards: hand-written text + one link button per module.

Cards are authored (not AI-generated), stored in the DB, and editable — reopen
the form, change it, and any already-posted card updates live.
"""
from __future__ import annotations

import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from db import Card

log = logging.getLogger("octo.cards")

_MAX_BUTTONS = 25  # Discord: up to 5 action rows × 5 buttons


# ── Rendering ────────────────────────────────────────────────
def _parse_color(value: str | None) -> discord.Color:
    if not value:
        return discord.Color.blurple()
    try:
        return discord.Color(int(value.lstrip("#"), 16))
    except ValueError:
        return discord.Color.blurple()


def build_embed(card: Card) -> discord.Embed:
    embed = discord.Embed(
        title=card.title or None,
        description=card.description or None,
        color=_parse_color(card.color),
    )
    if card.image_url:
        embed.set_image(url=card.image_url)
    embed.set_footer(text="Octo 🐙")
    return embed


def build_view(card: Card) -> discord.ui.View | None:
    buttons = _load_buttons(card.buttons)
    if not buttons:
        return None
    view = discord.ui.View(timeout=None)
    for label, url in buttons:
        view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    return view


def _load_buttons(raw: str) -> list[tuple[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [(b["label"], b["url"]) for b in data if b.get("label") and b.get("url")]


def parse_button_lines(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Parse a textarea of 'Label | https://url' lines into button dicts."""
    buttons: list[dict[str, str]] = []
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            errors.append(f"Line {lineno}: missing `|` separator.")
            continue
        label, _, url = line.partition("|")
        label, url = label.strip(), url.strip()
        if not label or not url.startswith(("http://", "https://")):
            errors.append(f"Line {lineno}: need a label and an http(s) URL.")
            continue
        buttons.append({"label": label[:80], "url": url})
        if len(buttons) >= _MAX_BUTTONS:
            break
    return buttons, errors


# ── The edit form ────────────────────────────────────────────
class CardModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, guild_id: int, name: str, existing: Card | None):
        super().__init__(title=f"Card: {name}"[:45])
        self.bot = bot
        self.guild_id = guild_id
        self.name = name

        prefill_buttons = ""
        if existing:
            prefill_buttons = "\n".join(f"{l} | {u}" for l, u in _load_buttons(existing.buttons))

        self.title_input = discord.ui.TextInput(
            label="Title",
            default=existing.title if existing else "",
            max_length=256,
            required=True,
        )
        self.desc_input = discord.ui.TextInput(
            label="Body text",
            style=discord.TextStyle.paragraph,
            default=existing.description if existing else "",
            max_length=4000,
            required=True,
        )
        self.image_input = discord.ui.TextInput(
            label="Image URL (optional)",
            default=(existing.image_url or "") if existing else "",
            required=False,
        )
        self.buttons_input = discord.ui.TextInput(
            label="Buttons — one 'Label | URL' per line",
            style=discord.TextStyle.paragraph,
            default=prefill_buttons,
            placeholder="Dashboard | https://app.octopilotai.com\nDocs | https://docs.octopilotai.com",
            required=False,
        )
        self.color_input = discord.ui.TextInput(
            label="Accent color hex (optional)",
            default=(existing.color or "") if existing else "",
            placeholder="#5865F2",
            required=False,
        )
        for item in (
            self.title_input,
            self.desc_input,
            self.image_input,
            self.buttons_input,
            self.color_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        buttons, errors = parse_button_lines(self.buttons_input.value)
        if errors:
            await interaction.response.send_message(
                "Couldn't save — button problems:\n" + "\n".join(f"• {e}" for e in errors),
                ephemeral=True,
            )
            return

        await self.bot.db.upsert_card(
            guild_id=self.guild_id,
            name=self.name,
            title=self.title_input.value.strip(),
            description=self.desc_input.value.strip(),
            image_url=self.image_input.value.strip() or None,
            color=self.color_input.value.strip() or None,
            buttons_json=json.dumps(buttons),
        )

        card = await self.bot.db.get_card(self.guild_id, self.name)
        note = ""
        if card and card.message_id and card.channel_id:
            updated = await _edit_live_message(self.bot, card)
            note = " Live posted card updated." if updated else " (couldn't update the posted card)"
        await interaction.response.send_message(
            f"✅ Saved card **{self.name}**.{note}\nUse `/card post name:{self.name}` to post it.",
            ephemeral=True,
        )


async def _edit_live_message(bot: commands.Bot, card: Card) -> bool:
    channel = bot.get_channel(card.channel_id or 0)
    if not isinstance(channel, discord.abc.Messageable):
        return False
    try:
        message = await channel.fetch_message(card.message_id or 0)
        await message.edit(embed=build_embed(card), view=build_view(card))
        return True
    except (discord.NotFound, discord.HTTPException):
        return False


# ── Commands ─────────────────────────────────────────────────
class Cards(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    card_group = app_commands.Group(
        name="card", description="Create, edit and post interactive cards."
    )

    async def _name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cards = await self.bot.db.list_cards(interaction.guild_id or 0)
        return [
            app_commands.Choice(name=c.name, value=c.name)
            for c in cards
            if current.lower() in c.name.lower()
        ][:25]

    @card_group.command(name="edit", description="Create or edit a card (opens a form).")
    @app_commands.describe(name="A short id for the card, e.g. 'welcome' or 'launch'")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def card_edit(self, interaction: discord.Interaction, name: str) -> None:
        existing = await self.bot.db.get_card(interaction.guild_id or 0, name)
        modal = CardModal(self.bot, interaction.guild_id or 0, name, existing)
        await interaction.response.send_modal(modal)

    @card_edit.autocomplete("name")
    async def _edit_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="post", description="Post a saved card to a channel.")
    @app_commands.describe(name="The card id", channel="Where to post (defaults to here)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def card_post(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        card = await self.bot.db.get_card(interaction.guild_id or 0, name)
        if not card:
            await interaction.response.send_message(
                f"No card named **{name}**. Create it with `/card edit`.", ephemeral=True
            )
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.Messageable):
            await interaction.response.send_message("Invalid channel.", ephemeral=True)
            return

        message = await target.send(embed=build_embed(card), view=build_view(card))
        await self.bot.db.set_card_message(
            interaction.guild_id or 0, name, target.id, message.id  # type: ignore[union-attr]
        )
        await interaction.response.send_message(
            f"✅ Posted **{name}** in {target.mention}. Edits will update it live.",  # type: ignore[union-attr]
            ephemeral=True,
        )

    @card_post.autocomplete("name")
    async def _post_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="show", description="Preview a saved card (only you see it).")
    async def card_show(self, interaction: discord.Interaction, name: str) -> None:
        card = await self.bot.db.get_card(interaction.guild_id or 0, name)
        if not card:
            await interaction.response.send_message(f"No card named **{name}**.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=build_embed(card), view=build_view(card), ephemeral=True
        )

    @card_show.autocomplete("name")
    async def _show_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="list", description="List all saved cards.")
    async def card_list(self, interaction: discord.Interaction) -> None:
        cards = await self.bot.db.list_cards(interaction.guild_id or 0)
        if not cards:
            await interaction.response.send_message(
                "No cards yet. Create one with `/card edit`.", ephemeral=True
            )
            return
        lines = []
        for c in cards:
            posted = f" · posted in <#{c.channel_id}>" if c.message_id else " · not posted"
            n_btn = len(_load_buttons(c.buttons))
            lines.append(f"**{c.name}** — {c.title or '(no title)'} · {n_btn} buttons{posted}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @card_group.command(name="delete", description="Delete a saved card.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def card_delete(self, interaction: discord.Interaction, name: str) -> None:
        ok = await self.bot.db.delete_card(interaction.guild_id or 0, name)
        msg = f"🗑️ Deleted **{name}**." if ok else f"No card named **{name}**."
        await interaction.response.send_message(msg, ephemeral=True)

    @card_delete.autocomplete("name")
    async def _delete_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Cards(bot))
