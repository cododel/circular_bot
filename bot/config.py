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
PROCESSING_TIMEOUT = int(os.getenv("PROCESSING_TIMEOUT", "480"))
PROGRESS_UPDATE_INTERVAL = int(os.getenv("PROGRESS_UPDATE_INTERVAL", "3"))

# Main composition
CIRCLE_SIZE_RATIO = float(os.getenv("CIRCLE_SIZE_RATIO", "0.82"))
ZOOM_SCALE = float(os.getenv("ZOOM_SCALE", "1.08"))

# Large ambient background. It is rendered at a reduced resolution before
# being upscaled, which produces a smooth blur without an expensive full-size
# Gaussian pass on every frame.
AMBIENT_DOWNSCALE = float(os.getenv("AMBIENT_DOWNSCALE", "0.25"))
BACKGROUND_BLUR = float(os.getenv("BACKGROUND_BLUR", "36"))
BRIGHTNESS_ADJUST = float(os.getenv("BRIGHTNESS_ADJUST", "-0.24"))
CONTRAST_ADJUST = float(os.getenv("CONTRAST_ADJUST", "1.05"))

# Weakly blurred square immediately behind the clear circle.
LOCAL_BACKGROUND_SIZE_RATIO = float(os.getenv("LOCAL_BACKGROUND_SIZE_RATIO", "1.14"))
LOCAL_BACKGROUND_BLUR = float(os.getenv("LOCAL_BACKGROUND_BLUR", "7"))
LOCAL_BACKGROUND_BRIGHTNESS = float(os.getenv("LOCAL_BACKGROUND_BRIGHTNESS", "-0.10"))
LOCAL_BACKGROUND_CONTRAST = float(os.getenv("LOCAL_BACKGROUND_CONTRAST", "1.03"))
LOCAL_BACKGROUND_OPACITY = float(os.getenv("LOCAL_BACKGROUND_OPACITY", "0.90"))
LOCAL_BACKGROUND_FEATHER_RATIO = float(os.getenv("LOCAL_BACKGROUND_FEATHER_RATIO", "0.045"))

# Curved signature. Font size, gap and tracking are relative to the circle,
# so the result stays visually consistent across 9:16, 1:1, 16:9 and 4:5.
TEXT_FONT_SIZE_RATIO = float(os.getenv("TEXT_FONT_SIZE_RATIO", "0.060"))
TEXT_MIN_FONT_SIZE_RATIO = float(os.getenv("TEXT_MIN_FONT_SIZE_RATIO", "0.022"))
TEXT_PADDING_RATIO = float(os.getenv("TEXT_PADDING_RATIO", "0.018"))
TEXT_TRACKING_RATIO = float(os.getenv("TEXT_TRACKING_RATIO", "0.26"))
TEXT_MIN_TRACKING_RATIO = float(os.getenv("TEXT_MIN_TRACKING_RATIO", "0.035"))
TEXT_ARC_END_DEG = float(os.getenv("TEXT_ARC_END_DEG", "38"))
TEXT_ARC_MAX_SPAN_DEG = float(os.getenv("TEXT_ARC_MAX_SPAN_DEG", "82"))

# Incoming media limits. The Bot API refuses to serve files larger than 20 MB,
# so reject them early with a readable message. A local Bot API server lifts
# that restriction — set 0 to disable the check.
MAX_VIDEO_SIZE_MB = float(os.getenv("MAX_VIDEO_SIZE_MB", "20"))
MAX_VIDEO_SIZE_BYTES = int(MAX_VIDEO_SIZE_MB * 1024 * 1024)

# Performance settings
FFMPEG_THREADS = int(os.getenv("FFMPEG_THREADS", "0"))  # 0 = auto

TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

ASPECT_RATIOS = {
    "9:16": (720, 1280),
    "1:1": (1080, 1080),
    "16:9": (1280, 720),
    "4:5": (1080, 1350),
}
