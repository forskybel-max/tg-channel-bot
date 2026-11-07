import logging
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from app.database import Database

logger = logging.getLogger(__name__)


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
    if user_id in admin_ids:
        return True, ""

    settings = await db.get_all_settings()
    if settings.get("require_sub", "0") != "1":
        return True, ""

    raw_channel_id = settings.get("channel_id", "").strip()
    if not raw_channel_id:
        return True, ""

    channel_url = settings.get("channel_url", "").strip()
    if not channel_url and raw_channel_id.startswith("@"):
        channel_url = f"https://t.me/{raw_channel_id.lstrip('@')}"

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
            "Не удалось проверить подписку на канал %s (убедитесь, что бот добавлен в админы канала!): %s",
            raw_channel_id,
            exc,
        )
        # Не блокируем выдачу материала, если админ еще не выдал боту права в канале
        return True, channel_url
