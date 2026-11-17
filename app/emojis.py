from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Официальные Telegram Custom Emoji ID из системного набора RestrictedEmoji
CUSTOM_EMOJI_MAP: dict[str, tuple[str, str]] = {
    "star": ("5435957248314579621", "⭐️"),
    "glow_star": ("5458799228719472718", "🌟"),
    "sparkle": ("5472164874886846699", "✨"),
    "rocket": ("5445284980978621387", "🚀"),
    "check": ("5427009714745517609", "✅"),
    "check_box": ("5454096630372379732", "☑️"),
    "cart": ("5431499171045581032", "🛒"),
    "book": ("5226512880362332956", "📖"),
    "books": ("5373098009640836781", "📚"),
    "diamond": ("5471952986970267163", "💎"),
    "user": ("5373012449597335010", "👤"),
    "id_card": ("5422683699130933153", "🪪"),
    "gift": ("5199749070830197566", "🎁"),
    "exchange": ("5264727218734524899", "🔄"),
    "chat": ("5465300082628763143", "💬"),
    "point_down": ("5470177992950946662", "👇"),
    "money": ("5375296873982604963", "💰"),
    "coin": ("5379600444098093058", "🪙"),
    "bags": ("5373052667671093676", "🛍"),
    "users": ("5372926953978341366", "👥"),
    "fire": ("5420315771991497307", "🔥"),
    "party": ("5436040291507247633", "🎉"),
    "trophy": ("5409008750893734809", "🏆"),
    "link": ("5375129357373165375", "🔗"),
}


def ce(key: str, enabled: bool = True) -> str:
    """Возвращает HTML-тег анимированного кастомного эмодзи <tg-emoji> или обычный эмодзи."""
    cid, fallback = CUSTOM_EMOJI_MAP.get(key, ("", "•"))
    if not enabled or not cid:
        return fallback
    return f'<tg-emoji emoji-id="{cid}">{fallback}</tg-emoji>'


def ce_id(key: str, enabled: bool = True) -> str | None:
    """Возвращает ID кастомного эмодзи для поля icon_custom_emoji_id кнопки."""
    if not enabled:
        return None
    cid, _ = CUSTOM_EMOJI_MAP.get(key, ("", ""))
    return cid or None


def strip_custom_emoji_from_markup(
    markup: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    """Убирает icon_custom_emoji_id со всех кнопок (авто-фоллбэк, если у владельца бота нет TG Premium)."""
    if markup is None:
        return None
    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for btn in row:
            data = btn.model_dump(exclude_none=True)
            data.pop("icon_custom_emoji_id", None)
            new_row.append(InlineKeyboardButton(**data))
        new_rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)
