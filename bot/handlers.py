"""Telegram bot handlers."""
import os
import html
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import TEMP_DIR, ALLOWED_USERS
from bot.keyboards import get_aspect_ratio_keyboard, get_username_source_keyboard
from bot.video_processor import process_video_async, cleanup_temp_files


router = Router()


def is_user_allowed(user_id: int) -> bool:
    """Check if user is in whitelist (if whitelist is configured)."""
    if ALLOWED_USERS is None:
        return True  # No whitelist = allow all
    return user_id in ALLOWED_USERS


class ProcessingState(StatesGroup):
    """States for video processing flow."""
    waiting_for_ratio = State()
    waiting_for_text = State()
    waiting_for_username_source = State()  # NEW: Choose username source
    processing = State()


def get_username_from_user(user) -> str | None:
    """Get username or full name from user object."""
    if not user:
        return None
    
    # Prefer username with TG: prefix
    if user.username:
        return f"TG: @{user.username}"
    
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
            username = match.group(0) if match.group(0).startswith('@') else match.group(1)
            return f"TG: {username}"
    
    return None


def normalize_username(text: str) -> str:
    """
    Normalize username input.
    - Trim whitespace
    - Remove duplicate @ symbols
    - Add TG: prefix if username-like
    """
    text = text.strip()
    
    # If already has TG: prefix, keep it
    if text.startswith("TG: "):
        return text
    if text.startswith("TG:"):
        return f"TG: {text[3:].strip()}"
    
    # If looks like username (starts with @)
    if text.startswith("@"):
        # Remove extra @ symbols (e.g., @@username -> @username)
        text = re.sub(r'^@+', '@', text)
        return f"TG: {text}"
    
    # If contains @ somewhere (like "channel @username")
    if "@" in text:
        # Try to extract username
        match = re.search(r'@([\w_]{5,32})', text)
        if match:
            return f"TG: @{match.group(1)}"
    
    # Plain text - return as-is
    return text


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    # Check whitelist
    if not is_user_allowed(message.from_user.id):
        return  # Silently ignore
    
    await message.answer(
        "👋 Привет! Я бот для обработки кружочков Telegram.\n\n"
        "Отправь мне video note (кружок), и я добавлю на него:\n"
        "• Чёрный фон вместо белого\n"
        "• Размытый ambient background\n"
        "• Подпись в углу\n\n"
        "Готовый результат можно скачать в разных форматах (9:16, 1:1, 16:9, 4:5)."
    )


@router.message(F.video_note)
async def handle_video_note(message: Message, state: FSMContext, bot: Bot):
    """Handle incoming video note (circle)."""
    # Check whitelist
    if not is_user_allowed(message.from_user.id):
        return  # Silently ignore
    
    # Store video info in state
    await state.update_data(
        video_note_file_id=message.video_note.file_id,
        video_note_duration=message.video_note.duration,
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
                original_author = f"TG: @{chat.username}"
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
    
    # Show keyboard to choose source
    keyboard = get_username_source_keyboard(
        original_author=original_author,
        sender=sender
    )
    
    await message.answer(
        "🎯 Кружок получен!\n\n"
        "Выбери, чей юзернейм использовать для подписи:",
        reply_markup=keyboard
    )
    await state.set_state(ProcessingState.waiting_for_username_source)


@router.callback_query(ProcessingState.waiting_for_username_source, F.data == "username_original")
async def handle_original_author_selection(callback: CallbackQuery, state: FSMContext):
    """Handle selection of original author as username source."""
    data = await state.get_data()
    original_author = data.get("original_author", "TG: @unknown")
    
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
    sender = data.get("sender_username", "TG: @unknown")
    
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
        "• TG: @username\n"
        "• Мой канал\n\n"
        "Я автоматически добавлю «TG: » если это похоже на username."
    )
    await state.set_state(ProcessingState.waiting_for_text)


@router.message(ProcessingState.waiting_for_text, F.text)
async def handle_overlay_text_input(message: Message, state: FSMContext):
    """Handle manual overlay text input from user."""
    raw_text = message.text.strip()
    
    # Normalize the username
    overlay_text = normalize_username(raw_text)
    
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
    file_id = data.get("video_note_file_id")
    overlay_text = data.get("overlay_text", "")
    video_duration = data.get("video_note_duration", 0)
    
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
        temp_input = os.path.join(TEMP_DIR, f"input_{file_id}.mp4")
        temp_output = os.path.join(TEMP_DIR, f"output_{file_id}_{ratio}.mp4")
        
        await bot.download_file(file.file_path, temp_input)
        
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
            video_duration=float(video_duration),
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
    """Handle non-video-note messages."""
    await message.answer(
        "Пожалуйста, отправь мне video note (кружок).\n"
        "Это круглое видео, которое записывается через кнопку с камерой в Telegram."
    )
