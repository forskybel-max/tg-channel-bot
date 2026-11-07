from typing import Any
from aiogram.enums import ButtonStyle
from aiogram.types import (
    CopyTextButton,
    DisabledButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def format_price_badge(item: dict[str, Any], settings: dict[str, str]) -> str:
    if not item.get("is_paid"):
        return "Бесплатно"
    parts: list[str] = []
    if settings.get("enable_manual_pay", "1") == "1" and int(item.get("price_rub") or 0) > 0:
        parts.append(f"{item['price_rub']} ₽")
    if settings.get("enable_stars", "1") == "1" and int(item.get("price_stars") or 0) > 0:
        parts.append(f"⭐️ {item['price_stars']}")
    return " / ".join(parts) if parts else "Скоро"


def build_main_menu_kb(
    show_paid_section: bool,
    is_admin: bool,
    channel_url: str = "",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📚 Бесплатные гайды и база",
                callback_data="nav:guides",
                style=ButtonStyle.PRIMARY,
            )
        ]
    ]

    if show_paid_section:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔥 Продукты и закрытые материалы",
                    callback_data="nav:shop",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="🎒 Мои материалы", callback_data="nav:my_items"),
            InlineKeyboardButton(text="ℹ️ О проекте", callback_data="nav:info"),
        ]
    )

    contact_row = [
        InlineKeyboardButton(text="💬 Связь с автором", callback_data="nav:support")
    ]
    if channel_url:
        contact_row.append(
            InlineKeyboardButton(text="📢 Наш канал", url=channel_url)
        )
    rows.append(contact_row)

    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚙️ Админ-панель",
                    callback_data="adm:menu",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_sub_gate_kb(channel_url: str, retry_callback: str = "sub:check:home") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if channel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📢 Подписаться на канал",
                    url=channel_url,
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Я подписался — продолжить",
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
    rows: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        cnt = int(cat.get("active_count") or 0)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📁 {cat['title']} ({cnt})",
                    callback_data=f"cat:{section}:{cat['id']}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )

    for item in items:
        if item.get("is_paid"):
            badge = format_price_badge(item, settings)
            label = f"💎 {item['title']} • {badge}"
        else:
            label = f"📘 {item['title']}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:64],
                    callback_data=f"item:view:{item['id']}",
                )
            ]
        )

    if in_category:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️ К разделам", callback_data=f"nav:{section}"
                ),
                InlineKeyboardButton(text="🏠 Меню", callback_data="nav:home"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home")]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_items_kb(items: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        icon = "💎" if item.get("is_paid") else "📘"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {item['title']}"[:64],
                    callback_data=f"item:open:{item['id']}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_item_card_kb(
    item: dict[str, Any],
    has_access: bool,
    settings: dict[str, str],
    back_callback: str,
    is_admin: bool = False,
    bot_username: str = "",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    item_id = item["id"]

    if has_access:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📂 Открыть материал",
                    callback_data=f"item:open:{item_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    elif not item.get("is_paid"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="📥 Забрать бесплатно",
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
                    InlineKeyboardButton(
                        text=f"⭐️ Купить за {item['price_stars']} Stars",
                        callback_data=f"pay:stars:{item_id}",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            )
            pay_buttons_added = True

        if (
            settings.get("enable_manual_pay", "1") == "1"
            and int(item.get("price_rub") or 0) > 0
        ):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"💳 Оплатить переводом ({item['price_rub']} ₽)",
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
                InlineKeyboardButton(
                    text="🔗 Ссылка для поста",
                    copy_text=CopyTextButton(text=deep_link),
                ),
                InlineKeyboardButton(
                    text="⚙️ В админке",
                    callback_data=f"adm:item:{item_id}",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback),
            InlineKeyboardButton(text="🏠 Меню", callback_data="nav:home"),
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
                    text="➕ Добавить гайд / товар",
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
    users_cnt = "🟢 Вкл" if settings.get("show_users_count", "1") == "1" else "🔴 Выкл"
    paid_sec = "🟢 Виден" if settings.get("show_paid_section") == "1" else "🔴 Скрыт"
    stars_on = "🟢 Вкл" if settings.get("enable_stars") == "1" else "🔴 Выкл"
    manual_on = "🟢 Вкл" if settings.get("enable_manual_pay") == "1" else "🔴 Выкл"

    return InlineKeyboardMarkup(
        inline_keyboard=[
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
                    text=f"👥 Счетчик участников сверху: {users_cnt}",
                    callback_data="adm:set_toggle:show_users_count",
                    style=ButtonStyle.PRIMARY
                    if settings.get("show_users_count", "1") == "1"
                    else None,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔥 Раздел «Продукты»: {paid_sec}",
                    callback_data="adm:set_toggle:show_paid_section",
                    style=ButtonStyle.PRIMARY
                    if settings.get("show_paid_section") == "1"
                    else None,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⭐️ Оплата Stars: {stars_on}",
                    callback_data="adm:set_toggle:enable_stars",
                ),
                InlineKeyboardButton(
                    text=f"💳 Полуавтомат: {manual_on}",
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
                    text="🖼 Обложка /start",
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


def build_admin_item_manage_kb(
    item: dict[str, Any], bot_username: str
) -> InlineKeyboardMarkup:
    item_id = item["id"]
    deep_link = f"https://t.me/{bot_username}?start=item_{item_id}"
    active_label = "🟢 Опубликован" if item.get("is_active") else "🔴 Скрыт"
    paid_label = (
        "💎 Тип: Платный товар (сделать бесплатным)"
        if item.get("is_paid")
        else "📘 Тип: Бесплатный гайд (сделать платным)"
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
                    text=f"💳 Цена ₽ ({item.get('price_rub', 0)})",
                    callback_data=f"adm:item_edit:{item_id}:price_rub",
                ),
                InlineKeyboardButton(
                    text=f"⭐️ Цена Stars ({item.get('price_stars', 0)})",
                    callback_data=f"adm:item_edit:{item_id}:price_stars",
                ),
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
