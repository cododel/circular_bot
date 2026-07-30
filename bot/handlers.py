"""Telegram bot handlers."""
import os
import html
import re
import uuid
from dataclasses import dataclass
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import MAX_VIDEO_SIZE_BYTES, TEMP_DIR, ALLOWED_USERS
from bot.keyboards import (
    get_aspect_ratio_keyboard,
    get_username_source_keyboard,
    get_video_mode_keyboard,
)
from bot.video_processor import (
    circle_max_duration,
    circle_output_size,
    cleanup_temp_files,
    exceeds_circle_duration,
    probe_duration,
    process_circle_async,
    process_video_async,
)


router = Router()

SEND_VIDEO_HINT = (
    "Пришли кружок (video note) или обычное видео — "
    "обычное я могу просто обрезать в кружок или обработать с оверлеем."
)


def is_user_allowed(user_id: int) -> bool:
    """Check if user is in whitelist (if whitelist is configured)."""
    if ALLOWED_USERS is None:
        return True  # No whitelist = allow all
    return user_id in ALLOWED_USERS


class ProcessingState(StatesGroup):
    """States for video processing flow."""
    waiting_for_mode = State()  # Plain circle or the full overlay pipeline
    waiting_for_ratio = State()
    waiting_for_text = State()
    waiting_for_username_source = State()  # NEW: Choose username source
    processing = State()


@dataclass(frozen=True)
class VideoSource:
    """A processable video attached to a message, whatever its kind."""

    file_id: str
    duration: float
    file_size: int | None
    kind: str


RECEIVED_PHRASES = {
    "video_note": "🎯 Кружок получен!",
    "video": "🎯 Видео получено!",
}


def extract_video_source(message: Message) -> VideoSource | None:
    """Return the video attached to a message, or None if there is none."""
    if message.video_note:
        note = message.video_note
        return VideoSource(
            file_id=note.file_id,
            duration=float(note.duration or 0),
            file_size=note.file_size,
            kind="video_note",
        )

    if message.video:
        video = message.video
        return VideoSource(
            file_id=video.file_id,
            duration=float(video.duration or 0),
            file_size=video.file_size,
            kind="video",
        )

    document = message.document
    if document and (document.mime_type or "").startswith("video/"):
        # Documents carry no duration; ffprobe recovers it after download.
        return VideoSource(
            file_id=document.file_id,
            duration=0.0,
            file_size=document.file_size,
            kind="video",
        )

    return None


def exceeds_size_limit(file_size: int | None) -> bool:
    """Check a declared file size against the Bot API download limit."""
    if not MAX_VIDEO_SIZE_BYTES or not file_size:
        return False
    return file_size > MAX_VIDEO_SIZE_BYTES


def get_username_from_user(user) -> str | None:
    """Get username or full name from user object."""
    if not user:
        return None
    
    # Keep the signature compact; the @ prefix already identifies Telegram.
    if user.username:
        return f"@{user.username}"
    
    # Fallback to full name
    full_name = user.full_name.strip()
    if full_name:
        return full_name
    
    return None


