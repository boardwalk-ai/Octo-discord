"""Interactive marketing cards: hand-written text + one link button per module.

Cards are authored (not AI-generated), stored in the DB, and editable — reopen
the form, change it, and any already-posted card updates live.

Images can be provided either as a URL (in the form) or uploaded straight from
your device via the ``image`` option on ``/card edit``. Uploaded images are
saved on the server and re-attached to the message, so they never expire.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from db import Card

log = logging.getLogger("octo.cards")

_MAX_BUTTONS = 25  # Discord: up to 5 action rows × 5 buttons
_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Uploaded card images live here (relative to the bot's working directory, i.e.
# /opt/octo on the server). It is git-ignored, so deploys never touch it.
IMAGE_DIR = Path("card_images")


# ── Rendering ────────────────────────────────────────────────
def _parse_color(value: str | None) -> discord.Color:
    if not value:
        return discord.Color.blurple()
    try:
        return discord.Color(int(value.lstrip("#"), 16))
    except ValueError:
        return discord.Color.blurple()


def _is_url(value: str | None) -> bool:
    return bool(value) and value.startswith(("http://", "https://"))  # type: ignore[union-attr]


def build_embed(card: Card) -> discord.Embed:
    embed = discord.Embed(
        title=card.title or None,
        description=card.description or None,
        color=_parse_color(card.color),
    )
    if _is_url(card.image_url):
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


def render_card(card: Card) -> tuple[discord.Embed, discord.ui.View | None, list[discord.File]]:
    """Build everything needed to send/edit a card message.

    Returns the embed, the (optional) button view, and any files to attach.
    An uploaded image is stored as ``file:<path>`` and re-attached here so the
    image keeps working long-term (Discord CDN upload URLs expire).
    """
    embed = build_embed(card)
    view = build_view(card)
    files: list[discord.File] = []
    if card.image_url and card.image_url.startswith("file:"):
        path = Path(card.image_url[len("file:"):])
        if path.is_file():
            files.append(discord.File(path, filename=path.name))
            embed.set_image(url=f"attachment://{path.name}")
    return embed, view, files


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


async def _save_uploaded_image(guild_id: int, name: str, attachment: discord.Attachment) -> str:
    """Persist an uploaded image to disk and return a ``file:<path>`` marker."""
    content_type = (attachment.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise ValueError("the uploaded file is not an image")
    if attachment.size > _MAX_IMAGE_BYTES:
        raise ValueError("the image is larger than 8 MB")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(attachment.filename)[1].lower()
    if ext not in _IMAGE_EXTS:
        ext = ".png"
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "", name)[:40] or "card"
    path = IMAGE_DIR / f"{guild_id}_{safe_name}_{int(time.time())}{ext}"
    await attachment.save(path)
    return f"file:{path.as_posix()}"


# ── The edit form ────────────────────────────────────────────
class CardModal(discord.ui.Modal):
    def __init__(
        self,
        bot: commands.Bot,
        guild_id: int,
        name: str,
        existing: Card | None,
        uploaded: discord.Attachment | None = None,
    ):
        super().__init__(title=f"Card: {name}"[:45])
        self.bot = bot
        self.guild_id = guild_id
        self.name = name
        self.uploaded = uploaded

        self.existing_image = existing.image_url if existing else None
        self.existing_is_file = bool(
            self.existing_image and self.existing_image.startswith("file:")
        )

        prefill_buttons = ""
        if existing:
            prefill_buttons = "\n".join(f"{l} | {u}" for l, u in _load_buttons(existing.buttons))

        # Only prefill the URL box with a real URL (never a file: marker).
        url_default = self.existing_image if _is_url(self.existing_image) else ""
        if uploaded is not None:
            image_ph = "Using your uploaded image — leave blank"
        elif self.existing_is_file:
            image_ph = "An uploaded image is attached — leave blank to keep it"
        else:
            image_ph = "https://example.com/image.png"

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
            default=url_default,
            placeholder=image_ph,
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

    async def _resolve_image(self) -> str | None:
        """Decide the card's image: new upload > URL field > existing upload."""
        if self.uploaded is not None:
            return await _save_uploaded_image(self.guild_id, self.name, self.uploaded)
        url_field = self.image_input.value.strip()
        if url_field:
            if not _is_url(url_field):
                raise ValueError("the image URL must start with http:// or https://")
            return url_field
        if self.existing_is_file:
            return self.existing_image  # keep the previously uploaded image
        return None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        buttons, errors = parse_button_lines(self.buttons_input.value)
        if errors:
            await interaction.response.send_message(
                "Couldn't save — button problems:\n" + "\n".join(f"• {e}" for e in errors),
                ephemeral=True,
            )
            return

        # Saving an uploaded image touches the disk/network, so defer first.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            image_value = await self._resolve_image()
        except ValueError as exc:
            await interaction.followup.send(f"Couldn't save — {exc}.", ephemeral=True)
            return

        await self.bot.db.upsert_card(
            guild_id=self.guild_id,
            name=self.name,
            title=self.title_input.value.strip(),
            description=self.desc_input.value.strip(),
            image_url=image_value,
            color=self.color_input.value.strip() or None,
            buttons_json=json.dumps(buttons),
        )

        card = await self.bot.db.get_card(self.guild_id, self.name)
        note = ""
        if card and card.message_id and card.channel_id:
            updated = await _edit_live_message(self.bot, card)
            note = " Live posted card updated." if updated else " (couldn't update the posted card)"
        await interaction.followup.send(
            f"✅ Saved card **{self.name}**.{note}\nUse `/card post name:{self.name}` to post it.",
            ephemeral=True,
        )


