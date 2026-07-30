"""Video processing with layered ambient background and curved signature."""
from __future__ import annotations

import asyncio
from collections import deque
import logging
import math
import os
import re
import tempfile
import time
from typing import Awaitable, Callable, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.config import (
    AMBIENT_DOWNSCALE, BACKGROUND_BLUR, BRIGHTNESS_ADJUST,
    CIRCLE_SIZE_RATIO, CONTRAST_ADJUST, FFMPEG_THREADS,
    LOCAL_BACKGROUND_BLUR, LOCAL_BACKGROUND_BRIGHTNESS,
    LOCAL_BACKGROUND_CONTRAST, LOCAL_BACKGROUND_FEATHER_RATIO,
    LOCAL_BACKGROUND_OPACITY, LOCAL_BACKGROUND_SIZE_RATIO,
    PROCESSING_TIMEOUT, PROGRESS_UPDATE_INTERVAL, TEMP_DIR,
    TEXT_ARC_END_DEG, TEXT_ARC_MAX_SPAN_DEG, TEXT_FONT_SIZE_RATIO,
    TEXT_MIN_FONT_SIZE_RATIO, TEXT_MIN_TRACKING_RATIO,
    TEXT_PADDING_RATIO, TEXT_TRACKING_RATIO, ZOOM_SCALE,
)

logger = logging.getLogger(__name__)
_RESAMPLING = getattr(Image, "Resampling", Image)
_LANCZOS = _RESAMPLING.LANCZOS
_BICUBIC = _RESAMPLING.BICUBIC
_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Windows/Fonts/arial.ttf",
)


def _even(value: float, minimum: int = 2) -> int:
    result = max(minimum, int(value))
    return result if result % 2 == 0 else result - 1


