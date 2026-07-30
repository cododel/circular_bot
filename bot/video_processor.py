"""Video processing with FFmpeg (async version)."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import math
import os
import re
import tempfile
import time
from typing import Awaitable, Callable, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.config import (
    AMBIENT_BLUR_SIGMA,
    AMBIENT_MAP_WIDTH,
    AMBIENT_SATURATION,
    AMBIENT_SMOOTHING_ALPHA,
    AMBIENT_SMOOTHING_FRAMES,
    BRIGHTNESS_ADJUST,
    CIRCLE_SIZE_RATIO,
    CONTRAST_ADJUST,
    FFMPEG_THREADS,
    LOCAL_BACKGROUND_BLUR,
    LOCAL_BACKGROUND_BRIGHTNESS,
    LOCAL_BACKGROUND_CONTRAST,
    LOCAL_BACKGROUND_OPACITY,
    LOCAL_BACKGROUND_SIZE_RATIO,
    LOCAL_BACKGROUND_SQUARE_FEATHER_RATIO,
    PROCESSING_TIMEOUT,
    PROGRESS_UPDATE_INTERVAL,
    TEMP_DIR,
    TEXT_ARC_END_DEG,
    TEXT_ARC_MAX_SPAN_DEG,
    TEXT_FONT_SIZE_RATIO,
    TEXT_FRAME_MARGIN_RATIO,
    TEXT_MIN_FONT_SIZE_RATIO,
    TEXT_MIN_TRACKING_RATIO,
    TEXT_PADDING_RATIO,
    TEXT_TRACKING_RATIO,
    VIDEO_NOTE_EDGE_TRIM,
    VIDEO_NOTE_SAFE_CROP,
    ZOOM_SCALE,
)

logger = logging.getLogger(__name__)

_RESAMPLING = getattr(Image, "Resampling", Image)
_LANCZOS = _RESAMPLING.LANCZOS
_BICUBIC = _RESAMPLING.BICUBIC
_TEXT_RENDER_SCALE = 3
_MASK_RENDER_SCALE = 4
_PROBE_TIMEOUT = 30

# Telegram bakes a white round mask into video notes, so they need their own
# sampling rules. Everything else is treated as an ordinary rectangular video.
VIDEO_NOTE_KIND = "video_note"


@dataclass(frozen=True)
class ArcTextLayout:
    """Resolved curved-text geometry in output pixels."""

    text: str
    font_size: int
    font_path: Optional[str]
    path_radius: float
    end_angle_deg: float
    span_deg: float
    tracking: float
    advances: Tuple[float, ...]


_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Windows/Fonts/arial.ttf",
)


def _even(value: float, minimum: int = 2) -> int:
    """Round a dimension down to a positive even integer."""
    result = max(minimum, int(value))
    return result if result % 2 == 0 else result - 1


def _temporary_png_path(prefix: str) -> str:
    """Reserve a unique PNG path inside TEMP_DIR."""
    fd, path = tempfile.mkstemp(prefix=f"{prefix}_", suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    return path


def _resolve_font_path() -> Optional[str]:
    for path in _FONT_PATHS:
        if os.path.exists(path):
            return path
    return None


def _load_font(size: int, font_path: Optional[str] = None) -> ImageFont.ImageFont:
    size = max(1, int(size))
    resolved_path = font_path or _resolve_font_path()
    if resolved_path:
        try:
            return ImageFont.truetype(resolved_path, size)
        except (OSError, ValueError):
            logger.warning("Failed to load font %s", resolved_path, exc_info=True)

    try:
        # Pillow 10.1+ supports a scalable default font.
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _normalize_overlay_text(text: str) -> str:
    """Curved text is single-line; collapse control whitespace safely."""
    return re.sub(r"\s+", " ", text or "").strip()


def _glyph_advance(font: ImageFont.ImageFont, character: str) -> float:
    try:
        return max(0.0, float(font.getlength(character)))
    except (AttributeError, TypeError):
        bbox = font.getbbox(character)
        return max(0.0, float(bbox[2] - bbox[0]))


def _measure_arc_text(
    text: str,
    font: ImageFont.ImageFont,
    tracking: float,
) -> tuple[Tuple[float, ...], float]:
    advances = tuple(_glyph_advance(font, character) for character in text)
    total = sum(advances) + max(0, len(advances) - 1) * tracking
    return advances, total


def _layout_for_size(
    text: str,
    circle_size: int,
    font_size: int,
    font_path: Optional[str],
    tracking: Optional[float] = None,
) -> ArcTextLayout:
    font = _load_font(font_size, font_path)
    if tracking is None:
        tracking = max(0.0, font_size * TEXT_TRACKING_RATIO)
    advances, text_length = _measure_arc_text(text, font, tracking)

    visible_radius = circle_size / 2.0
    gap = circle_size * TEXT_PADDING_RATIO
    # The path runs through glyph centres, keeping the complete glyph body
    # outside the clear circle rather than putting its baseline on the edge.
    path_radius = visible_radius + gap + font_size * 0.55
    span_deg = math.degrees(text_length / path_radius) if path_radius else 0.0

    return ArcTextLayout(
        text=text,
        font_size=font_size,
        font_path=font_path,
        path_radius=path_radius,
        end_angle_deg=TEXT_ARC_END_DEG,
        span_deg=span_deg,
        tracking=tracking,
        advances=advances,
    )


def _stroke_width(font_size: float) -> int:
    """Outline width used by the glyph renderer."""
    return max(1, int(round(font_size * 0.035)))


def _outer_extent(layout: ArcTextLayout) -> float:
    """Distance from the frame centre to the outer edge of the drawn glyphs.

    Every glyph is rotated to the tangent and pasted centred on the path, so
    its own downward direction points away from the circle: half of the tallest
    glyph box plus the outline sticks out beyond the path radius.
    """
    font = _load_font(layout.font_size, layout.font_path)
    bbox = font.getbbox(layout.text)
    glyph_height = max(0.0, float(bbox[3] - bbox[1]))
    return layout.path_radius + glyph_height / 2.0 + _stroke_width(layout.font_size)


def _layout_fits_frame(
    layout: ArcTextLayout,
    frame_size: Optional[Tuple[int, int]],
) -> bool:
    """Check that the arc stays inside the frame with a safety margin."""
    if frame_size is None:
        return True

    width, height = frame_size
    margin = min(width, height) * TEXT_FRAME_MARGIN_RATIO
    extent = _outer_extent(layout)

    start_deg = layout.end_angle_deg
    end_deg = start_deg + layout.span_deg
    # Sample the arc ends plus every axis extremum they enclose.
    angles = [start_deg, end_deg]
    angles += [deg for deg in (0.0, 90.0, 180.0, 270.0) if start_deg < deg < end_deg]
    offsets = [
        (extent * math.cos(math.radians(deg)), extent * math.sin(math.radians(deg)))
        for deg in angles
    ]

    center_x, center_y = width / 2.0, height / 2.0
    return all(
        margin <= center_x + dx <= width - margin
        and margin <= center_y + dy <= height - margin
        for dx, dy in offsets
    )


def fit_text_to_arc(
    text: str,
    circle_size: int,
    frame_size: Optional[Tuple[int, int]] = None,
) -> ArcTextLayout:
    """Fit text to the lower-right circle arc by scaling and, last, ellipsis."""
    normalized_text = _normalize_overlay_text(text)
    font_path = _resolve_font_path()

    max_font_size = max(8, int(round(circle_size * TEXT_FONT_SIZE_RATIO)))
    min_font_size = max(8, int(round(circle_size * TEXT_MIN_FONT_SIZE_RATIO)))
    min_font_size = min(min_font_size, max_font_size)

    if not normalized_text:
        return _layout_for_size("", circle_size, max_font_size, font_path)

    maximum_span_radians = math.radians(TEXT_ARC_MAX_SPAN_DEG)

    for font_size in range(max_font_size, min_font_size - 1, -1):
        # Keep the airy tracking used by the reference design for short labels,
        # but contract it before shrinking the font for long usernames/text.
        preferred_tracking = max(0.0, font_size * TEXT_TRACKING_RATIO)
        minimum_tracking = max(0.0, font_size * TEXT_MIN_TRACKING_RATIO)
        base_layout = _layout_for_size(
            normalized_text,
            circle_size,
            font_size,
            font_path,
            tracking=0.0,
        )
        glyph_length = sum(base_layout.advances)
        capacity = base_layout.path_radius * maximum_span_radians
        gap_count = max(0, len(normalized_text) - 1)

        if gap_count == 0:
            tracking = 0.0
        else:
            available_tracking = (capacity - glyph_length) / gap_count
            if available_tracking < minimum_tracking:
                continue
            tracking = min(preferred_tracking, available_tracking)

        layout = _layout_for_size(
            normalized_text,
            circle_size,
            font_size,
            font_path,
            tracking=tracking,
        )
        # A generous upper font size is only usable where the frame leaves room
        # for it; tight formats keep shrinking instead of clipping the arc.
        if not _layout_fits_frame(layout, frame_size):
            continue

        return layout

    # A custom label can still exceed the configured arc when this function is
    # reused outside the 50-character UI limit. Preserve the beginning and make
    # truncation explicit rather than rendering unreadably tiny text.
    candidate = normalized_text
    while len(candidate) > 1:
        candidate = candidate[:-1].rstrip()
        rendered = f"{candidate}…"
        layout = _layout_for_size(
            rendered,
            circle_size,
            min_font_size,
            font_path,
            tracking=min_font_size * TEXT_MIN_TRACKING_RATIO,
        )
        if layout.span_deg <= TEXT_ARC_MAX_SPAN_DEG:
            return layout

    return _layout_for_size("…", circle_size, min_font_size, font_path)


def _render_glyph(
    character: str,
    font_size: int,
    font_path: Optional[str],
    rotation_deg: float,
) -> Optional[Image.Image]:
    """Render one rotated glyph with supersampling for clean tangents."""
    if character.isspace():
        return None

    scale = _TEXT_RENDER_SCALE
    font = _load_font(font_size * scale, font_path)
    stroke_width = _stroke_width(font_size * scale)

    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    bbox = probe_draw.textbbox(
        (0, 0),
        character,
        font=font,
        stroke_width=stroke_width,
    )
    glyph_width = max(1, bbox[2] - bbox[0])
    glyph_height = max(1, bbox[3] - bbox[1])
    padding = max(6 * scale, stroke_width * 3)

    glyph = Image.new(
        "RGBA",
        (glyph_width + padding * 2, glyph_height + padding * 2),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(glyph)
    draw.text(
        (padding - bbox[0], padding - bbox[1]),
        character,
        font=font,
        fill=(255, 255, 255, 232),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 65),
    )

    rotated = glyph.rotate(rotation_deg, expand=True, resample=_BICUBIC)
    target_size = (
        max(1, int(round(rotated.width / scale))),
        max(1, int(round(rotated.height / scale))),
    )
    return rotated.resize(target_size, _LANCZOS)


def create_text_overlay(
    width: int,
    height: int,
    text: str = "",
    output_path: Optional[str] = None,
    circle_size: Optional[int] = None,
) -> str:
    """Create a transparent PNG with a fitted lower-right arc signature."""
    if output_path is None:
        output_path = _temporary_png_path("text_overlay")

    if circle_size is None:
        circle_size = _even(min(width, height) * CIRCLE_SIZE_RATIO)
    else:
        circle_size = _even(circle_size)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layout = fit_text_to_arc(text, circle_size, frame_size=(width, height))
    if not layout.text:
        image.save(output_path)
        return output_path

    center_x = width / 2.0
    center_y = height / 2.0
    cursor_angle = math.radians(layout.end_angle_deg + layout.span_deg)

    for index, (character, advance) in enumerate(zip(layout.text, layout.advances)):
        half_advance_angle = (advance / 2.0) / layout.path_radius
        character_angle = cursor_angle - half_advance_angle
        angle_deg = math.degrees(character_angle)

        x = center_x + layout.path_radius * math.cos(character_angle)
        y = center_y + layout.path_radius * math.sin(character_angle)
        # Text progresses toward smaller polar angles. The corresponding
        # tangent rises to the right in the lower-right quadrant.
        rotation_deg = 90.0 - angle_deg

        glyph = _render_glyph(
            character,
            layout.font_size,
            layout.font_path,
            rotation_deg,
        )
        if glyph is not None:
            paste_x = int(round(x - glyph.width / 2.0))
            paste_y = int(round(y - glyph.height / 2.0))
            image.alpha_composite(glyph, (paste_x, paste_y))

        # Move from the leading edge through the complete glyph advance.
        cursor_angle -= 2.0 * half_advance_angle
        if index < len(layout.text) - 1:
            cursor_angle -= layout.tracking / layout.path_radius

    image.save(output_path)
    return output_path


def create_circle_mask(size: int, output_path: Optional[str] = None) -> str:
    """Create an antialiased circular alpha mask."""
    if output_path is None:
        output_path = _temporary_png_path("circle_mask")

    size = _even(size)
    scale = _MASK_RENDER_SCALE
    high_size = size * scale
    mask = Image.new("L", (high_size, high_size), 0)
    draw = ImageDraw.Draw(mask)
    inset = scale // 2
    draw.ellipse(
        (inset, inset, high_size - inset - 1, high_size - inset - 1),
        fill=255,
    )
    mask.resize((size, size), _LANCZOS).save(output_path)
    return output_path


def create_soft_square_mask(size: int, output_path: Optional[str] = None) -> str:
    """Create a softly feathered square mask for the local background layer.

    The square is the same size as the clear circle, so only its corners show
    and its border has to reach zero alpha exactly at the frame edge. Insetting
    the opaque core by a full feather puts that edge three sigma out, where the
    Gaussian tail has died: fading over half a feather instead would leave the
    border stepping straight from nothing to a quarter opacity, which reads as
    a hard line around the square.
    """
    if output_path is None:
        output_path = _temporary_png_path("local_mask")

    size = _even(size)
    opacity = max(0.0, min(1.0, LOCAL_BACKGROUND_OPACITY))
    maximum = int(round(255 * opacity))
    feather = max(2, int(round(size * LOCAL_BACKGROUND_SQUARE_FEATHER_RATIO)))

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(1, feather)
    radius = max(2, int(round(size * 0.035)))
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=radius,
        fill=maximum,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, feather / 3.0)))
    mask.save(output_path)
    return output_path


def create_soft_circle_mask(
    size: int,
    circle_size: int,
    output_path: Optional[str] = None,
) -> str:
    """Create a softly feathered round mask for the local background layer.

    A video note is round, so a square backdrop would draw a square silhouette
    around it — exactly the shape Telegram's own white mask leaves behind. The
    circular halo fades into the ambient layer instead.

    Only the ring between the circle and the halo's own edge is ever visible,
    and how wide that ring is depends on the circle size and the frame, so the
    fade is derived from it rather than from a fixed ratio: the gradient is
    centred on the middle of the ring and spans it at three sigma either way.
    That keeps the halo at full strength where it meets the circle and at zero
    alpha on its border no matter how thin the ring gets — a fade measured
    against the halo diameter instead collapses under the circle and vanishes
    as soon as the circle grows.
    """
    if output_path is None:
        output_path = _temporary_png_path("local_mask")

    size = _even(size)
    opacity = max(0.0, min(1.0, LOCAL_BACKGROUND_OPACITY))
    maximum = int(round(255 * opacity))

    circle_radius = min(_even(circle_size), size) / 2.0
    ring = max(1.0, size / 2.0 - circle_radius)
    core_radius = circle_radius + ring / 2.0
    sigma = max(1.0, ring / 6.0)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    inset = size / 2.0 - core_radius
    draw.ellipse((inset, inset, size - inset - 1, size - inset - 1), fill=maximum)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=sigma))
    mask.save(output_path)
    return output_path


def create_local_backdrop_mask(
    size: int,
    circle_size: int,
    source_kind: str,
    output_path: Optional[str] = None,
) -> str:
    """Pick the backdrop silhouette that matches the source geometry."""
    if source_kind == VIDEO_NOTE_KIND:
        return create_soft_circle_mask(size, circle_size, output_path)
    return create_soft_square_mask(size, output_path)


def parse_ffmpeg_progress(line: str, duration: float) -> Optional[float]:
    """Parse FFmpeg log or ``-progress`` output into a percentage."""
    if duration <= 0:
        return None

    time_match = re.search(
        r"(?:out_time|time)=(\d+):(\d+):(\d+(?:\.\d+)?)",
        line,
    )
    if time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        seconds = float(time_match.group(3))
        current_time = hours * 3600 + minutes * 60 + seconds
        return min(100.0, (current_time / duration) * 100)

    microseconds_match = re.search(r"out_time_(?:us|ms)=(\d+)", line)
    if microseconds_match:
        current_time = int(microseconds_match.group(1)) / 1_000_000
        return min(100.0, (current_time / duration) * 100)

    seconds_match = re.search(r"time=(\d+(?:\.\d+)?)", line)
    if seconds_match:
        current_time = float(seconds_match.group(1))
        return min(100.0, (current_time / duration) * 100)

    return None


async def probe_duration(path: str) -> float:
    """Read a media duration with ffprobe; return 0.0 when it is unavailable.

    Video notes always carry a duration in the Telegram payload, but regular
    videos — especially ones sent as documents — may not. Progress reporting
    needs the duration, so recover it from the downloaded file.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]

    process: Optional[asyncio.subprocess.Process] = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=_PROBE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        logger.debug("ffprobe timed out for %s", path)
        return 0.0
    except OSError:
        logger.debug("ffprobe is unavailable", exc_info=True)
        return 0.0

    if process.returncode != 0:
        return 0.0

    try:
        duration = float(stdout.decode("utf-8", errors="ignore").strip())
    except ValueError:
        return 0.0

    return duration if math.isfinite(duration) and duration > 0 else 0.0


