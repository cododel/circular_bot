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


class FakeState:
    """Minimal stand-in for aiogram's FSMContext."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.state = None

    async def update_data(self, **values) -> dict:
        self.data.update(values)
        return self.data

    async def get_data(self) -> dict:
        return self.data

    async def set_state(self, state) -> None:
        self.state = state


class FakeMessage(SimpleNamespace):
    """Message stand-in that records what the bot answered."""

    def __init__(self, **attachments) -> None:
        payload = {
            "video_note": None,
            "video": None,
            "document": None,
            "forward_origin": None,
            "forward_from": None,
            "forward_sender_name": None,
            "from_user": SimpleNamespace(id=1, username="cododel", full_name="Alex"),
        }
        payload.update(attachments)
        super().__init__(**payload)
        self.answers: list = []

    async def answer(self, text, reply_markup=None, **_kwargs) -> None:
        self.answers.append((text, reply_markup))


def callback_data(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_regular_video_offers_the_plain_circle_choice() -> None:
    message = FakeMessage(
        video=SimpleNamespace(file_id="video-1", duration=12, file_size=1_000_000)
    )
    state = FakeState()

    asyncio.run(handlers.handle_video(message, state))

    assert state.state == handlers.ProcessingState.waiting_for_mode
    text, markup = message.answers[-1]
    assert callback_data(markup) == ["mode_circle", "mode_overlay"]
    assert "Что с ним сделать?" in text
    # The signature candidates are resolved up front, while the original
    # message is still at hand: the callback only sees the bot's own message.
    assert state.data["sender_username"] == "@cododel"


def test_video_note_skips_the_mode_choice() -> None:
    message = FakeMessage(
        video_note=SimpleNamespace(file_id="note-1", duration=12, file_size=900_000)
    )
    state = FakeState()

    asyncio.run(handlers.handle_video(message, state))

    # A video note is already a circle, so only the overlay path makes sense.
    assert state.state == handlers.ProcessingState.waiting_for_username_source
    _text, markup = message.answers[-1]
    assert callback_data(markup) == ["username_sender", "username_custom"]


def test_probe_duration_returns_zero_for_unreadable_input(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"

    assert asyncio.run(video_processor.probe_duration(str(missing))) == 0.0