def _temp_png(prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"{prefix}_", suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    return path


def _font_path() -> Optional[str]:
    return next((path for path in _FONT_PATHS if os.path.exists(path)), None)


def _font(size: int, path: Optional[str] = None) -> ImageFont.ImageFont:
    path = path or _font_path()
    if path:
        return ImageFont.truetype(path, max(1, int(size)))
    try:
        return ImageFont.load_default(size=max(1, int(size)))
    except TypeError:
        return ImageFont.load_default()


def _advance(font: ImageFont.ImageFont, char: str) -> float:
    try:
        return float(font.getlength(char))
    except AttributeError:
        box = font.getbbox(char)
        return float(box[2] - box[0])


def _fit_arc_text(text: str, circle_size: int) -> tuple[str, int, float, list[float], float]:
    text = re.sub(r"\s+", " ", text or "").strip()
    maximum = max(8, round(circle_size * TEXT_FONT_SIZE_RATIO))
    minimum = min(maximum, max(8, round(circle_size * TEXT_MIN_FONT_SIZE_RATIO)))
    path = _font_path()
    max_span = math.radians(TEXT_ARC_MAX_SPAN_DEG)

    if not text:
        return "", maximum, 0.0, [], circle_size / 2

    for size in range(maximum, minimum - 1, -1):
        font = _font(size, path)
        advances = [_advance(font, char) for char in text]
        radius = circle_size / 2 + circle_size * TEXT_PADDING_RATIO + size * 0.55
        capacity = radius * max_span
        gaps = max(0, len(text) - 1)
        preferred = size * TEXT_TRACKING_RATIO
        min_tracking = size * TEXT_MIN_TRACKING_RATIO
        if gaps:
            available = (capacity - sum(advances)) / gaps
            if available < min_tracking:
                continue
            tracking = min(preferred, available)
        else:
            tracking = 0.0
        return text, size, tracking, advances, radius

    candidate = text
    while len(candidate) > 1:
        candidate = candidate[:-1].rstrip()
        rendered = candidate + "…"
        font = _font(minimum, path)
        advances = [_advance(font, char) for char in rendered]
        tracking = minimum * TEXT_MIN_TRACKING_RATIO
        radius = circle_size / 2 + circle_size * TEXT_PADDING_RATIO + minimum * 0.55
        length = sum(advances) + max(0, len(advances) - 1) * tracking
        if length / radius <= max_span:
            return rendered, minimum, tracking, advances, radius
    return "…", minimum, 0.0, [_advance(_font(minimum, path), "…")], circle_size / 2


def _render_glyph(char: str, size: int, rotation: float) -> Optional[Image.Image]:
    if char.isspace():
        return None
    scale = 3
    font = _font(size * scale)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    stroke = max(1, round(size * scale * 0.035))
    box = probe.textbbox((0, 0), char, font=font, stroke_width=stroke)
    pad = 6 * scale
    image = Image.new("RGBA", (box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text(
        (pad - box[0], pad - box[1]), char, font=font,
        fill=(255, 255, 255, 232), stroke_width=stroke,
        stroke_fill=(0, 0, 0, 65),
    )
    image = image.rotate(rotation, expand=True, resample=_BICUBIC)
    return image.resize((max(1, image.width // scale), max(1, image.height // scale)), _LANCZOS)


def create_text_overlay(width: int, height: int, text: str = "", output_path: Optional[str] = None, circle_size: Optional[int] = None) -> str:
    output_path = output_path or _temp_png("text_overlay")
    circle_size = _even(circle_size or min(width, height) * CIRCLE_SIZE_RATIO)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text, size, tracking, advances, radius = _fit_arc_text(text, circle_size)
    if not text:
        canvas.save(output_path)
        return output_path

    total = sum(advances) + max(0, len(advances) - 1) * tracking
    angle = math.radians(TEXT_ARC_END_DEG) + total / radius
    cx, cy = width / 2, height / 2
    for index, (char, advance) in enumerate(zip(text, advances)):
        angle -= (advance / 2) / radius
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        glyph = _render_glyph(char, size, 90 - math.degrees(angle))
        if glyph:
            canvas.alpha_composite(glyph, (round(x - glyph.width / 2), round(y - glyph.height / 2)))
        angle -= (advance / 2) / radius
        if index < len(text) - 1:
            angle -= tracking / radius
    canvas.save(output_path)
    return output_path


def create_circle_mask(size: int, output_path: Optional[str] = None) -> str:
    output_path = output_path or _temp_png("circle_mask")
    scale = 4
    large = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(large).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    large.resize((size, size), _LANCZOS).save(output_path)
    return output_path


def create_soft_square_mask(size: int, output_path: Optional[str] = None) -> str:
    output_path = output_path or _temp_png("square_mask")
    maximum = max(0, min(255, round(255 * LOCAL_BACKGROUND_OPACITY)))
    feather = max(2, round(size * LOCAL_BACKGROUND_FEATHER_RATIO))
    mask = Image.new("L", (size, size), 0)
    inset = max(1, feather // 2)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=max(2, round(size * 0.035)), fill=maximum,
    )
    mask.filter(ImageFilter.GaussianBlur(max(1, feather / 2))).save(output_path)
    return output_path


def parse_ffmpeg_progress(line: str, duration: float) -> Optional[float]:
    if duration <= 0:
        return None
    match = re.search(r"(?:out_time|time)=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if match:
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        return min(100.0, seconds / duration * 100)
    match = re.search(r"out_time_(?:us|ms)=(\d+)", line)
    if match:
        return min(100.0, int(match.group(1)) / 1_000_000 / duration * 100)
    return None


def _local_size(width: int, height: int, circle: int) -> int:
    return max(circle, min(_even(circle * LOCAL_BACKGROUND_SIZE_RATIO), _even(min(width, height))))


def _filter(width: int, height: int, circle: int) -> str:
    square = _local_size(width, height, circle)
    downscale = max(0.1, min(1.0, AMBIENT_DOWNSCALE))
    aw, ah = _even(width * downscale), _even(height * downscale)
    zw, zh = _even(aw * max(1.0, ZOOM_SCALE)), _even(ah * max(1.0, ZOOM_SCALE))
    sigma = max(0.1, BACKGROUND_BLUR * downscale)
    cx, cy = (width - circle) // 2, (height - circle) // 2
    sx, sy = (width - square) // 2, (height - square) // 2
    return (
        "[0:v]split=3[a][l][c];"
        f"[a]scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={aw}:{ah},"
        f"gblur=sigma={sigma:.3f}:steps=2,eq=brightness={BRIGHTNESS_ADJUST}:contrast={CONTRAST_ADJUST},"
        f"scale={width}:{height}:flags=lanczos,setsar=1,format=yuv420p[ambient];"
        f"[l]scale={square}:{square}:force_original_aspect_ratio=increase,crop={square}:{square},"
        f"gblur=sigma={max(0.1, LOCAL_BACKGROUND_BLUR):.3f}:steps=1,"
        f"eq=brightness={LOCAL_BACKGROUND_BRIGHTNESS}:contrast={LOCAL_BACKGROUND_CONTRAST},setsar=1,format=rgba[lb];"
        "[lb][3:v]alphamerge[local];"
        f"[c]scale={circle}:{circle}:force_original_aspect_ratio=increase,crop={circle}:{circle},setsar=1,format=rgba[cb];"
        "[cb][2:v]alphamerge[clear];"
        f"[ambient][local]overlay={sx}:{sy}:format=auto:eof_action=repeat[x];"
        f"[x][clear]overlay={cx}:{cy}:format=auto:eof_action=repeat[y];"
        "[y][1:v]overlay=0:0:format=auto:eof_action=repeat,format=yuv420p[outv]"
    )


async def process_video_async(
    input_path: str,
    output_path: str,
    target_size: Tuple[int, int],
    overlay_text: str = "",
    progress_callback: Optional[Callable[[int], Awaitable[None]]] = None,
    video_duration: float = 0.0,
) -> str:
    started = time.time()
    width, height = target_size
    circle = _even(min(width, height) * CIRCLE_SIZE_RATIO)
    generated: list[str] = []
    process: Optional[asyncio.subprocess.Process] = None
    try:
        text = create_text_overlay(width, height, overlay_text, circle_size=circle)
        mask = create_circle_mask(circle)
        square_mask = create_soft_square_mask(_local_size(width, height, circle))
        generated.extend((text, mask, square_mask))
        cmd = ["ffmpeg", "-y"]
        if FFMPEG_THREADS > 0:
            cmd += ["-threads", str(FFMPEG_THREADS)]
        cmd += [
            "-progress", "pipe:2", "-i", input_path, "-i", text,
            "-i", mask, "-i", square_mask, "-filter_complex", _filter(width, height, circle),
            "-map", "[outv]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
            "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", output_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        last_update = 0.0
        last_progress = -1
        errors: deque[str] = deque(maxlen=40)

        async def read_stderr() -> None:
            nonlocal last_update, last_progress
            assert process and process.stderr
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").strip()
                if line:
                    errors.append(line)
                if progress_callback:
                    value = parse_ffmpeg_progress(line, video_duration)
                    if value is not None and time.time() - last_update >= PROGRESS_UPDATE_INTERVAL:
                        last_update = time.time()
                        last_progress = int(value)
                        try:
                            await progress_callback(last_progress)
                        except Exception:
                            logger.debug("Progress callback failed", exc_info=True)

        await asyncio.wait_for(asyncio.gather(process.wait(), read_stderr()), PROCESSING_TIMEOUT)
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {' '.join(errors)[-2500:]}")
        if progress_callback and last_progress < 100:
            await progress_callback(100)
        logger.info("Video processing completed in %.1fs", time.time() - started)
        return output_path
    except asyncio.TimeoutError as exc:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise RuntimeError(f"Processing timeout after {PROCESSING_TIMEOUT} seconds") from exc
    finally:
        cleanup_temp_files(*generated)


def cleanup_temp_files(*paths: str) -> None:
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.debug("Failed to remove temporary file %s", path, exc_info=True)


process_video = None