def _local_backdrop_size(
    width: int,
    height: int,
    circle_size: int,
    source_kind: str = "video",
) -> int:
    """Side of the backdrop layer sitting directly behind the clear circle.

    A regular video keeps it at the circle diameter. The backdrop is then
    scaled exactly like the circle layer, so its blurred corners continue the
    sharp circle content straight across the edge instead of stepping to a
    different zoom, and the square meets the circle flush at the four tangent
    points.

    A video note draws a round halo instead, which only reads if it extends
    past the circle — hence the ratio.
    """
    if source_kind != VIDEO_NOTE_KIND:
        return circle_size

    maximum = _even(min(width, height))
    requested = _even(circle_size * LOCAL_BACKGROUND_SIZE_RATIO)
    return max(circle_size, min(requested, maximum))


def _ambient_map_size(width: int, height: int) -> Tuple[int, int]:
    """Size of the tiny colour map, keeping the output aspect ratio."""
    map_width = _even(max(16, AMBIENT_MAP_WIDTH), minimum=16)
    map_height = _even(map_width * height / width, minimum=16)
    return map_width, map_height


def _ambient_smoothing_filter() -> str:
    """Build the ``tmix`` pass that smooths the colour map over time.

    ``tmix`` orders its weights oldest to newest, so an exponential ramp makes
    the current frame dominate while older ones decay by ``1 - alpha`` per
    step. That approximates ``A_t = alpha * B_t + (1 - alpha) * A_(t-1)`` over
    a finite window, which is cheap here because the map is only ~96px wide.
    """
    frames = max(1, AMBIENT_SMOOTHING_FRAMES)
    if frames < 2:
        return ""

    decay = max(0.0, min(0.99, 1.0 - AMBIENT_SMOOTHING_ALPHA))
    weights = " ".join(
        f"{decay ** (frames - 1 - index):.5f}" for index in range(frames)
    )
    return f"tmix=frames={frames}:weights='{weights}',"