def extract_author_from_caption(caption: str | None) -> str | None:
    """Try to extract original author from forwarded message caption."""
    if not caption:
        return None
    
    # Look for patterns like "From @username" or "via @username"
    patterns = [
        r'@[\w_]{5,32}',  # Standard username pattern
        r'via\s+@([\w_]{5,32})',
        r'from\s+@([\w_]{5,32})',
        r'by\s+@([\w_]{5,32})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, caption, re.IGNORECASE)
        if match:
            username = match.group(0) if match.group(0).startswith('@') else f"@{match.group(1)}"
            return username
    
    return None


def normalize_username(text: str) -> str:
    """
    Normalize username input.
    - Trim whitespace
    - Remove a legacy TG: prefix
    - Collapse duplicate @ symbols
    """
    text = text.strip()
    
    # Strip the legacy label so the arc contains only the useful identity.
    if text.upper().startswith("TG:"):
        text = text[3:].strip()

    # If it looks like a username, keep exactly one @ prefix.
    if text.startswith("@"):
        return re.sub(r'^@+', '@', text)
    
    # If contains @ somewhere (like "channel @username")
    if "@" in text:
        # Try to extract username
        match = re.search(r'@([\w_]{5,32})', text)
        if match:
            return f"@{match.group(1)}"
    
    # Plain text - return as-is
    return text


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    # Check whitelist
    if not is_user_allowed(message.from_user.id):
        return  # Silently ignore
    
    await message.answer(
        "👋 Привет! Я бот для обработки видео Telegram.\n\n"
        "Отправь обычное видео — предложу два варианта:\n"
        "• ⭕ <b>Просто кружок</b> — обрежу центральный квадрат "
        "и верну готовый video note\n"
        "• 🎨 <b>С оверлеем</b> — круглая маска по центру кадра, "
        "размытый ambient background и подпись по дуге "
        "в формате 9:16, 1:1, 16:9 или 4:5\n\n"
        "Кружок (video note) сразу идёт по второму пути."
    )


@router.message(F.video_note | F.video | F.document)
async def handle_video(message: Message, state: FSMContext):
    """Handle an incoming video note, regular video or video document."""
    # Check whitelist
    if not is_user_allowed(message.from_user.id):
        return  # Silently ignore

    source = extract_video_source(message)
    if source is None:
        # A non-video document landed here through the F.document filter.
        await message.answer(f"❌ Это не видео.\n{SEND_VIDEO_HINT}")
        return

    if exceeds_size_limit(source.file_size):
        limit_mb = MAX_VIDEO_SIZE_BYTES // (1024 * 1024)
        await message.answer(
            f"❌ Файл слишком большой ({source.file_size / 1024 / 1024:.1f} МБ). "
            f"Telegram отдаёт ботам файлы до {limit_mb} МБ — "
            "пришли видео покороче или пожми его."
        )
        return

    # Store video info in state
    await state.update_data(
        source_file_id=source.file_id,
        source_duration=source.duration,
        source_kind=source.kind,
    )

    # Get usernames
    sender = get_username_from_user(message.from_user)

    # Try to get original author from forwarded message
    original_author = None

    # Check forward_origin (for channels)
    if message.forward_origin:
        if message.forward_origin.type == "channel":
            # Forwarded from channel
            chat = message.forward_origin.chat
            if chat.username:
                original_author = f"@{chat.username}"
            else:
                original_author = chat.title
        elif message.forward_origin.type == "user":
            # Forwarded from user
            sender_user = message.forward_origin.sender_user
            original_author = get_username_from_user(sender_user)

    # Fallback to old fields (for compatibility)
    if not original_author:
        if message.forward_from:
            original_author = get_username_from_user(message.forward_from)
        elif message.forward_sender_name:
            original_author = message.forward_sender_name

    # Store both for later use
    await state.update_data(
        sender_username=sender,
        original_author=original_author,
    )

    # A video note is already a circle, so the plain path has nothing to offer
    # there: only regular videos get the choice.
    if source.kind != "video_note":
        await message.answer(
            f"{RECEIVED_PHRASES[source.kind]}\n\nЧто с ним сделать?",
            reply_markup=get_video_mode_keyboard(),
        )
        await state.set_state(ProcessingState.waiting_for_mode)
        return

    await prompt_username_source(
        message,
        state,
        header=RECEIVED_PHRASES[source.kind],
    )


async def prompt_username_source(
    target: Message,
    state: FSMContext,
    header: str,
    edit: bool = False,
) -> None:
    """Ask which username should be used for the signature.

    Reached either straight from a video note or from the mode keyboard, so the
    prompt can replace the bot's own message instead of adding another one.
    """
    data = await state.get_data()
    keyboard = get_username_source_keyboard(
        original_author=data.get("original_author"),
        sender=data.get("sender_username"),
    )

    text = f"{header}\n\nВыбери, чей юзернейм использовать для подписи:"
    if edit:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

    await state.set_state(ProcessingState.waiting_for_username_source)


@router.callback_query(ProcessingState.waiting_for_mode, F.data == "mode_overlay")
async def handle_overlay_mode(callback: CallbackQuery, state: FSMContext):
    """Continue into the full pipeline: signature, format, ambient render."""
    await callback.answer("Обработка с оверлеем")
    await prompt_username_source(
        callback.message,
        state,
        header="🎨 Обработка с оверлеем",
        edit=True,
    )


@router.callback_query(ProcessingState.waiting_for_mode, F.data == "mode_circle")
async def handle_circle_mode(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Crop the video to its center square and send it back as a video note."""
    await callback.answer("Делаю кружок")

    data = await state.get_data()
    file_id = data.get("source_file_id")
    video_duration = float(data.get("source_duration") or 0.0)

    temp_input = None
    temp_output = None
    progress_message = None

    try:
        await callback.message.edit_text("⏳ Загружаю видео...")

        job_id = uuid.uuid4().hex
        temp_input = os.path.join(TEMP_DIR, f"input_{job_id}.mp4")
        temp_output = os.path.join(TEMP_DIR, f"circle_{job_id}.mp4")

        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, temp_input)

        # Documents arrive without a duration, and the trimming notice needs it.
        if video_duration <= 0:
            video_duration = await probe_duration(temp_input)

        limit = circle_max_duration()
        trimmed = exceeds_circle_duration(video_duration)
        notice = ""
        if trimmed:
            notice = (
                f"\n✂️ Видео длиннее {limit:g} с — "
                "кружком уйдёт только начало."
            )

        async def report_progress(percent: int):
            nonlocal progress_message
            try:
                text = f"⏳ Делаю кружок: {percent}%{notice}"
                if progress_message is None:
                    progress_message = await callback.message.edit_text(text)
                else:
                    await progress_message.edit_text(text)
            except Exception:
                pass  # Ignore edit errors

        await process_circle_async(
            input_path=temp_input,
            output_path=temp_output,
            progress_callback=report_progress,
            video_duration=video_duration,
        )

        # An unknown duration is left to Telegram rather than guessed at.
        sent_duration = int(min(video_duration, limit)) if video_duration > 0 else None
        await callback.message.answer_video_note(
            video_note=FSInputFile(temp_output),
            length=circle_output_size(),
            duration=sent_duration,
        )
        if trimmed:
            await callback.message.answer(
                f"✂️ Исходное видео длиннее {limit:g} с, "
                "поэтому в кружок попала только первая часть."
            )

        try:
            await callback.message.delete()
        except Exception:
            pass

    except Exception as e:
        error_msg = html.escape(str(e))
        await callback.message.edit_text(
            f"❌ Ошибка при обработке видео:\n<pre>{error_msg}</pre>"
        )
    finally:
        cleanup_temp_files(temp_input, temp_output)
        await state.clear()


@router.callback_query(ProcessingState.waiting_for_mode)
async def ignore_other_mode_callbacks(callback: CallbackQuery):
    """Ignore unexpected callbacks in mode selection."""
    await callback.answer("Пожалуйста, выбери вариант из списка")


@router.callback_query(ProcessingState.waiting_for_username_source, F.data == "username_original")
async def handle_original_author_selection(callback: CallbackQuery, state: FSMContext):
    """Handle selection of original author as username source."""
    data = await state.get_data()
    original_author = data.get("original_author", "@unknown")
    
    await state.update_data(overlay_text=original_author)
    await callback.answer(f"Выбран: {original_author}")
    await callback.message.edit_text(
        f"✅ Подпись: «{original_author}»\n\n"
        f"Выбери формат выходного видео:",
        reply_markup=get_aspect_ratio_keyboard()
    )
    await state.set_state(ProcessingState.waiting_for_ratio)


@router.callback_query(ProcessingState.waiting_for_username_source, F.data == "username_sender")
async def handle_sender_selection(callback: CallbackQuery, state: FSMContext):
    """Handle selection of sender as username source."""
    data = await state.get_data()
    sender = data.get("sender_username", "@unknown")
    
    await state.update_data(overlay_text=sender)
    await callback.answer(f"Выбран: {sender}")
    await callback.message.edit_text(
        f"✅ Подпись: «{sender}»\n\n"
        f"Выбери формат выходного видео:",
        reply_markup=get_aspect_ratio_keyboard()
    )
    await state.set_state(ProcessingState.waiting_for_ratio)


@router.callback_query(ProcessingState.waiting_for_username_source, F.data == "username_custom")
async def handle_custom_username_selection(callback: CallbackQuery, state: FSMContext):
    """Handle selection of custom username - ask for text input."""
    await callback.answer("Введи свой текст")
    await callback.message.edit_text(
        "📝 Напиши текст подписи для оверлея.\n\n"
        "Примеры:\n"
        "• @channel_name\n"
        "• Мой канал\n"
        "• Автор видео"
    )
    await state.set_state(ProcessingState.waiting_for_text)


@router.message(ProcessingState.waiting_for_text, F.text)
async def handle_overlay_text_input(message: Message, state: FSMContext):
    """Handle manual overlay text input from user."""
    overlay_text = message.text.strip()
    
    if len(overlay_text) > 50:
        await message.answer(
            "❌ Текст слишком длинный (максимум 50 символов). "
            "Попробуй короче:"
        )
        return
    
    await state.update_data(overlay_text=overlay_text)
    await message.answer(
        f"✅ Подпись: «{overlay_text}»\n\n"
        f"Выбери формат выходного видео:",
        reply_markup=get_aspect_ratio_keyboard()
    )
    await state.set_state(ProcessingState.waiting_for_ratio)


@router.message(ProcessingState.waiting_for_text)
async def handle_invalid_overlay_input(message: Message):
    """Handle non-text input when waiting for overlay text."""
    await message.answer(
        "❌ Пожалуйста, отправь текстовое сообщение с подписью для оверлея."
    )


@router.callback_query(ProcessingState.waiting_for_ratio, F.data.startswith("ratio_"))
async def process_ratio_selection(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Handle aspect ratio selection and process video."""
    ratio = callback.data.replace("ratio_", "")
    
    await callback.answer(f"Выбран формат {ratio}")
    
    # Get stored data
    data = await state.get_data()
    file_id = data.get("source_file_id")
    overlay_text = data.get("overlay_text", "")
    video_duration = float(data.get("source_duration") or 0.0)
    # Video notes need their own sampling rules: Telegram bakes a white round
    # mask into them, so only the inner circle carries usable pixels.
    source_kind = data.get("source_kind") or "video"

    temp_input = None
    temp_output = None
    progress_message = None
    
    try:
        # Get aspect ratio dimensions
        from bot.config import ASPECT_RATIOS
        target_size = ASPECT_RATIOS.get(ratio, (720, 1280))
        
        # Download video
        await callback.message.edit_text(f"⏳ Загружаю видео...")
        
        file = await bot.get_file(file_id)
        job_id = uuid.uuid4().hex
        temp_input = os.path.join(TEMP_DIR, f"input_{job_id}.mp4")
        temp_output = os.path.join(TEMP_DIR, f"output_{job_id}_{ratio}.mp4")
        
        await bot.download_file(file.file_path, temp_input)

        # Regular videos may arrive without a usable duration; without it the
        # progress percentage cannot be computed.
        if video_duration <= 0:
            video_duration = await probe_duration(temp_input)

        # Progress callback
        async def report_progress(percent: int):
            nonlocal progress_message
            try:
                if progress_message is None:
                    progress_message = await callback.message.edit_text(
                        f"⏳ Обрабатываю видео: {percent}%"
                    )
                else:
                    await progress_message.edit_text(
                        f"⏳ Обрабатываю видео: {percent}%"
                    )
            except Exception:
                pass  # Ignore edit errors
        
        # Process video with progress
        await process_video_async(
            input_path=temp_input,
            output_path=temp_output,
            target_size=target_size,
            overlay_text=overlay_text,
            progress_callback=report_progress,
            video_duration=video_duration,
            source_kind=source_kind,
        )
        
        # Send result
        output_file = FSInputFile(temp_output)
        await callback.message.answer_video(
            video=output_file,
            caption=f"✅ Готово! Формат: {ratio} | Подпись: {overlay_text}"
        )
        
        # Delete processing message
        try:
            await callback.message.delete()
        except Exception:
            pass
        
    except Exception as e:
        error_msg = html.escape(str(e))
        await callback.message.edit_text(
            f"❌ Ошибка при обработке видео:\n\u003cpre\u003e{error_msg}\u003c/pre\u003e"
        )
    finally:
        # Cleanup
        cleanup_temp_files(temp_input, temp_output)
        await state.clear()


@router.callback_query(ProcessingState.waiting_for_ratio)
async def ignore_other_callbacks(callback: CallbackQuery):
    """Ignore unexpected callbacks."""
    await callback.answer("Пожалуйста, выбери формат из списка")


@router.callback_query(ProcessingState.waiting_for_username_source)
async def ignore_other_username_callbacks(callback: CallbackQuery):
    """Ignore unexpected callbacks in username selection."""
    await callback.answer("Пожалуйста, выбери источник подписи")


@router.message()
async def handle_other_messages(message: Message):
    """Handle messages that carry no video."""
    await message.answer(SEND_VIDEO_HINT)
