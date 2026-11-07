import logging
import time
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from app.database import Database

logger = logging.getLogger(__name__)

_last_admin_warn_ts: float = 0.0


def _parse_chat_id(raw: str) -> int | str:
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    if not raw.startswith("@") and "t.me/" in raw:
        slug = raw.rstrip("/").split("t.me/")[-1]
        if slug and not slug.startswith("+"):
            return f"@{slug}"
    return raw


async def check_user_subscription(
    bot: Bot, db: Database, user_id: int, admin_ids: list[int]
) -> tuple[bool, str]:
    """
    Проверяет подписку пользователя на обязательный канал.
    Возвращает (is_subscribed, channel_url).
    """
    global _last_admin_warn_ts

    if user_id in admin_ids:
        return True, ""

    settings = await db.get_all_settings()
    if settings.get("require_sub", "0") != "1":
        return True, ""

    raw_channel_id = settings.get("channel_id", "").strip()
    if not raw_channel_id:
        return True, ""

    channel_url = settings.get("channel_url", "").strip()
    if not channel_url:
        if raw_channel_id.startswith("@"):
            channel_url = f"https://t.me/{raw_channel_id.lstrip('@')}"
        elif "t.me/" in raw_channel_id:
            channel_url = (
                raw_channel_id
                if raw_channel_id.startswith("http")
                else f"https://{raw_channel_id}"
            )

    chat_id = _parse_chat_id(raw_channel_id)
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        ):
            return True, channel_url
        if member.status == ChatMemberStatus.RESTRICTED and getattr(
            member, "is_member", False
        ):
            return True, channel_url
        return False, channel_url
    except TelegramAPIError as exc:
        logger.warning(
            "Не удалось проверить подписку на канал %s (добавьте бота в админы канала!): %s",
            raw_channel_id,
            exc,
        )
        now = time.monotonic()
        if now - _last_admin_warn_ts > 600:
            _last_admin_warn_ts = now
            me = await bot.get_me()
            warn_msg = (
                f"⚠️ <b>Внимание: не работает проверка подписки на {raw_channel_id}!</b>\n\n"
                f"Telegram вернул ошибку доступа к списку участников канала.\n"
                f"Добавьте бота <b>@{me.username}</b> в <b>Администраторы</b> канала "
                f"<code>{raw_channel_id}</code> (все галочки прав можно выключить — боту нужно просто числиться в админах, чтобы видеть подписчиков)."
            )
            for aid in admin_ids:
                try:
                    await bot.send_message(aid, warn_msg, parse_mode="HTML")
                except Exception:
                    pass
        return True, channel_url
