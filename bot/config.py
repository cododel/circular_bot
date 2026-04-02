"""Configuration module."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Optional whitelist: comma-separated list of allowed user IDs
ALLOW_USER_IDS = os.getenv("ALLOW_USER_IDS", "")
if ALLOW_USER_IDS:
    ALLOWED_USERS = {int(uid.strip()) for uid in ALLOW_USER_IDS.split(",") if uid.strip().isdigit()}
else:
    ALLOWED_USERS = None  # None means allow all

# Video processing settings (all configurable via ENV)
PROCESSING_TIMEOUT = int(os.getenv("PROCESSING_TIMEOUT", "480"))  # seconds
PROGRESS_UPDATE_INTERVAL = int(os.getenv("PROGRESS_UPDATE_INTERVAL", "3"))  # seconds (temporary stub)
ZOOM_SCALE = float(os.getenv("ZOOM_SCALE", "1.08"))  # background zoom
CIRCLE_SIZE_RATIO = float(os.getenv("CIRCLE_SIZE_RATIO", "0.82"))  # circle size relative to video
BACKGROUND_BLUR = int(os.getenv("BACKGROUND_BLUR", "40"))  # boxblur amount
TEXT_FONT_SIZE_RATIO = float(os.getenv("TEXT_FONT_SIZE_RATIO", "0.035"))  # font size relative to video height
TEXT_PADDING_RATIO = float(os.getenv("TEXT_PADDING_RATIO", "0.02"))  # text padding from circle
BRIGHTNESS_ADJUST = float(os.getenv("BRIGHTNESS_ADJUST", "-0.15"))  # background brightness
CONTRAST_ADJUST = float(os.getenv("CONTRAST_ADJUST", "1.1"))  # background contrast

TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

ASPECT_RATIOS = {
    "9:16": (720, 1280),
    "1:1": (1080, 1080),
    "16:9": (1280, 720),
    "4:5": (1080, 1350),
}
