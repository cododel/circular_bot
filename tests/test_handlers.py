"""Tests for media intake: video notes, regular videos and video documents."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import handlers, video_processor


def make_message(**attachments) -> SimpleNamespace:
    """Build a minimal stand-in for an aiogram Message."""
    payload = {"video_note": None, "video": None, "document": None}
    payload.update(attachments)
    return SimpleNamespace(**payload)


def test_video_note_is_recognized() -> None:
    message = make_message(
        video_note=SimpleNamespace(file_id="note-1", duration=12, file_size=900_000)
    )

    source = handlers.extract_video_source(message)

    assert source == handlers.VideoSource(
        file_id="note-1",
        duration=12.0,
        file_size=900_000,
        kind="video_note",
    )


def test_regular_video_is_recognized() -> None:
    message = make_message(
        video=SimpleNamespace(file_id="video-1", duration=42, file_size=5_000_000)
    )

    source = handlers.extract_video_source(message)

    assert source is not None
    assert source.kind == "video"
    assert source.file_id == "video-1"
    assert source.duration == 42.0


def test_video_document_is_recognized_without_duration() -> None:
    message = make_message(
        document=SimpleNamespace(
            file_id="doc-1",
            mime_type="video/mp4",
            file_size=3_000_000,
        )
    )

    source = handlers.extract_video_source(message)

    assert source is not None
    assert source.kind == "video"
    assert source.duration == 0.0


@pytest.mark.parametrize(
    "message",
    [
        make_message(),
        make_message(
            document=SimpleNamespace(file_id="doc-2", mime_type="application/pdf", file_size=10)
        ),
        make_message(document=SimpleNamespace(file_id="doc-3", mime_type=None, file_size=10)),
    ],
)
def test_messages_without_video_are_rejected(message: SimpleNamespace) -> None:
    assert handlers.extract_video_source(message) is None


def test_every_source_kind_has_a_confirmation_phrase() -> None:
    kinds = {
        handlers.extract_video_source(message).kind
        for message in (
            make_message(video_note=SimpleNamespace(file_id="a", duration=1, file_size=1)),
            make_message(video=SimpleNamespace(file_id="b", duration=1, file_size=1)),
        )
    }

    assert kinds <= set(handlers.RECEIVED_PHRASES)


def test_size_limit_only_rejects_known_oversized_files(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "MAX_VIDEO_SIZE_BYTES", 20 * 1024 * 1024)

    assert handlers.exceeds_size_limit(21 * 1024 * 1024) is True
    assert handlers.exceeds_size_limit(19 * 1024 * 1024) is False
    assert handlers.exceeds_size_limit(None) is False


def test_size_limit_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "MAX_VIDEO_SIZE_BYTES", 0)

    assert handlers.exceeds_size_limit(2 * 1024 * 1024 * 1024) is False


def test_probe_duration_returns_zero_for_unreadable_input(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"

    assert asyncio.run(video_processor.probe_duration(str(missing))) == 0.0
