"""Scheduled messages: one-off or recurring posts to a channel."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from db import ScheduledMessage

log = logging.getLogger("octo.scheduler")

_REPEATS = ("once", "hourly", "daily", "weekly")
_DELTAS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(seconds=30)
    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            due = await self.bot.db.due_schedules(now.isoformat())
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            log.exception("Failed to read due schedules: %s", exc)
            return

        for sched in due:
            await self._fire(sched, now)

    @tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _fire(self, sched: ScheduledMessage, now: datetime) -> None:
        channel = self.bot.get_channel(sched.channel_id)
        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(sched.content)
            except discord.HTTPException as exc:
                log.warning("Failed to send schedule %d: %s", sched.id, exc)
        else:
            log.warning("Schedule %d has an invalid channel %d", sched.id, sched.channel_id)

        if sched.repeat == "once":
            await self.bot.db.set_enabled(sched.id, False)
            return

        # Advance past 'now' so a long downtime doesn't cause a burst.
        next_run = datetime.fromisoformat(sched.next_run)
        delta = _DELTAS[sched.repeat]
        while next_run <= now:
            next_run += delta
        await self.bot.db.update_next_run(sched.id, next_run.isoformat())

    # ── /schedule commands ───────────────────────────────────
    schedule_group = app_commands.Group(
        name="schedule", description="Manage scheduled messages."
    )

    @schedule_group.command(name="add", description="Schedule a message.")
    @app_commands.describe(
        when="When to send: 'HH:MM' or 'YYYY-MM-DD HH:MM' (server timezone)",
        message="The message to send",
        repeat="How often to repeat",
        channel="Channel to post in (defaults to here)",
    )
    @app_commands.choices(
        repeat=[app_commands.Choice(name=r, value=r) for r in _REPEATS]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def schedule_add(
        self,
        interaction: discord.Interaction,
        when: str,
        message: str,
        repeat: app_commands.Choice[str] | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        repeat_value = repeat.value if repeat else "once"
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.Messageable):
            await interaction.response.send_message("Invalid channel.", ephemeral=True)
            return

        parsed = _parse_when(when)
        if parsed is None:
            await interaction.response.send_message(
                "Couldn't parse the time. Use `HH:MM` or `YYYY-MM-DD HH:MM`.",
                ephemeral=True,
            )
            return

        sid = await self.bot.db.add_schedule(
            guild_id=interaction.guild_id or 0,
            channel_id=target.id,  # type: ignore[union-attr]
            content=message,
            repeat=repeat_value,
            next_run=parsed.astimezone(timezone.utc).isoformat(),
            created_by=interaction.user.id,
        )
        local = parsed.astimezone(config.TIMEZONE)
        await interaction.response.send_message(
            f"✅ Scheduled **#{sid}** — {repeat_value}, next at "
            f"`{local:%Y-%m-%d %H:%M}` ({config.TIMEZONE_NAME}) in {target.mention}.",  # type: ignore[union-attr]
            ephemeral=True,
        )

    @schedule_group.command(name="list", description="List scheduled messages.")
    async def schedule_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.list_schedules(interaction.guild_id or 0)
        if not rows:
            await interaction.response.send_message("No scheduled messages.", ephemeral=True)
            return

        lines = []
        for s in rows:
            local = datetime.fromisoformat(s.next_run).astimezone(config.TIMEZONE)
            status = "" if s.enabled else " *(done)*"
            preview = s.content if len(s.content) <= 40 else s.content[:37] + "..."
            lines.append(
                f"**#{s.id}** · {s.repeat} · `{local:%Y-%m-%d %H:%M}` · <#{s.channel_id}>"
                f"{status}\n> {preview}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @schedule_group.command(name="remove", description="Delete a scheduled message by id.")
    @app_commands.describe(schedule_id="The id shown in /schedule list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def schedule_remove(
        self, interaction: discord.Interaction, schedule_id: int
    ) -> None:
        ok = await self.bot.db.delete_schedule(interaction.guild_id or 0, schedule_id)
        msg = f"🗑️ Removed schedule #{schedule_id}." if ok else "No such schedule."
        await interaction.response.send_message(msg, ephemeral=True)


def _parse_when(raw: str) -> datetime | None:
    """Parse user input in the configured timezone; return a tz-aware datetime.

    'HH:MM'              → next occurrence today or tomorrow
    'YYYY-MM-DD HH:MM'   → that exact local time
    """
    raw = raw.strip()
    now = datetime.now(config.TIMEZONE)

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=config.TIMEZONE)
        except ValueError:
            pass

    try:
        t = datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None
    candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
