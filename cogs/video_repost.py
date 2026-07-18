"""Admin posts a marketing video in a source channel → Octo reposts it
to a target channel as a clean card."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("octo.repost")

_SOURCE_KEY = "repost_source_channel"
_TARGET_KEY = "repost_target_channel"

_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")


class VideoRepost(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    repost_group = app_commands.Group(
        name="repost", description="Configure marketing-video reposting."
    )

    @repost_group.command(name="setup", description="Set the source and target channels.")
    @app_commands.describe(
        source="Channel where admins upload videos",
        target="Channel where Octo reposts them",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def repost_setup(
        self,
        interaction: discord.Interaction,
        source: discord.TextChannel,
        target: discord.TextChannel,
    ) -> None:
        guild_id = interaction.guild_id or 0
        await self.bot.db.set_setting(guild_id, _SOURCE_KEY, str(source.id))
        await self.bot.db.set_setting(guild_id, _TARGET_KEY, str(target.id))
        await interaction.response.send_message(
            f"✅ Videos posted in {source.mention} will be reposted to {target.mention}.",
            ephemeral=True,
        )

    @repost_group.command(name="status", description="Show the current repost configuration.")
    async def repost_status(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        source = await self.bot.db.get_setting(guild_id, _SOURCE_KEY)
        target = await self.bot.db.get_setting(guild_id, _TARGET_KEY)
        if not source or not target:
            await interaction.response.send_message(
                "Reposting is not configured. Use `/repost setup`.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Source: <#{source}>\nTarget: <#{target}>", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        source = await self.bot.db.get_setting(message.guild.id, _SOURCE_KEY)
        target_id = await self.bot.db.get_setting(message.guild.id, _TARGET_KEY)
        if not source or not target_id or str(message.channel.id) != source:
            return

        videos = [a for a in message.attachments if _is_video(a)]
        if not videos:
            return

        target = message.guild.get_channel(int(target_id))
        if not isinstance(target, discord.abc.Messageable):
            log.warning("Repost target channel %s is invalid.", target_id)
            return

        caption = message.content.strip()
        for video in videos:
            try:
                file = await video.to_file()
            except (discord.HTTPException, discord.NotFound) as exc:
                log.warning("Could not fetch attachment %s: %s", video.filename, exc)
                continue
            content = f"📣 **{caption}**" if caption else None
            await target.send(content=content, file=file)

        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass


def _is_video(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("video/"):
        return True
    return attachment.filename.lower().endswith(_VIDEO_EXTS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VideoRepost(bot))
