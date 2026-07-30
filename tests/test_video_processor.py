"""Tests for the video composition and curved signature renderer."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from bot import video_processor
from bot.config import (
    ASPECT_RATIOS,
    CIRCLE_SIZE_RATIO,
    LOCAL_BACKGROUND_OPACITY,
    TEXT_ARC_MAX_SPAN_DEG,
    TEXT_FONT_SIZE_RATIO,
    TEXT_FRAME_MARGIN_RATIO,
    TEXT_MIN_FONT_SIZE_RATIO,
)


def test_short_signature_uses_max_font_and_fits_arc() -> None:
    circle_size = 590

    layout = video_processor.fit_text_to_arc("@Cododel", circle_size)

    assert layout.text == "@Cododel"
    assert layout.font_size == round(circle_size * TEXT_FONT_SIZE_RATIO)
    assert 0 < layout.span_deg <= TEXT_ARC_MAX_SPAN_DEG
    assert layout.tracking > 0
    assert len(layout.advances) == len(layout.text)


def test_signature_whitespace_is_normalized_to_one_line() -> None:
    layout = video_processor.fit_text_to_arc("  @code\n\todel  ", 590)

    assert layout.text == "@code odel"


def test_long_ui_signature_scales_without_truncation() -> None:
    circle_size = 590
    text = "This is a custom signature up to fifty chars total"

    layout = video_processor.fit_text_to_arc(text, circle_size)

    assert layout.text == text
    assert layout.font_size >= round(circle_size * TEXT_MIN_FONT_SIZE_RATIO)
    assert layout.font_size < round(circle_size * TEXT_FONT_SIZE_RATIO)
    assert layout.span_deg <= TEXT_ARC_MAX_SPAN_DEG + 1e-6


@pytest.mark.parametrize("ratio_name", sorted(ASPECT_RATIOS))
def test_signature_keeps_frame_margin_in_every_aspect_ratio(
    tmp_path: Path,
    monkeypatch,
    ratio_name: str,
) -> None:
    monkeypatch.setattr(video_processor, "TEMP_DIR", str(tmp_path))
    width, height = ASPECT_RATIOS[ratio_name]
    circle_size = video_processor._even(min(width, height) * CIRCLE_SIZE_RATIO)
    margin = min(width, height) * TEXT_FRAME_MARGIN_RATIO

    layout = video_processor.fit_text_to_arc("@Cododel", circle_size, frame_size=(width, height))
    overlay = Path(
        video_processor.create_text_overlay(width, height, "@Cododel", circle_size=circle_size)
    )

    assert layout.font_size <= round(circle_size * TEXT_FONT_SIZE_RATIO)
    assert layout.font_size >= round(circle_size * TEXT_MIN_FONT_SIZE_RATIO)

    with Image.open(overlay) as image:
        bbox = image.getchannel("A").getbbox()

    assert bbox is not None
    assert bbox[0] >= margin and bbox[1] >= margin
    assert bbox[2] <= width - margin and bbox[3] <= height - margin


def test_tight_frame_shrinks_signature_below_the_upper_font_size() -> None:
    # 16:9 leaves the least room under the circle, so the ceiling cannot be
    # reached there while 9:16 renders the same circle at full size.
    width, height = ASPECT_RATIOS["16:9"]
    circle_size = video_processor._even(min(width, height) * CIRCLE_SIZE_RATIO)

    unbounded = video_processor.fit_text_to_arc("@Cododel", circle_size)
    bounded = video_processor.fit_text_to_arc("@Cododel", circle_size, frame_size=(width, height))

    assert unbounded.font_size == round(circle_size * TEXT_FONT_SIZE_RATIO)
    assert bounded.font_size < unbounded.font_size


def test_text_overlay_is_unique_and_outside_clear_circle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(video_processor, "TEMP_DIR", str(tmp_path))
    width, height, circle_size = 720, 1280, 590

    first = Path(video_processor.create_text_overlay(width, height, "@Cododel", circle_size=circle_size))
    second = Path(video_processor.create_text_overlay(width, height, "@Cododel", circle_size=circle_size))

    assert first != second
    assert first.exists() and second.exists()

    with Image.open(first) as overlay:
        assert overlay.size == (width, height)
        alpha = overlay.getchannel("A")
        bbox = alpha.getbbox()
        assert bbox is not None
        assert bbox[0] > 0 and bbox[1] > 0
        assert bbox[2] < width and bbox[3] < height

        center_x, center_y = width / 2, height / 2
        visible_radius = circle_size / 2
        minimum_opaque_distance = math.inf
        pixels = alpha.load()
        for y in range(bbox[1], bbox[3]):
            for x in range(bbox[0], bbox[2]):
                if pixels[x, y] >= 64:
                    minimum_opaque_distance = min(
                        minimum_opaque_distance,
                        math.hypot(x - center_x, y - center_y),
                    )

        assert minimum_opaque_distance > visible_radius


def test_circle_and_local_masks_are_antialiased(tmp_path: Path) -> None:
    circle_path = tmp_path / "circle.png"
    local_path = tmp_path / "local.png"

    video_processor.create_circle_mask(300, str(circle_path))
    video_processor.create_soft_square_mask(340, str(local_path))

    with Image.open(circle_path) as circle:
        histogram = circle.histogram()
        assert circle.getpixel((150, 150)) == 255
        assert circle.getpixel((0, 0)) == 0
        assert any(histogram[1:255])

    with Image.open(local_path) as local:
        expected_center = round(255 * LOCAL_BACKGROUND_OPACITY)
        histogram = local.histogram()
        assert abs(local.getpixel((170, 170)) - expected_center) <= 1
        assert local.getpixel((0, 0)) < expected_center // 4
        assert any(histogram[1:expected_center])


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("out_time=00:00:05.000000", 50.0),
        ("time=00:00:02.500", 25.0),
        ("out_time_us=7500000", 75.0),
    ],
)
def test_parse_ffmpeg_progress(line: str, expected: float) -> None:
    assert video_processor.parse_ffmpeg_progress(line, 10.0) == pytest.approx(expected)


def test_filter_graph_contains_three_visual_layers() -> None:
    graph = video_processor._build_filter_complex(720, 1280, 590)

    assert "split=3" in graph
    assert "[ambient]" in graph
    assert "[local]" in graph
    assert "[circle]" in graph
    assert graph.count("gblur=") == 2
    assert "boxblur=" not in graph
    assert graph.endswith("format=yuv420p[outv]")


def test_every_layer_center_crops_non_square_input() -> None:
    """Regular videos are not square, so each layer must scale-up then crop."""
    graph = video_processor._build_filter_complex(720, 1280, 590)

    assert graph.count("force_original_aspect_ratio=increase") == 3
    assert graph.count("crop=") == 3


@pytest.mark.parametrize(
    ("source_size", "source_label"),
    [
        ("256x256", "square video note"),
        ("320x180", "landscape video"),
        ("180x320", "portrait video"),
    ],
)
def test_ffmpeg_integration_and_generated_file_cleanup(
    tmp_path: Path,
    monkeypatch,
    source_size: str,
    source_label: str,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg tools are not installed")

    monkeypatch.setattr(video_processor, "TEMP_DIR", str(tmp_path))
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"

    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={source_size}:rate=8:duration=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    asyncio.run(
        video_processor.process_video_async(
            str(source),
            str(output),
            (320, 568),
            overlay_text="@Cododel",
            video_duration=0.5,
        )
    )

    assert output.exists() and output.stat().st_size > 0
    metadata = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(metadata.stdout)["streams"][0]
    assert stream == {"width": 320, "height": 568}

    assert not list(tmp_path.glob("text_overlay_*.png"))
    assert not list(tmp_path.glob("circle_mask_*.png"))
    assert not list(tmp_path.glob("local_mask_*.png"))


def test_probe_duration_reads_a_real_file(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg tools are not installed")

    source = tmp_path / "probe.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=8:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    assert asyncio.run(video_processor.probe_duration(str(source))) == pytest.approx(2.0, abs=0.2)
