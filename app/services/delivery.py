import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


def build_delivery_keyboard(item: dict[str, Any]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    snippet = (item.get("copy_snippet") or "").strip()
    if snippet:
        # Telegram CopyTextButton принимает от 1 до 256 символов
        rows.append(
            [
                InlineKeyboardButton(
                    text="📋 Скопировать промпт / код",
                    copy_text=CopyTextButton(text=snippet[:256]),
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )

    back_target = "nav:shop" if item.get("is_paid") else "nav:guides"
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ В каталог", callback_data=back_target),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_send_html(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=False,
        )
    except TelegramBadRequest:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=False,
        )


async def deliver_item_content(
    bot: Bot, chat_id: int, item: dict[str, Any]
) -> None:
    """Отправляет открытый гайд или купленный продукт пользователю."""
    title = html.escape(item.get("title", "Материал"))
    body = (item.get("content_text") or "").strip()
    file_id = (item.get("file_id") or "").strip()
    file_type = (item.get("file_type") or "").strip()
    markup = build_delivery_keyboard(item)

    header = f"🎁 <b>{title}</b>"
    full_text = f"{header}\n\n{body}" if body else header

    if not file_id:
        await _safe_send_html(bot, chat_id, full_text[:4096], reply_markup=markup)
        return

    caption = full_text if len(full_text) <= 1024 else header
    attach_markup = markup if len(full_text) <= 1024 else None

    try:
        if file_type == "photo":
            await bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=attach_markup,
            )
        elif file_type == "video":
            await bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=attach_markup,
            )
        elif file_type == "audio":
            await bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=attach_markup,
            )
        else:
            await bot.send_document(
                chat_id=chat_id,
                document=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=attach_markup,
            )
    except TelegramBadRequest:
        # Фоллбэк без HTML-разметки, если в тексте встретился незакрытый тег
        await bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=item.get("title", "Материал")[:1024],
            reply_markup=attach_markup,
        )

    if len(full_text) > 1024:
        await _safe_send_html(bot, chat_id, full_text[:4096], reply_markup=markup)
