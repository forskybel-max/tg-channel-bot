import urllib.parse
from typing import Any
from aiogram.enums import ButtonStyle
from aiogram.types import (
    CopyTextButton,
    DisabledButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.emojis import ce_id


def _btn(
    text: str,
    emoji_key: str = "",
    fallback_prefix: str = "",
    use_ce: bool = True,
    **kwargs: Any,
) -> InlineKeyboardButton:
    """Создает инлайн-кнопку с кастомным анимированным эмодзи (или обычным префиксом, если отключено)."""
    cid = ce_id(emoji_key, enabled=use_ce) if emoji_key else None
    if cid:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=cid, **kwargs)
    label = f"{fallback_prefix} {text}".strip() if fallback_prefix else text
    return InlineKeyboardButton(text=label, **kwargs)


def format_price_badge(item: dict[str, Any], settings: dict[str, str]) -> str:
    if not item.get("is_paid") and int(item.get("price_bonus_stars") or 0) <= 0:
        return "Бесплатно"
    parts: list[str] = []
    if settings.get("enable_stars", "1") == "1" and int(item.get("price_stars") or 0) > 0:
        parts.append(f"{item['price_stars']} ⭐️")
    if int(item.get("price_bonus_stars") or 0) > 0:
        parts.append(f"{item['price_bonus_stars']} бон. ⭐️")
    if settings.get("enable_manual_pay", "0") == "1" and int(item.get("price_rub") or 0) > 0:
        parts.append(f"{item['price_rub']} ₽")
    return " / ".join(parts) if parts else "Скоро"