def _build_filter_complex(
    width: int,
    height: int,
    circle_size: int,
    source_kind: str = "video",
) -> str:
    """Compose the ambient, backdrop, clear-circle and signature layers.

    Video notes arrive with Telegram's white round mask baked in, so their
    background layers are sampled from inside the source circle only. Ordinary
    videos keep using the whole frame.
    """
    backdrop_size = _local_backdrop_size(width, height, circle_size, source_kind)
    map_width, map_height = _ambient_map_size(width, height)
    zoom_width = _even(map_width * max(1.0, ZOOM_SCALE), minimum=16)
    zoom_height = _even(map_height * max(1.0, ZOOM_SCALE), minimum=16)

    if source_kind == VIDEO_NOTE_KIND:
        # The corners hold nothing but Telegram's white mask; take the largest
        # square that fits inside the circle. Video notes are always square, so
        # a relative crop lands exactly on it whatever the source resolution.
        safe_crop = max(0.05, min(1.0, VIDEO_NOTE_SAFE_CROP))
        inner_crop = f"crop=iw*{safe_crop:.4f}:ih*{safe_crop:.4f},"
        # Zoom past the antialiased rim of that baked mask before cutting the
        # visible circle, so no pale outline survives.
        edge_trim = max(0.5, min(1.0, VIDEO_NOTE_EDGE_TRIM))
        circle_source = _even(circle_size / edge_trim)
    else:
        inner_crop = ""
        circle_source = circle_size

    circle_x = (width - circle_size) // 2
    circle_y = (height - circle_size) // 2
    backdrop_x = (width - backdrop_size) // 2
    backdrop_y = (height - backdrop_size) // 2

    return (
        "[0:v]split=3[ambient_src][local_src][circle_src];"
        f"[ambient_src]{inner_crop}scale={zoom_width}:{zoom_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={map_width}:{map_height},"
        f"{_ambient_smoothing_filter()}"
        f"gblur=sigma={max(0.1, AMBIENT_BLUR_SIGMA):.3f}:steps=2,"
        f"eq=saturation={AMBIENT_SATURATION}:"
        f"brightness={BRIGHTNESS_ADJUST}:contrast={CONTRAST_ADJUST},"
        # Bicubic, not lanczos: the map is already a smooth colour field and
        # sharpening kernels only ring on it.
        f"scale={width}:{height}:flags=bicubic,setsar=1,format=yuv420p[ambient];"
        f"[local_src]{inner_crop}scale={backdrop_size}:{backdrop_size}:"
        "force_original_aspect_ratio=increase,"
        f"crop={backdrop_size}:{backdrop_size},"
        f"gblur=sigma={max(0.1, LOCAL_BACKGROUND_BLUR):.3f}:steps=1,"
        f"eq=brightness={LOCAL_BACKGROUND_BRIGHTNESS}:"
        f"contrast={LOCAL_BACKGROUND_CONTRAST},"
        "setsar=1,format=rgba[local_base];"
        "[local_base][3:v]alphamerge[local];"
        f"[circle_src]scale={circle_source}:{circle_source}:"
        "force_original_aspect_ratio=increase,"
        f"crop={circle_size}:{circle_size},setsar=1,format=rgba[circle_base];"
        "[circle_base][2:v]alphamerge[circle];"
        f"[ambient][local]overlay={backdrop_x}:{backdrop_y}:"
        "format=auto:eof_action=repeat[ambient_local];"
        f"[ambient_local][circle]overlay={circle_x}:{circle_y}:"
        "format=auto:eof_action=repeat[video];"
        "[video][1:v]overlay=0:0:format=auto:eof_action=repeat,"
        "format=yuv420p[outv]"
    )


