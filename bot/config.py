"""Configuration loaded from environment variables (or a .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: str
    admin_ids: frozenset[int]
    db_path: str
    timezone: ZoneInfo


def load_config() -> Config:
    _load_dotenv(Path(".env"))

    token = os.environ.get("BOT_TOKEN", "").strip()
    channel = os.environ.get("CHANNEL_ID", "").strip()
    admins_raw = os.environ.get("ADMIN_IDS", "").strip()

    missing = [name for name, val in (("BOT_TOKEN", token), ("CHANNEL_ID", channel), ("ADMIN_IDS", admins_raw)) if not val]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    try:
        admin_ids = frozenset(int(x) for x in admins_raw.replace(" ", "").split(",") if x)
    except ValueError:
        raise SystemExit("ADMIN_IDS must be a comma-separated list of numeric Telegram user IDs")

    return Config(
        bot_token=token,
        channel_id=channel,
        admin_ids=admin_ids,
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
        timezone=ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tehran")),
    )
