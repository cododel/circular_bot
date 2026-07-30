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
    AMBIENT_BLUR_SIGMA,
    AMBIENT_MAP_WIDTH,
    AMBIENT_SATURATION,
    AMBIENT_SMOOTHING_ALPHA,
    AMBIENT_SMOOTHING_FRAMES,
    ASPECT_RATIOS,
    CIRCLE_SIZE_RATIO,
    LOCAL_BACKGROUND_OPACITY,
    LOCAL_BACKGROUND_SIZE_RATIO,
    TEXT_ARC_MAX_SPAN_DEG,
    TEXT_FONT_SIZE_RATIO,
    TEXT_FRAME_MARGIN_RATIO,
    TEXT_MIN_FONT_SIZE_RATIO,
    VIDEO_NOTE_EDGE_TRIM,
    VIDEO_NOTE_SAFE_CROP,
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


def test_square_backdrop_fades_to_nothing_at_its_own_border(tmp_path: Path) -> None:
    """A border that starts at partial alpha draws a hard line around the square."""
    size = 590
    mask_path = tmp_path / "square.png"
    video_processor.create_soft_square_mask(size, str(mask_path))

    with Image.open(mask_path) as mask:
        border = [mask.getpixel((x, 0)) for x in range(0, size, 20)]
        border += [mask.getpixel((0, y)) for y in range(0, size, 20)]
        assert max(border) == 0

        # ...and it is back to full opacity by the time it reaches the circle,
        # so the backdrop still meets the circle content flush at the corners.
        circle_edge = int(round(size * (2**0.5 - 1) / 2 / 2**0.5))
        opaque = round(255 * LOCAL_BACKGROUND_OPACITY)
        assert mask.getpixel((circle_edge, circle_edge)) >= opaque * 0.9

        # The fade in between is gradual rather than a couple of steps.
        profile = [mask.getpixel((d, d)) for d in range(0, circle_edge)]
        assert max(b - a for a, b in zip(profile, profile[1:])) < opaque * 0.1


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


def test_ambient_is_built_from_a_tiny_colour_map() -> None:
    """A wide blur is affordable only on a downscaled map."""
    width, height = 720, 1280
    graph = video_processor._build_filter_complex(width, height, 590)
    map_width, map_height = video_processor._ambient_map_size(width, height)

    assert map_width == video_processor._even(AMBIENT_MAP_WIDTH, minimum=16)
    # The map keeps the canvas aspect ratio, so the colours stay where they are.
    assert map_height == pytest.approx(map_width * height / width, abs=2)
    assert f"crop={map_width}:{map_height}," in graph
    assert f"gblur=sigma={AMBIENT_BLUR_SIGMA:.3f}:steps=2" in graph
    assert f"saturation={AMBIENT_SATURATION}" in graph
    # Sharpening kernels ring on a smooth colour field.
    assert f"scale={width}:{height}:flags=bicubic" in graph


def test_ambient_smoothing_weights_favour_the_current_frame() -> None:
    """tmix orders weights oldest to newest, so the ramp must rise."""
    smoothing = video_processor._ambient_smoothing_filter()

    assert smoothing.startswith(f"tmix=frames={AMBIENT_SMOOTHING_FRAMES}:weights='")
    weights = [float(value) for value in smoothing.split("'")[1].split()]

    assert len(weights) == AMBIENT_SMOOTHING_FRAMES
    assert weights[-1] == pytest.approx(1.0)
    assert all(
        earlier < later for earlier, later in zip(weights, weights[1:])
    )
    assert weights[-2] == pytest.approx(1.0 - AMBIENT_SMOOTHING_ALPHA, abs=1e-4)


def test_ambient_smoothing_is_skipped_for_a_single_frame_window(monkeypatch) -> None:
    monkeypatch.setattr(video_processor, "AMBIENT_SMOOTHING_FRAMES", 1)

    assert video_processor._ambient_smoothing_filter() == ""
    assert "tmix=" not in video_processor._build_filter_complex(720, 1280, 590)


def test_video_note_layers_sample_only_inside_the_source_circle() -> None:
    """Telegram bakes a white round mask in, so the corners are unusable."""
    graph = video_processor._build_filter_complex(
        720,
        1280,
        590,
        video_processor.VIDEO_NOTE_KIND,
    )

    inner_crop = f"crop=iw*{VIDEO_NOTE_SAFE_CROP:.4f}:ih*{VIDEO_NOTE_SAFE_CROP:.4f},"
    # The ambient and backdrop layers both take the inscribed square; the
    # visible circle keeps the full frame and is only trimmed at the rim.
    assert graph.count(inner_crop) == 2
    assert f"[ambient_src]{inner_crop}" in graph
    assert f"[local_src]{inner_crop}" in graph
    # Any larger crop would reach past the circle into the white corners.
    assert VIDEO_NOTE_SAFE_CROP <= 1 / math.sqrt(2)


