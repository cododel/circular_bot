"""Video processing with FFmpeg (async version)."""
import os
import asyncio
import re
import math
from typing import Tuple, Callable, Optional
from PIL import Image, ImageDraw, ImageFont
from bot.config import TEMP_DIR


def create_text_overlay(
    width: int,
    height: int,
    text: str = "",
    output_path: str = None,
    circle_size: int = None
) -> str:
    """Create PNG with text overlay at bottom-right of the circle."""
    if output_path is None:
        output_path = os.path.join(TEMP_DIR, f"overlay_{width}x{height}.png")
    
    # Create transparent image
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Try to use a nice font, fallback to default
    try:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Windows/Fonts/arial.ttf",
        ]
        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, int(height * 0.035))
                break
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    
    # Circle position
    if circle_size is None:
        circle_size = min(width, height) * 0.82
    
    circle_right = (width + circle_size) // 2
    circle_bottom = (height + circle_size) // 2
    
    # Text position: just outside circle, bottom-right
    padding = int(height * 0.02)
    text_x = circle_right + padding
    text_y = circle_bottom - padding
    
    # Draw text with shadow
    draw.text((text_x + 2, text_y + 2), text, font=font, fill=(0, 0, 0, 180))
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 230))
    
    img.save(output_path)
    return output_path


def create_circle_mask(size: int, output_path: str = None) -> str:
    """Create PNG mask: white circle on black background."""
    if output_path is None:
        output_path = os.path.join(TEMP_DIR, f"circle_mask_{size}.png")
    
    # Create black background
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    
    # Draw white circle - меньше на 2% от размера
    margin = int(size * 0.02)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=255
    )
    
    img.save(output_path)
    return output_path


def parse_ffmpeg_progress(line: str, duration: float) -> Optional[float]:
    """Parse FFmpeg progress line and return percentage (0-100)."""
    # Look for time=HH:MM:SS.xx or time=SS.xx
    time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
    if time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        seconds = float(time_match.group(3))
        current_time = hours * 3600 + minutes * 60 + seconds
        if duration > 0:
            return min(100.0, (current_time / duration) * 100)
    
    # Alternative format: time=123.45
    alt_match = re.search(r'time=(\d+\.\d+)', line)
    if alt_match:
        current_time = float(alt_match.group(1))
        if duration > 0:
            return min(100.0, (current_time / duration) * 100)
    
    return None


async def process_video_async(
    input_path: str,
    output_path: str,
    target_size: Tuple[int, int],
    overlay_text: str = "",
    progress_callback: Optional[Callable[[int], None]] = None,
    video_duration: float = 0.0,
) -> str:
    """
    Process video note to target aspect ratio with black background and overlay.
    Async version with progress tracking.
    """
    width, height = target_size
    
    # Create overlays
    circle_size = min(width, height) * 0.82
    circle_size = int(circle_size)
    circle_size = (circle_size // 2) * 2
    
    text_overlay = create_text_overlay(width, height, overlay_text, circle_size=circle_size)
    
    circle_mask = create_circle_mask(circle_size)
    
    # Build FFmpeg command with progress output
    # Zoom reduced from 1.15 to 1.08
    filter_complex = (
        f"[0:v]scale={int(width*1.08)}:{int(height*1.08)}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"boxblur=40:40,"
        f"eq=brightness=-0.15:contrast=1.1,"
        f"format=yuv420p[bg];"
        f"[0:v]scale={circle_size}:{circle_size}[fg];"
        f"[fg][2:v]alphamerge,format=rgba[circle];"
        f"[bg][circle]overlay={(width-circle_size)//2}:{(height-circle_size)//2}:format=auto[video];"
        f"[video][1:v]overlay=0:0:format=auto"
    )
    
    cmd = [
        "ffmpeg",
        "-y",
        "-progress", "pipe:2",  # Output progress to stderr
        "-i", input_path,
        "-i", text_overlay,
        "-i", circle_mask,
        "-filter_complex", filter_complex,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]
    
    # Start FFmpeg process
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    # Track progress
    last_reported_progress = -1
    
    # Read stderr for progress
    async def read_stderr():
        nonlocal last_reported_progress
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            line_str = line.decode('utf-8', errors='ignore').strip()
            
            # Parse progress
            if progress_callback and video_duration > 0:
                progress = parse_ffmpeg_progress(line_str, video_duration)
                if progress is not None:
                    progress_int = int(progress)
                    # Report only on 10% increments to avoid spam
                    if progress_int >= last_reported_progress + 10:
                        last_reported_progress = progress_int
                        try:
                            await progress_callback(progress_int)
                        except Exception:
                            pass  # Ignore callback errors
    
    # Wait for process to complete while reading progress
    try:
        await asyncio.wait_for(
            asyncio.gather(
                process.wait(),
                read_stderr(),
            ),
            timeout=300  # 5 minutes timeout
        )
        
        if process.returncode != 0:
            # Try to get error from stderr
            stderr_data = await process.stderr.read()
            error_msg = stderr_data.decode('utf-8', errors='ignore')[-500:]  # Last 500 chars
            raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {error_msg}")
        
        # Final progress report
        if progress_callback and last_reported_progress < 100:
            try:
                await progress_callback(100)
            except Exception:
                pass
        
        return output_path
        
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("Processing timeout (5 minutes)")


def cleanup_temp_files(*paths: str):
    """Remove temporary files."""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# Keep sync version for backward compatibility (will be removed)
process_video = None  # Mark as removed - use process_video_async