def build_main_menu_kb(
    show_paid_section: bool,
    is_admin: bool,
    channel_url: str = "",
    use_ce: bool = True,
) -> InlineKeyboardMarkup:
    """
    Единый аккуратный стиль кнопок как в SubStore (все кнопки в единой палитре с 3D-эмодзи из Finance/News/Topics).
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            _btn(
                text="БЕСПЛАТНЫЕ ГАЙДЫ",
                emoji_key="grad_cap",
                fallback_prefix="🎓",
                use_ce=use_ce,
                callback_data="nav:guides",
            )
        ]
    ]

    if show_paid_section:
        rows.append(
            [
                _btn(
                    text="Каталог",
                    emoji_key="cart",
                    fallback_prefix="🛒",
                    use_ce=use_ce,
                    callback_data="nav:shop",
                ),
                _btn(
                    text="Профиль",
                    emoji_key="shield",
                    fallback_prefix="🛡",
                    use_ce=use_ce,
                    callback_data="nav:profile",
                ),
            ]
        )
    else:
        rows.append(
            [
                _btn(
                    text="Профиль",
                    emoji_key="shield",
                    fallback_prefix="🛡",
                    use_ce=use_ce,
                    callback_data="nav:profile",
                ),
                _btn(
                    text="О проекте",
                    emoji_key="info",
                    fallback_prefix="ℹ️",
                    use_ce=use_ce,
                    callback_data="nav:info",
                ),
            ]
        )

    rows.append(
        [
            _btn(
                text="Обмен бонусов",
                emoji_key="exchange",
                fallback_prefix="💱",
                use_ce=use_ce,
                callback_data="nav:exchange",
            )
        ]
    )

    rows.append(
        [
            _btn(
                text="Бонусная система",
                emoji_key="star",
                fallback_prefix="⭐️",
                use_ce=use_ce,
                callback_data="nav:bonuses",
            )
        ]
    )

    contact_row = [
        _btn(
            text="Поддержка",
            emoji_key="chat",
            fallback_prefix="💬",
            use_ce=use_ce,
            callback_data="nav:support",
        ),
        _btn(
            text="О проекте",
            emoji_key="info",
            fallback_prefix="ℹ️",
            use_ce=use_ce,
            callback_data="nav:info",
        ),
    ]
    if channel_url:
        contact_row = [
            _btn(
                text="Поддержка",
                emoji_key="chat",
                fallback_prefix="💬",
                use_ce=use_ce,
                callback_data="nav:support",
            ),
            _btn(
                text="Наш канал",
                emoji_key="megaphone",
                fallback_prefix="📣",
                use_ce=use_ce,
                url=channel_url,
            ),
        ]
    rows.append(contact_row)

    if is_admin:
        rows.append(
            [
                _btn(
                    text="Админ-панель",
                    emoji_key="gear",
                    fallback_prefix="⚙️",
                    use_ce=use_ce,
                    callback_data="adm:menu",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_profile_kb(use_ce: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    text="Мои материалы и покупки",
                    emoji_key="gift",
                    fallback_prefix="🎁",
                    use_ce=use_ce,
                    callback_data="nav:my_items",
                )
            ],
            [
                _btn(
                    text="Обмен бонусов",
                    emoji_key="exchange",
                    fallback_prefix="💱",
                    use_ce=use_ce,
                    callback_data="nav:exchange",
                ),
                _btn(
                    text="Бонусная система",
                    emoji_key="star",
                    fallback_prefix="⭐️",
                    use_ce=use_ce,
                    callback_data="nav:bonuses",
                ),
            ],
            [
                _btn(
                    text="История бонусов",
                    emoji_key="receipt",
                    fallback_prefix="🧾",
                    use_ce=use_ce,
                    callback_data="nav:bonus_history",
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Главное меню", callback_data="nav:home"
                )
            ],
        ]
    )


def build_bonus_system_kb(ref_link: str, use_ce: bool = True) -> InlineKeyboardMarkup:
    share_text = "Забирай бесплатные гайды по ИИ и бонусные звёзды в боте!"
    share_url = (
        f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}"
        f"&text={urllib.parse.quote(share_text)}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    text="Скопировать ссылку",
                    emoji_key="link",
                    fallback_prefix="🔗",
                    use_ce=use_ce,
                    copy_text=CopyTextButton(text=ref_link),
                ),
                _btn(
                    text="Поделиться",
                    emoji_key="outbox",
                    fallback_prefix="📤",
                    use_ce=use_ce,
                    url=share_url,
                ),
            ],
            [
                _btn(
                    text="Обменять бонусы",
                    emoji_key="exchange",
                    fallback_prefix="💱",
                    use_ce=use_ce,
                    callback_data="nav:exchange",
                )
            ],
            [
                _btn(
                    text="История бонусов",
                    emoji_key="receipt",
                    fallback_prefix="🧾",
                    use_ce=use_ce,
                    callback_data="nav:bonus_history",
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Главное меню", callback_data="nav:home"
                )
            ],
        ]
    )


def build_exchange_kb(
    items: list[dict[str, Any]], user_bonus: int, use_ce: bool = True
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            _btn(
                text="ПРИГЛАСИТЬ ДРУЗЕЙ",
                emoji_key="users",
                fallback_prefix="👥",
                use_ce=use_ce,
                callback_data="nav:bonuses",
            )
        ]
    ]

    for item in items:
        cost = int(item.get("price_bonus_stars") or 0)
        can_afford = user_bonus >= cost
        rows.append(
            [
                _btn(
                    text=f"{item['title']} • {cost} ⭐️"[:64],
                    emoji_key="star" if can_afford else "gift",
                    fallback_prefix="⭐️" if can_afford else "🎁",
                    use_ce=use_ce,
                    callback_data=f"item:view:{item['id']}",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="↩️ Назад в меню", callback_data="nav:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_sub_gate_kb(
    channel_url: str, retry_callback: str = "sub:check:home", use_ce: bool = True
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if channel_url:
        rows.append(
            [
                _btn(
                    text="Подписаться на канал",
                    emoji_key="megaphone",
                    fallback_prefix="📣",
                    use_ce=use_ce,
                    url=channel_url,
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            _btn(
                text="Я подписался — продолжить",
                emoji_key="check",
                fallback_prefix="✔️",
                use_ce=use_ce,
                callback_data=retry_callback,
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_catalog_kb(
    section: str,
    categories: list[dict[str, Any]],
    items: list[dict[str, Any]],
    settings: dict[str, str],
    in_category: bool = False,
) -> InlineKeyboardMarkup:
    use_ce = settings.get("use_custom_emoji", "1") == "1"
    rows: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        cnt = int(cat.get("active_count") or 0)
        rows.append(
            [
                _btn(
                    text=f"{cat['title']} ({cnt})",
                    emoji_key="folder" if section == "guides" else "pink_bags",
                    fallback_prefix="📁" if section == "guides" else "🛍",
                    use_ce=use_ce,
                    callback_data=f"cat:{section}:{cat['id']}",
                )
            ]
        )

    for item in items:
        if item.get("is_paid"):
            badge = format_price_badge(item, settings)
            rows.append(
                [
                    _btn(
                        text=f"{item['title']} • {badge}"[:64],
                        emoji_key="diamond",
                        fallback_prefix="💎",
                        use_ce=use_ce,
                        callback_data=f"item:view:{item['id']}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    _btn(
                        text=item["title"][:64],
                        emoji_key="grad_cap",
                        fallback_prefix="🎓",
                        use_ce=use_ce,
                        callback_data=f"item:view:{item['id']}",
                    )
                ]
            )

    if in_category:
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩️ К категориям", callback_data=f"nav:{section}"
                ),
                InlineKeyboardButton(
                    text="🏠 Главное меню", callback_data="nav:home"
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩️ Главное меню", callback_data="nav:home"
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_items_kb(
    items: list[dict[str, Any]], use_ce: bool = True
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        is_paid = bool(item.get("is_paid"))
        rows.append(
            [
                _btn(
                    text=item["title"][:64],
                    emoji_key="diamond" if is_paid else "grad_cap",
                    fallback_prefix="💎" if is_paid else "🎓",
                    use_ce=use_ce,
                    callback_data=f"item:open:{item['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="↩️ В профиль", callback_data="nav:profile"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_item_card_kb(
    item: dict[str, Any],
    has_access: bool,
    settings: dict[str, str],
    back_callback: str,
    is_admin: bool = False,
    bot_username: str = "",
) -> InlineKeyboardMarkup:
    use_ce = settings.get("use_custom_emoji", "1") == "1"
    rows: list[list[InlineKeyboardButton]] = []
    item_id = item["id"]

    if has_access:
        rows.append(
            [
                _btn(
                    text="Открыть материал",
                    emoji_key="check",
                    fallback_prefix="✔️",
                    use_ce=use_ce,
                    callback_data=f"item:open:{item_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    elif not item.get("is_paid") and int(item.get("price_bonus_stars") or 0) <= 0:
        rows.append(
            [
                _btn(
                    text="Забрать бесплатно",
                    emoji_key="inbox",
                    fallback_prefix="📥",
                    use_ce=use_ce,
                    callback_data=f"item:claim:{item_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    else:
        pay_buttons_added = False
        if (
            settings.get("enable_stars", "1") == "1"
            and int(item.get("price_stars") or 0) > 0
        ):
            rows.append(
                [
                    _btn(
                        text=f"Купить за {item['price_stars']} TG Stars",
                        emoji_key="star",
                        fallback_prefix="⭐️",
                        use_ce=use_ce,
                        callback_data=f"pay:stars:{item_id}",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            )
            pay_buttons_added = True

        bonus_cost = int(item.get("price_bonus_stars") or 0)
        if bonus_cost > 0:
            rows.append(
                [
                    _btn(
                        text=f"Обменять за {bonus_cost} бонусных ⭐️",
                        emoji_key="exchange",
                        fallback_prefix="💱",
                        use_ce=use_ce,
                        callback_data=f"pay:bonus:{item_id}",
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            )
            pay_buttons_added = True

        if (
            settings.get("enable_manual_pay", "0") == "1"
            and int(item.get("price_rub") or 0) > 0
        ):
            rows.append(
                [
                    _btn(
                        text=f"Оплатить переводом ({item['price_rub']} ₽)",
                        emoji_key="id_card",
                        fallback_prefix="💳",
                        use_ce=use_ce,
                        callback_data=f"pay:manual:{item_id}",
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            )
            pay_buttons_added = True

        if not pay_buttons_added:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⏳ Скоро в продаже",
                        disabled=DisabledButton(),
                    )
                ]
            )

    if is_admin and bot_username:
        deep_link = f"https://t.me/{bot_username}?start=item_{item_id}"
        rows.append(
            [
                _btn(
                    text="Ссылка для поста",
                    emoji_key="link",
                    fallback_prefix="🔗",
                    use_ce=use_ce,
                    copy_text=CopyTextButton(text=deep_link),
                ),
                _btn(
                    text="В админке",
                    emoji_key="gear",
                    fallback_prefix="⚙️",
                    use_ce=use_ce,
                    callback_data=f"adm:item:{item_id}",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data=back_callback),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_manual_pay_kb(item_id: int, requisites: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    clean_req = requisites.strip()
    if clean_req:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📋 Скопировать реквизиты",
                    copy_text=CopyTextButton(text=clean_req[:256]),
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Я оплатил (отправить чек)",
                callback_data=f"pay:manual_proof:{item_id}",
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="✖️ Отмена",
                callback_data=f"item:view:{item_id}",
                style=ButtonStyle.DANGER,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_cancel_kb(cancel_callback: str = "nav:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✖️ Отмена",
                    callback_data=cancel_callback,
                    style=ButtonStyle.DANGER,
                )
            ]
        ]
    )


def build_order_review_kb(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выдать доступ",
                    callback_data=f"adm:ord_ok:{order_id}",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"adm:ord_no:{order_id}",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Написать покупателю",
                    callback_data=f"adm:reply:{user_id}",
                )
            ],
        ]
    )


def build_admin_main_kb(pending_orders: int = 0) -> InlineKeyboardMarkup:
    ord_badge = f" ({pending_orders} 🔥)" if pending_orders > 0 else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить гайд / товар в каталог",
                    callback_data="adm:add_item",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Все материалы",
                    callback_data="adm:items",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="📁 Категории",
                    callback_data="adm:cats",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐️ Рефералка и бонусы",
                    callback_data="adm:ref_settings",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="✨ Узнать ID эмодзи",
                    callback_data="adm:emoji_id",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"💳 Заявки на оплату{ord_badge}",
                    callback_data="adm:orders",
                    style=ButtonStyle.SUCCESS if pending_orders > 0 else None,
                ),
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="adm:stats",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка по базе",
                    callback_data="adm:broadcast",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="⚙️ Настройки бота",
                    callback_data="adm:settings",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Открыть как пользователь",
                    callback_data="nav:home",
                )
            ],
        ]
    )


def build_admin_settings_kb(settings: dict[str, str]) -> InlineKeyboardMarkup:
    req_sub = "🟢 Вкл" if settings.get("require_sub") == "1" else "🔴 Выкл"
    paid_sec = "🟢 Виден" if settings.get("show_paid_section", "1") == "1" else "🔴 Скрыт"
    ce_on = "🟢 Вкл" if settings.get("use_custom_emoji", "1") == "1" else "🔴 Выкл"
    prof_home = (
        "🟢 Вкл" if settings.get("show_profile_in_home", "1") == "1" else "🔴 Выкл"
    )
    stars_on = "🟢 Вкл" if settings.get("enable_stars", "1") == "1" else "🔴 Выкл"
    manual_on = "🟢 Вкл" if settings.get("enable_manual_pay", "0") == "1" else "🔴 Выкл"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐️ Настройки рефералки и бонусов",
                    callback_data="adm:ref_settings",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"✨ Кастомные эмодзи: {ce_on}",
                    callback_data="adm:set_toggle:use_custom_emoji",
                    style=ButtonStyle.PRIMARY
                    if settings.get("use_custom_emoji", "1") == "1"
                    else None,
                ),
                InlineKeyboardButton(
                    text=f"🪪 Профиль в /start: {prof_home}",
                    callback_data="adm:set_toggle:show_profile_in_home",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔒 Подписка на канал: {req_sub}",
                    callback_data="adm:set_toggle:require_sub",
                    style=ButtonStyle.SUCCESS
                    if settings.get("require_sub") == "1"
                    else None,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Указать ID/@username канала",
                    callback_data="adm:set_edit:channel_id",
                ),
                InlineKeyboardButton(
                    text="🔗 Ссылка на канал",
                    callback_data="adm:set_edit:channel_url",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🛒 Раздел «Каталог»: {paid_sec}",
                    callback_data="adm:set_toggle:show_paid_section",
                    style=ButtonStyle.PRIMARY
                    if settings.get("show_paid_section", "1") == "1"
                    else None,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⭐️ Оплата TG Stars: {stars_on}",
                    callback_data="adm:set_toggle:enable_stars",
                ),
                InlineKeyboardButton(
                    text=f"💳 Полуавтомат ₽: {manual_on}",
                    callback_data="adm:set_toggle:enable_manual_pay",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏦 Реквизиты (карта/СБП/USDT)",
                    callback_data="adm:set_edit:payment_requisites",
                ),
                InlineKeyboardButton(
                    text="📝 Текст к оплате",
                    callback_data="adm:set_edit:payment_instructions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👋 Текст /start",
                    callback_data="adm:set_edit:welcome_text",
                ),
                InlineKeyboardButton(
                    text="🖼 Баннер /start",
                    callback_data="adm:set_photo:welcome_photo_id",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Текст «О проекте»",
                    callback_data="adm:set_edit:info_text",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в админку", callback_data="adm:menu"
                )
            ],
        ]
    )


def build_admin_ref_settings_kb(settings: dict[str, str]) -> InlineKeyboardMarkup:
    r_join = settings.get("ref_join_bonus", "1")
    r_first = settings.get("ref_first_buy_bonus", "15")
    r_rep = settings.get("ref_repeat_buy_bonus", "5")
    s_first = settings.get("self_first_buy_bonus", "20")
    s_rep = settings.get("self_repeat_buy_bonus", "5")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"👥 За приглашённого друга: +{r_join} ⭐️",
                    callback_data="adm:set_edit:ref_join_bonus",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔥 Рефереру за 1-ю покупку друга: +{r_first} ⭐️",
                    callback_data="adm:set_edit:ref_first_buy_bonus",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔄 Рефереру за след. покупки: +{r_rep} ⭐️",
                    callback_data="adm:set_edit:ref_repeat_buy_bonus",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🛍 Покупателю за 1-ю покупку: +{s_first} ⭐️",
                    callback_data="adm:set_edit:self_first_buy_bonus",
                ),
                InlineKeyboardButton(
                    text=f"🛍 За следующие: +{s_rep} ⭐️",
                    callback_data="adm:set_edit:self_repeat_buy_bonus",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Баннер раздела «Бонусная система»",
                    callback_data="adm:set_photo:bonus_banner_photo_id",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Начислить / списать бонусы по ID",
                    callback_data="adm:bonus_give",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В админку", callback_data="adm:menu"
                )
            ],
        ]
    )


def build_admin_item_manage_kb(
    item: dict[str, Any], bot_username: str
) -> InlineKeyboardMarkup:
    item_id = item["id"]
    deep_link = f"https://t.me/{bot_username}?start=item_{item_id}"
    active_label = "🟢 Опубликован" if item.get("is_active") else "🔴 Скрыт"
    paid_label = (
        "💎 Раздел: Каталог (перенести в Гайды)"
        if item.get("is_paid")
        else "📘 Раздел: Гайды (перенести в Каталог)"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Скопировать ссылку для поста в канал",
                    copy_text=CopyTextButton(text=deep_link),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="👁 Предпросмотр выдачи",
                    callback_data=f"adm:item_test:{item_id}",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text=active_label,
                    callback_data=f"adm:item_toggle_active:{item_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=paid_label,
                    callback_data=f"adm:item_toggle_paid:{item_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⭐️ Цена TG Stars ({item.get('price_stars', 0)})",
                    callback_data=f"adm:item_edit:{item_id}:price_stars",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text=f"🎁 За бонусы ({item.get('price_bonus_stars', 0)} ⭐️)",
                    callback_data=f"adm:item_edit:{item_id}:price_bonus_stars",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"💳 Цена в рублях ({item.get('price_rub', 0)} ₽)",
                    callback_data=f"adm:item_edit:{item_id}:price_rub",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Название",
                    callback_data=f"adm:item_edit:{item_id}:title",
                ),
                InlineKeyboardButton(
                    text="📝 Описание витрины",
                    callback_data=f"adm:item_edit:{item_id}:description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📄 Текст/ссылка внутри",
                    callback_data=f"adm:item_edit:{item_id}:content_text",
                ),
                InlineKeyboardButton(
                    text="📎 Файл внутри",
                    callback_data=f"adm:item_file:{item_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Обложка карточки",
                    callback_data=f"adm:item_cover:{item_id}",
                ),
                InlineKeyboardButton(
                    text="📋 Кнопка-копирка",
                    callback_data=f"adm:item_edit:{item_id}:copy_snippet",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📁 Сменить категорию",
                    callback_data=f"adm:item_cat:{item_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить материал",
                    callback_data=f"adm:item_del_ask:{item_id}",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Ко всем материалам", callback_data="adm:items"
                )
            ],
        ]
    )
