from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Официальные кастомные анимированные эмодзи из наборов:
# NewsEmoji ("News Emoji"), FinanceEmoji ("Finance Emoji"),
# BirthdayCollection ("Birthday Collection") и Topics ("Topics")
CUSTOM_EMOJI_MAP: dict[str, tuple[str, str]] = {
    # FinanceEmoji
    "star": ("5267500801240092311", "⭐️"),
    "id_card": ("5445353829304387411", "💳"),
    "money_bag": ("5287231198098117669", "💰"),
    "cart": ("5312361253610475399", "🛒"),
    "exchange": ("5312441427764989435", "💱"),
    "laptop": ("5193177581888755275", "💻"),
    "receipt": ("5444856076954520455", "🧾"),
    "coin": ("5377505475015235101", "🪙"),
    "rocket": ("5195033767969839232", "🚀"),
    "inbox": ("5443127283898405358", "📥"),
    "outbox": ("5445355530111437729", "📤"),
    "target": ("5310278924616356636", "🎯"),
    "tag": ("5240228673738527951", "🏷"),
    # NewsEmoji
    "news_star": ("5438496463044752972", "⭐️"),
    "arrow_down": ("5406745015365943482", "⬇️"),
    "arrow_right": ("5416117059207572332", "➡️"),
    "shield": ("5251203410396458957", "🛡"),
    "shush": ("5431609822288033666", "🤫"),
    "link": ("5271604874419647061", "🔗"),
    "check": ("5206607081334906820", "✔️"),
    "cross": ("5210952531676504517", "❌"),
    "fire": ("5424972470023104089", "🔥"),
    "diamond": ("5427168083074628963", "💎"),
    "crown": ("5217822164362739968", "👑"),
    "chat": ("5443038326535759644", "💬"),
    "megaphone": ("5424818078833715060", "📣"),
    "home": ("5416041192905265756", "🏠"),
    "gear": ("5341715473882955310", "⚙️"),
    "lock": ("5296369303661067030", "🔒"),
    "info": ("5334544901428229844", "ℹ️"),
    "plus": ("5397916757333654639", "➕"),
    "trash": ("5445267414562389170", "🗑"),
    "stats": ("5231200819986047254", "📊"),
    "free": ("5406756500108501710", "🆓"),
    "bolt": ("5456140674028019486", "⚡️"),
    "bulb": ("5422439311196834318", "💡"),
    # BirthdayCollection
    "gift": ("5449800250032143374", "🎁"),
    "pink_bags": ("5451937962629544243", "🛍"),
    "dizzy_star": ("5469744063815102906", "💫"),
    "sparkle": ("5451636889717062286", "✨"),
    "party": ("5193018401810822951", "🎉"),
    "heart": ("5406926593698312391", "❤️"),
    "clover": ("5258040062028822951", "🍀"),
    # Topics & RestrictedEmoji
    "grad_cap": ("5357419403325481346", "🎓"),
    "books": ("5350481781306958339", "📚"),
    "book": ("5226512880362332956", "📖"),
    "folder": ("5357315181649076022", "📁"),
    "users": ("5372926953978341366", "👥"),
    "user": ("5373012449597335010", "👤"),
    "check_box": ("5454096630372379732", "☑️"),
    "point_down": ("5406745015365943482", "⬇️"),
    "bags": ("5451937962629544243", "🛍"),
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
