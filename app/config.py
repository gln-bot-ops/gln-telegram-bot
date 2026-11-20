"""Configuration from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

# Telegram bot token from BotFather. Required.
BOT_TOKEN = os.getenv("GLN_BOT_TOKEN", "")

# Comma-separated Telegram user IDs with access to admin commands.
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}

# Postgres connection string (e.g. Neon). When set, it wins over SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# SQLite database file location, used when DATABASE_URL is not set.
DB_PATH = os.getenv("GLN_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "gln_bot.db"))
