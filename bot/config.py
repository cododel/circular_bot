"""Configuration module."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DEFAULT_OVERLAY_TEXT = os.getenv("DEFAULT_OVERLAY_TEXT", "TG: @cododel_dev")

# Optional whitelist: comma-separated list of allowed user IDs
ALLOW_USER_IDS = os.getenv("ALLOW_USER_IDS", "")
if ALLOW_USER_IDS:
    ALLOWED_USERS = {int(uid.strip()) for uid in ALLOW_USER_IDS.split(",") if uid.strip().isdigit()}
else:
    ALLOWED_USERS = None  # None means allow all

TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

ASPECT_RATIOS = {
    "9:16": (720, 1280),
    "1:1": (1080, 1080),
    "16:9": (1280, 720),
    "4:5": (1080, 1350),
}
