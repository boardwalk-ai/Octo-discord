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
        name="repost",
        description="Configure marketing-video reposting.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @repost_group.command(name="setup", description="Set the source and target channels.")
    @app_commands.describe(
        source="Channel where admins upload videos",
        target="Channel where Octo reposts them",
    )
    @app_commands.checks.has_permissions(administrator=True)
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
    @app_commands.checks.has_permissions(administrator=True)
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
        header = f"📣 **{caption}**" if caption else None
        size_limit = getattr(message.guild, "filesize_limit", 25 * 1024 * 1024)

        posted_any = False
        for video in videos:
            if await self._repost_one(target, video, header, size_limit):
                posted_any = True

        if posted_any:
            try:
                await message.add_reaction("✅")
            except discord.HTTPException:
                pass

    async def _repost_one(
        self,
        target: discord.abc.Messageable,
        video: discord.Attachment,
        header: str | None,
        size_limit: int,
    ) -> bool:
        """Re-upload the video; if it's too big, fall back to posting its link."""
        # Only try a re-upload if it fits under the server's file-size limit.
        if video.size <= size_limit:
            try:
                file = await video.to_file()
                await target.send(content=header, file=file)
                return True
            except discord.HTTPException as exc:
                log.warning("Re-upload of %s failed (%s); falling back to link.", video.filename, exc)
            except discord.NotFound as exc:
                log.warning("Could not fetch attachment %s: %s", video.filename, exc)
                return False

        # Fallback: share the original CDN link so the video still gets out.
        link_body = f"{header}\n{video.url}" if header else video.url
        try:
            await target.send(link_body)
            return True
        except discord.HTTPException as exc:
            log.warning("Link fallback for %s failed: %s", video.filename, exc)
            return False


def _is_video(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("video/"):
        return True
    return attachment.filename.lower().endswith(_VIDEO_EXTS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VideoRepost(bot))
