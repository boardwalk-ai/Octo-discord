"""Central configuration loaded from environment variables."""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _split(name: str) -> list[str]:
    raw = _get(name)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Discord ──────────────────────────────────────────────────
DISCORD_TOKEN = _get("DISCORD_TOKEN")
GUILD_ID = int(_get("GUILD_ID") or 0) or None

# ── OpenRouter ───────────────────────────────────────────────
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = _get("OPENROUTER_MODEL") or "deepseek/deepseek-chat"
OPENROUTER_FALLBACK_MODEL = _get("OPENROUTER_FALLBACK_MODEL")
OPENROUTER_ALLOWED_MODELS = _split("OPENROUTER_ALLOWED_MODELS") or [OPENROUTER_MODEL]
OPENROUTER_APP_URL = _get("OPENROUTER_APP_URL") or "https://openrouter.ai"
OPENROUTER_APP_NAME = _get("OPENROUTER_APP_NAME") or "Octo"

OCTO_SYSTEM_PROMPT = (
    _get("OCTO_SYSTEM_PROMPT")
    or "You are Octo, a friendly and concise Discord assistant. Keep replies short and helpful."
)
AI_HISTORY_LIMIT = int(_get("AI_HISTORY_LIMIT") or 8)

# ── Misc ─────────────────────────────────────────────────────
TIMEZONE_NAME = _get("TIMEZONE") or "UTC"
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:  # noqa: BLE001 - fall back to UTC on a bad tz name
    TIMEZONE = ZoneInfo("UTC")
    TIMEZONE_NAME = "UTC"

DATABASE_PATH = _get("DATABASE_PATH") or "octo.db"


def validate() -> list[str]:
    """Return a list of human-readable problems with the current config."""
    problems: list[str] = []
    if not DISCORD_TOKEN:
        problems.append("DISCORD_TOKEN is not set.")
    if not OPENROUTER_API_KEY:
        problems.append("OPENROUTER_API_KEY is not set (AI chat will be disabled).")
    return problems
