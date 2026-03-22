import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/klinkeroblik.db")
DEFAULT_LANGUAGE = "uk"
DEFAULT_CURRENCY = "PLN"
DEFAULT_TIMEZONE = "Europe/Warsaw"
INVITE_CODE_EXPIRY_DAYS = 7