async def _edit_live_message(bot: commands.Bot, card: Card) -> bool:
    channel = bot.get_channel(card.channel_id or 0)
    if not isinstance(channel, discord.abc.Messageable):
        return False
    try:
        message = await channel.fetch_message(card.message_id or 0)
        embed, view, files = render_card(card)
        await message.edit(embed=embed, view=view, attachments=files)
        return True
    except (discord.NotFound, discord.HTTPException):
        return False


# ── Channel picker (shown when /card post is used without a channel) ──
class ChannelPickView(discord.ui.View):
    def __init__(self, cog: "Cards", name: str, author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.name = name
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This picker isn't for you.", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="Choose a channel to post in…",
        min_values=1,
        max_values=1,
    )
    async def pick(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect) -> None:
        chosen = select.values[0]
        channel = interaction.guild.get_channel(chosen.id) if interaction.guild else None
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.edit_message(
                content="That channel can't receive messages.", view=None
            )
            return
        try:
            message = await self.cog._publish(interaction.guild_id or 0, self.name, channel)
        except discord.Forbidden:
            await interaction.response.edit_message(
                content=f"I don't have permission to post in {channel.mention}.", view=None
            )
            return
        if message is None:
            await interaction.response.edit_message(
                content=f"Card **{self.name}** no longer exists.", view=None
            )
            return
        await interaction.response.edit_message(
            content=f"✅ Posted **{self.name}** in {channel.mention}. Edits will update it live.",
            view=None,
        )


# ── Commands ─────────────────────────────────────────────────
class Cards(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    card_group = app_commands.Group(
        name="card",
        description="Create, edit and post interactive cards.",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def _publish(
        self, guild_id: int, name: str, channel: discord.abc.Messageable
    ) -> discord.Message | None:
        """Post a card to a channel and remember where it went (for live edits)."""
        card = await self.bot.db.get_card(guild_id, name)
        if card is None:
            return None
        embed, view, files = render_card(card)
        message = await channel.send(embed=embed, view=view, files=files)
        await self.bot.db.set_card_message(guild_id, name, channel.id, message.id)  # type: ignore[attr-defined]
        return message

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
    @app_commands.describe(
        name="A short id for the card, e.g. 'welcome' or 'launch'",
        image="Optional: upload an image from your device to use on the card",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def card_edit(
        self,
        interaction: discord.Interaction,
        name: str,
        image: discord.Attachment | None = None,
    ) -> None:
        if image is not None and not (image.content_type or "").lower().startswith("image/"):
            await interaction.response.send_message(
                "That file isn't an image. Please upload a PNG, JPG, GIF or WEBP.",
                ephemeral=True,
            )
            return
        existing = await self.bot.db.get_card(interaction.guild_id or 0, name)
        modal = CardModal(self.bot, interaction.guild_id or 0, name, existing, uploaded=image)
        await interaction.response.send_modal(modal)

    @card_edit.autocomplete("name")
    async def _edit_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="post", description="Post a saved card to a channel.")
    @app_commands.describe(
        name="The card id", channel="Where to post (leave empty to pick from a menu)"
    )
    @app_commands.checks.has_permissions(administrator=True)
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

        # No channel given → show a channel picker so it's easy to choose.
        if channel is None:
            view = ChannelPickView(self, name, interaction.user.id)
            await interaction.response.send_message(
                f"Where should I post **{name}**?", view=view, ephemeral=True
            )
            return

        try:
            message = await self._publish(interaction.guild_id or 0, name, channel)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"I don't have permission to post in {channel.mention}.", ephemeral=True
            )
            return
        if message is None:
            await interaction.response.send_message(
                f"No card named **{name}**.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Posted **{name}** in {channel.mention}. Edits will update it live.",
            ephemeral=True,
        )

    @card_post.autocomplete("name")
    async def _post_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="show", description="Preview a saved card (only you see it).")
    @app_commands.checks.has_permissions(administrator=True)
    async def card_show(self, interaction: discord.Interaction, name: str) -> None:
        card = await self.bot.db.get_card(interaction.guild_id or 0, name)
        if not card:
            await interaction.response.send_message(f"No card named **{name}**.", ephemeral=True)
            return
        embed, view, files = render_card(card)
        await interaction.response.send_message(
            embed=embed, view=view, files=files, ephemeral=True
        )

    @card_show.autocomplete("name")
    async def _show_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)

    @card_group.command(name="list", description="List all saved cards.")
    @app_commands.checks.has_permissions(administrator=True)
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
    @app_commands.checks.has_permissions(administrator=True)
    async def card_delete(self, interaction: discord.Interaction, name: str) -> None:
        ok = await self.bot.db.delete_card(interaction.guild_id or 0, name)
        msg = f"🗑️ Deleted **{name}**." if ok else f"No card named **{name}**."
        await interaction.response.send_message(msg, ephemeral=True)

    @card_delete.autocomplete("name")
    async def _delete_ac(self, interaction, current):  # noqa: ANN001
        return await self._name_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Cards(bot))
