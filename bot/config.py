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

# YouTube-like ambient background. Each frame is reduced to a tiny colour map,
# smoothed over time, blurred and stretched back over the canvas. Working on a
# ~96px map keeps a very wide blur cheap and turns the frame into large colour
# patches that still carry its spatial layout (light on the left stays on the
# left), unlike a single average colour.
AMBIENT_MAP_WIDTH = int(os.getenv("AMBIENT_MAP_WIDTH", "96"))
AMBIENT_BLUR_SIGMA = float(os.getenv("AMBIENT_BLUR_SIGMA", "6"))
AMBIENT_SATURATION = float(os.getenv("AMBIENT_SATURATION", "1.30"))
# Temporal smoothing, applied on the colour map as an exponential moving
# average over the last AMBIENT_SMOOTHING_FRAMES frames. Without it the
# background flickers on every fast motion. Lower alpha = slower, calmer
# colour drift; 1 frame disables the smoothing entirely.
# 10 frames at alpha 0.25 is a ~0.13 s time constant on a 30 fps video note,
# and the oldest frame still carries 7.5% of the weight, so the window is not
# truncated where it would show.
AMBIENT_SMOOTHING_FRAMES = int(os.getenv("AMBIENT_SMOOTHING_FRAMES", "10"))
AMBIENT_SMOOTHING_ALPHA = float(os.getenv("AMBIENT_SMOOTHING_ALPHA", "0.25"))
BRIGHTNESS_ADJUST = float(os.getenv("BRIGHTNESS_ADJUST", "-0.24"))
CONTRAST_ADJUST = float(os.getenv("CONTRAST_ADJUST", "1.05"))

# Weakly blurred square immediately behind the clear circle.
LOCAL_BACKGROUND_SIZE_RATIO = float(os.getenv("LOCAL_BACKGROUND_SIZE_RATIO", "1.14"))
LOCAL_BACKGROUND_BLUR = float(os.getenv("LOCAL_BACKGROUND_BLUR", "7"))
LOCAL_BACKGROUND_BRIGHTNESS = float(os.getenv("LOCAL_BACKGROUND_BRIGHTNESS", "-0.10"))
LOCAL_BACKGROUND_CONTRAST = float(os.getenv("LOCAL_BACKGROUND_CONTRAST", "1.03"))
LOCAL_BACKGROUND_OPACITY = float(os.getenv("LOCAL_BACKGROUND_OPACITY", "0.90"))
LOCAL_BACKGROUND_FEATHER_RATIO = float(os.getenv("LOCAL_BACKGROUND_FEATHER_RATIO", "0.045"))

# Video notes carry Telegram's white round mask baked into the file: outside
# the inscribed circle every frame is pure white. Only the inner circle may
# feed the ambient and backdrop layers, so they are sampled from the largest
# square that fits inside it (side <= diameter / sqrt(2) ~= 0.707).
VIDEO_NOTE_SAFE_CROP = float(os.getenv("VIDEO_NOTE_SAFE_CROP", "0.70"))
# The baked mask has an antialiased rim. Zoom the visible circle slightly so
# that rim falls outside the crop instead of leaving a pale outline.
VIDEO_NOTE_EDGE_TRIM = float(os.getenv("VIDEO_NOTE_EDGE_TRIM", "0.985"))

# Curved signature. Font size, gap and tracking are relative to the circle,
# so the result stays visually consistent across 9:16, 1:1, 16:9 and 4:5.
TEXT_FONT_SIZE_RATIO = float(os.getenv("TEXT_FONT_SIZE_RATIO", "0.085"))
TEXT_MIN_FONT_SIZE_RATIO = float(os.getenv("TEXT_MIN_FONT_SIZE_RATIO", "0.022"))
# Safety gap between the signature and the frame edge, relative to the shorter
# frame side. The upper font size is capped by it, so a large ratio degrades
# gracefully in tight formats (16:9, 1:1) instead of clipping the glyphs.
TEXT_FRAME_MARGIN_RATIO = float(os.getenv("TEXT_FRAME_MARGIN_RATIO", "0.012"))
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