def test_video_note_circle_is_zoomed_past_the_baked_mask_rim() -> None:
    circle_size = 590
    graph = video_processor._build_filter_complex(
        720,
        1280,
        circle_size,
        video_processor.VIDEO_NOTE_KIND,
    )
    zoomed = video_processor._even(circle_size / VIDEO_NOTE_EDGE_TRIM)

    assert zoomed > circle_size
    assert f"[circle_src]scale={zoomed}:{zoomed}:" in graph
    assert f"crop={circle_size}:{circle_size},setsar=1,format=rgba[circle_base]" in graph


def test_regular_video_keeps_using_the_whole_frame() -> None:
    graph = video_processor._build_filter_complex(720, 1280, 590)

    assert "crop=iw*" not in graph
    assert "[circle_src]scale=590:590:" in graph


def test_regular_video_backdrop_is_scaled_exactly_like_the_circle() -> None:
    """A backdrop at another zoom steps visibly at the circle edge."""
    width, height, circle_size = 720, 1280, 590

    assert video_processor._local_backdrop_size(width, height, circle_size) == circle_size

    graph = video_processor._build_filter_complex(width, height, circle_size)

    # Same scale and same crop, so the blurred corners continue the sharp
    # circle content across the edge instead of jumping to a different zoom.
    assert f"[local_src]scale={circle_size}:{circle_size}:" in graph
    assert f"[circle_src]scale={circle_size}:{circle_size}:" in graph
    assert graph.count(f"crop={circle_size}:{circle_size},") == 2

    # ...and both land on the same spot, so the square is flush with the circle.
    x = (width - circle_size) // 2
    y = (height - circle_size) // 2
    assert graph.count(f"overlay={x}:{y}:") == 2


def test_video_note_halo_still_extends_past_the_circle() -> None:
    """The round halo is only visible where it reaches beyond the circle."""
    circle_size = 590
    size = video_processor._local_backdrop_size(
        720,
        1280,
        circle_size,
        video_processor.VIDEO_NOTE_KIND,
    )

    assert size > circle_size
    assert size == pytest.approx(circle_size * LOCAL_BACKGROUND_SIZE_RATIO, abs=2)


def test_video_note_backdrop_mask_is_round(tmp_path: Path) -> None:
    """A square halo would redraw the silhouette we are removing."""
    size, circle_size = 340, 300
    round_mask = tmp_path / "round.png"
    square_mask = tmp_path / "square.png"

    video_processor.create_local_backdrop_mask(
        size,
        circle_size,
        video_processor.VIDEO_NOTE_KIND,
        str(round_mask),
    )
    video_processor.create_local_backdrop_mask(
        size,
        circle_size,
        "video",
        str(square_mask),
    )

    expected_center = round(255 * LOCAL_BACKGROUND_OPACITY)
    with Image.open(round_mask) as mask:
        assert abs(mask.getpixel((size // 2, size // 2)) - expected_center) <= 1
        # Mid-edge stays lit while the corners of the same square fall away.
        assert mask.getpixel((size // 2, 6)) > 0
        assert mask.getpixel((12, 12)) == 0

    with Image.open(square_mask) as mask:
        # The square keeps its corners — that is the only part of it on show,
        # and it is exactly where the round halo has nothing.
        assert mask.getpixel((size // 4, size // 4)) > 0


@pytest.mark.parametrize("ring", [8, 26, 60])
def test_round_halo_survives_any_ring_width(tmp_path: Path, ring: int) -> None:
    """The ring narrows as the circle grows; the glow has to hold up anyway."""
    size = 720
    circle_size = size - 2 * ring
    mask_path = tmp_path / f"halo_{ring}.png"
    video_processor.create_soft_circle_mask(size, circle_size, str(mask_path))

    opaque = round(255 * LOCAL_BACKGROUND_OPACITY)
    centre = size // 2

    with Image.open(mask_path) as mask:
        # Full strength where it meets the circle, so the glow is not a faint
        # smear left over from a fade measured against the halo diameter.
        assert mask.getpixel((centre - circle_size // 2 + 1, centre)) >= opaque * 0.95
        # ...and gone by its own border, so the halo draws no hard outline.
        assert mask.getpixel((0, centre)) == 0
        assert mask.getpixel((centre, 0)) == 0


@pytest.mark.parametrize(
    ("source_size", "source_kind", "source_label"),
    [
        ("256x256", "video_note", "square video note"),
        ("256x256", "video", "square video"),
        ("320x180", "video", "landscape video"),
        ("180x320", "video", "portrait video"),
    ],
)
def test_ffmpeg_integration_and_generated_file_cleanup(
    tmp_path: Path,
    monkeypatch,
    source_size: str,
    source_kind: str,
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
            source_kind=source_kind,
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
