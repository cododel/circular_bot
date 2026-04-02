"""Inline keyboards for bot."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_aspect_ratio_keyboard() -> InlineKeyboardMarkup:
    """Return keyboard with aspect ratio options."""
    buttons = [
        [
            InlineKeyboardButton(text="📱 9:16 (Stories)", callback_data="ratio_9:16"),
            InlineKeyboardButton(text="🟦 1:1 (Square)", callback_data="ratio_1:1"),
        ],
        [
            InlineKeyboardButton(text="🖥 16:9 (Wide)", callback_data="ratio_16:9"),
            InlineKeyboardButton(text="📷 4:5 (Instagram)", callback_data="ratio_4:5"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_username_source_keyboard(
    original_author: str | None = None,
    sender: str | None = None
) -> InlineKeyboardMarkup:
    """
    Return keyboard for selecting username source.
    
    Args:
        original_author: Username from forwarded message (if available)
        sender: Username of the person who sent the message
    """
    buttons = []
    
    if original_author:
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 Автор кружка: {original_author[:20]}",
                callback_data="username_original"
            )
        ])
    
    if sender:
        buttons.append([
            InlineKeyboardButton(
                text=f"📤 Отправитель: {sender[:20]}",
                callback_data="username_sender"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(
            text="✏️ Свой текст",
            callback_data="username_custom"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