async def process_video_async(
    input_path: str,
    output_path: str,
    target_size: Tuple[int, int],
    overlay_text: str = "",
    progress_callback: Optional[Callable[[int], Awaitable[None]]] = None,
    video_duration: float = 0.0,
    source_kind: str = "video",
) -> str:
    """Render the ambient, backdrop, clear-circle and arc-text layers."""
    started_at = time.time()
    width, height = target_size
    circle_size = _even(min(width, height) * CIRCLE_SIZE_RATIO)

    logger.info(
        "Starting video processing: %s -> %s (%sx%s, kind=%s)",
        input_path,
        output_path,
        width,
        height,
        source_kind,
    )

    generated_files: list[str] = []
    process: Optional[asyncio.subprocess.Process] = None

    try:
        text_overlay = create_text_overlay(
            width,
            height,
            overlay_text,
            circle_size=circle_size,
        )
        generated_files.append(text_overlay)

        circle_mask = create_circle_mask(circle_size)
        generated_files.append(circle_mask)

        backdrop_size = _local_backdrop_size(
            width,
            height,
            circle_size,
            source_kind,
        )
        local_mask = create_local_backdrop_mask(
            backdrop_size,
            circle_size,
            source_kind,
        )
        generated_files.append(local_mask)

        filter_complex = _build_filter_complex(
            width,
            height,
            circle_size,
            source_kind,
        )

        cmd = ["ffmpeg", "-y"]
        if FFMPEG_THREADS > 0:
            cmd.extend(["-threads", str(FFMPEG_THREADS)])

        cmd.extend(
            [
                "-progress",
                "pipe:2",
                "-i",
                input_path,
                "-i",
                text_overlay,
                "-i",
                circle_mask,
                "-i",
                local_mask,
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        last_update_time = 0.0
        last_reported_progress = -1
        stderr_tail: deque[str] = deque(maxlen=40)

        async def read_stderr() -> None:
            nonlocal last_update_time, last_reported_progress
            assert process is not None and process.stderr is not None

            while True:
                raw_line = await process.stderr.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line:
                    stderr_tail.append(line)

                if "[libx264" in line or "encoded" in line:
                    if "cpu capabilities" in line:
                        logger.info("FFmpeg CPU: %s", line.split("cpu capabilities:")[-1].strip())
                    elif "threads=" in line:
                        threads_match = re.search(r"threads=(\d+)", line)
                        lookahead_match = re.search(r"lookahead_threads=(\d+)", line)
                        crf_match = re.search(r"crf=([\d.]+)", line)
                        logger.info(
                            "FFmpeg config: threads=%s (lookahead=%s), CRF=%s",
                            threads_match.group(1) if threads_match else "?",
                            lookahead_match.group(1) if lookahead_match else "?",
                            crf_match.group(1) if crf_match else "?",
                        )

                if progress_callback and video_duration > 0:
                    progress = parse_ffmpeg_progress(line, video_duration)
                    if progress is None:
                        continue

                    progress_int = int(progress)
                    current_time = time.time()
                    if current_time - last_update_time >= PROGRESS_UPDATE_INTERVAL:
                        last_update_time = current_time
                        last_reported_progress = progress_int
                        try:
                            await progress_callback(progress_int)
                        except Exception:
                            logger.debug("Progress callback failed", exc_info=True)

        await asyncio.wait_for(
            asyncio.gather(process.wait(), read_stderr()),
            timeout=PROCESSING_TIMEOUT,
        )

        if process.returncode != 0:
            details = "\n".join(stderr_tail)[-2500:]
            raise RuntimeError(
                f"FFmpeg failed (code {process.returncode}): {details}"
            )

        if progress_callback and last_reported_progress < 100:
            try:
                await progress_callback(100)
            except Exception:
                logger.debug("Final progress callback failed", exc_info=True)

        logger.info("Video processing completed in %.1fs", time.time() - started_at)
        return output_path

    except asyncio.TimeoutError as exc:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise RuntimeError(
            f"Processing timeout after {PROCESSING_TIMEOUT} seconds"
        ) from exc
    except asyncio.CancelledError:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    finally:
        cleanup_temp_files(*generated_files)


def cleanup_temp_files(*paths: str) -> None:
    """Remove temporary files."""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.debug("Failed to remove temporary file %s", path, exc_info=True)


# Keep sync version for backward compatibility (will be removed)
process_video = None  # Mark as removed - use process_video_async
