import html
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from app.config import Config
from app.database import Database
from app.keyboards import (
    build_cancel_kb,
    build_catalog_kb,
    build_item_card_kb,
    build_main_menu_kb,
    build_my_items_kb,
    build_sub_gate_kb,
    format_price_badge,
)
from app.services.delivery import deliver_item_content
from app.services.subscription import check_user_subscription

logger = logging.getLogger(__name__)


class UserStates(StatesGroup):
    waiting_support_msg = State()


async def render_screen(
    event: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    photo_id: str = "",
) -> None:
    """Плавная отрисовка экрана (редактирует сообщение на месте, если возможно)."""
    photo_id = (photo_id or "").strip()

    if isinstance(event, Message):
        if photo_id:
            try:
                await event.answer_photo(
                    photo=photo_id,
                    caption=text[:1024],
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
            except TelegramBadRequest:
                pass
        try:
            await event.answer(
                text=text[:4096],
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except TelegramBadRequest:
            await event.answer(
                text=text[:4096],
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        return

    # CallbackQuery
    msg = event.message
    if msg is None:
        return

    has_current_photo = bool(msg.photo)

    try:
        if photo_id and has_current_photo:
            await msg.edit_media(
                media=InputMediaPhoto(
                    media=photo_id, caption=text[:1024], parse_mode="HTML"
                ),
                reply_markup=reply_markup,
            )
            return
        if not photo_id and not has_current_photo and msg.text is not None:
            await msg.edit_text(
                text=text[:4096],
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return

    # Если переход между фото <-> текстом или старым сообщением выдачи файла
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass

    if photo_id:
        try:
            await msg.answer_photo(
                photo=photo_id,
                caption=text[:1024],
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest:
            pass

    try:
        await msg.answer(
            text=text[:4096],
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await msg.answer(
            text=text[:4096],
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


def format_item_card_text(item: dict[str, Any], settings: dict[str, str], has_access: bool) -> str:
    icon = "💎" if item.get("is_paid") else "📘"
    title = html.escape(item.get("title", "Материал"))
    desc = (item.get("description") or "").strip()

    if has_access:
        status_line = "✅ <b>Доступ открыт</b>"
    elif not item.get("is_paid"):
        status_line = "🎁 <b>Доступно бесплатно</b>"
    else:
        badge = format_price_badge(item, settings)
        status_line = f"💳 <b>Стоимость:</b> {badge}"

    parts = [f"{icon} <b>{title}</b>"]
    if desc:
        parts.append(desc)
    parts.append(status_line)
    return "\n\n".join(parts)


def setup_user_router(config: Config, db: Database) -> Router:
    router = Router(name="user")

    async def show_home(event: Message | CallbackQuery, user_id: int) -> None:
        settings = await db.get_all_settings()
        show_paid = settings.get("show_paid_section", "0") == "1"
        channel_url = settings.get("channel_url", "").strip()
        welcome_text = settings.get("welcome_text", "").strip() or "👋 Добро пожаловать!"
        welcome_photo = settings.get("welcome_photo_id", "").strip()

        kb = build_main_menu_kb(
            show_paid_section=show_paid,
            is_admin=user_id in config.admin_ids,
            channel_url=channel_url,
        )
        await render_screen(event, welcome_text, kb, photo_id=welcome_photo)

    async def show_item_card(
        event: Message | CallbackQuery,
        bot: Bot,
        user_id: int,
        item: dict[str, Any],
    ) -> None:
        settings = await db.get_all_settings()
        has_access = await db.has_access(user_id, item["id"])
        me = await bot.get_me()

        if item.get("category_id"):
            sec = "shop" if item.get("is_paid") else "guides"
            back_cb = f"cat:{sec}:{item['category_id']}"
        else:
            back_cb = "nav:shop" if item.get("is_paid") else "nav:guides"

        card_text = format_item_card_text(item, settings, has_access)
        kb = build_item_card_kb(
            item=item,
            has_access=has_access,
            settings=settings,
            back_callback=back_cb,
            is_admin=user_id in config.admin_ids,
            bot_username=me.username or "",
        )
        await render_screen(
            event,
            card_text,
            kb,
            photo_id=item.get("cover_photo_id", ""),
        )

    @router.message(CommandStart())
    async def cmd_start(
        message: Message, command: CommandObject, state: FSMContext, bot: Bot
    ) -> None:
        await state.clear()
        user = message.from_user
        if not user:
            return

        payload = (command.args or "").strip()
        await db.upsert_user(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            source_param=payload,
        )

        # Обработка прямых ссылок из постов канала: ?start=item_12
        if payload.startswith("item_"):
            raw_id = payload[len("item_") :]
            if raw_id.isdigit():
                item = await db.get_item(int(raw_id))
                if item and (item.get("is_active") or user.id in config.admin_ids):
                    if not item.get("is_paid"):
                        is_sub, ch_url = await check_user_subscription(
                            bot, db, user.id, config.admin_ids
                        )
                        if not is_sub:
                            gate_text = (
                                f"🔒 Чтобы бесплатно забрать материал <b>«{html.escape(item['title'])}»</b>, "
                                "подпишитесь на наш Telegram-канал и нажмите зелёную кнопку ниже:"
                            )
                            await message.answer(
                                gate_text,
                                parse_mode="HTML",
                                reply_markup=build_sub_gate_kb(
                                    ch_url, f"item:claim:{item['id']}"
                                ),
                            )
                            return
                        await db.grant_access(user.id, item["id"], access_type="free")
                        await deliver_item_content(bot, message.chat.id, item)
                        return

                    # Платный материал — показываем карточку товара
                    await show_item_card(message, bot, user.id, item)
                    return

        await show_home(message, user.id)

    @router.callback_query(F.data == "nav:home")
    async def cb_home(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        await show_home(call, call.from_user.id)

    @router.callback_query(F.data.in_({"nav:guides", "nav:shop"}))
    async def cb_catalog_root(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        section = "shop" if call.data == "nav:shop" else "guides"
        is_paid = section == "shop"

        settings = await db.get_all_settings()
        categories = await db.get_categories(section=section, only_with_active_items=True)
        uncat_items = await db.get_catalog_items(
            is_paid=is_paid, uncategorized_only=True
        )

        if section == "guides":
            header = "📚 <b>Бесплатные гайды и база знаний</b>"
            empty_hint = (
                "Здесь пока нет опубликованных материалов. Скоро добавим свежие гайды!"
            )
        else:
            header = "🔥 <b>Продукты и закрытые материалы</b>"
            empty_hint = "Платные продукты сейчас готовятся к запуску. Следите за анонсами в канале!"

        if not categories and not uncat_items:
            text = f"{header}\n\n<i>{empty_hint}</i>"
        else:
            text = f"{header}\n\n👇 Выберите нужный раздел или материал:"

        kb = build_catalog_kb(
            section=section,
            categories=categories,
            items=uncat_items,
            settings=settings,
            in_category=False,
        )
        await render_screen(call, text, kb)

    @router.callback_query(F.data.startswith("cat:"))
    async def cb_category_view(call: CallbackQuery) -> None:
        await call.answer()
        parts = (call.data or "").split(":")
        if len(parts) != 3 or not parts[2].isdigit():
            return
        section = parts[1]
        cat_id = int(parts[2])
        is_paid = section == "shop"

        category = await db.get_category(cat_id)
        if not category:
            await call.answer("Раздел не найден", show_alert=True)
            return

        settings = await db.get_all_settings()
        items = await db.get_catalog_items(is_paid=is_paid, category_id=cat_id)
        text = f"📁 <b>{html.escape(category['title'])}</b>\n\n👇 Доступные материалы в разделе:"
        if not items:
            text = f"📁 <b>{html.escape(category['title'])}</b>\n\n<i>В этой папке пока пусто.</i>"

        kb = build_catalog_kb(
            section=section,
            categories=[],
            items=items,
            settings=settings,
            in_category=True,
        )
        await render_screen(call, text, kb)

    @router.callback_query(F.data.startswith("item:view:"))
    async def cb_item_view(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit():
            await call.answer()
            return
        item = await db.get_item(int(raw_id))
        if not item or (not item.get("is_active") and call.from_user.id not in config.admin_ids):
            await call.answer("Материал недоступен", show_alert=True)
            return
        await call.answer()
        await show_item_card(call, bot, call.from_user.id, item)

    @router.callback_query(F.data.startswith("item:claim:"))
    async def cb_item_claim(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return

        item = await db.get_item(int(raw_id))
        if not item or not item.get("is_active"):
            await call.answer("Материал больше недоступен", show_alert=True)
            return
        if item.get("is_paid"):
            await call.answer("Этот материал платный", show_alert=True)
            await show_item_card(call, bot, call.from_user.id, item)
            return

        is_sub, ch_url = await check_user_subscription(
            bot, db, call.from_user.id, config.admin_ids
        )
        if not is_sub:
            await call.answer("Подпишитесь на канал, чтобы забрать гайд!", show_alert=True)
            gate_text = (
                f"🔒 Для доступа к материалу <b>«{html.escape(item['title'])}»</b> "
                "необходимо быть подписчиком нашего канала.\n\n"
                "Подпишитесь и нажмите кнопку проверки ниже 👇"
            )
            await render_screen(
                call,
                gate_text,
                build_sub_gate_kb(ch_url, f"item:claim:{item['id']}"),
            )
            return

        await call.answer("Готово! Отправляю материал 🎁")
        await db.grant_access(call.from_user.id, item["id"], access_type="free")
        await deliver_item_content(bot, call.message.chat.id, item)

    @router.callback_query(F.data.startswith("item:open:"))
    async def cb_item_open(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return

        item = await db.get_item(int(raw_id))
        if not item:
            await call.answer("Материал не найден", show_alert=True)
            return

        has_access = await db.has_access(call.from_user.id, item["id"])
        if not has_access and call.from_user.id not in config.admin_ids:
            await call.answer("У вас нет доступа к этому материалу", show_alert=True)
            return

        await call.answer("Отправляю материал 📂")
        await deliver_item_content(bot, call.message.chat.id, item)

    @router.callback_query(F.data == "nav:my_items")
    async def cb_my_items(call: CallbackQuery) -> None:
        await call.answer()
        items = await db.get_user_items(call.from_user.id)
        if not items:
            text = (
                "🎒 <b>Мои материалы</b>\n\n"
                "У вас пока нет открытых гайдов или покупок.\n"
                "Загляните в раздел <b>«📚 Бесплатные гайды и база»</b>!"
            )
        else:
            text = (
                f"🎒 <b>Мои материалы ({len(items)})</b>\n\n"
                "Нажмите на любой материал, чтобы открыть его снова:"
            )
        await render_screen(call, text, build_my_items_kb(items))

    @router.callback_query(F.data == "nav:info")
    async def cb_info(call: CallbackQuery) -> None:
        await call.answer()
        info_text = await db.get_setting("info_text", "ℹ️ Информация скоро появится.")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💬 Связь с автором",
                        callback_data="nav:support",
                        style=ButtonStyle.PRIMARY,
                    )
                ],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav:home")],
            ]
        )
        await render_screen(call, info_text, kb)

    @router.callback_query(F.data == "nav:support")
    async def cb_support_start(call: CallbackQuery, state: FSMContext) -> None:
        await call.answer()
        await state.set_state(UserStates.waiting_support_msg)
        text = (
            "💬 <b>Связь с автором / Предложка / Реклама</b>\n\n"
            "Напишите ваш вопрос, предложение или запрос на сотрудничество одним сообщением "
            "(можно прикрепить фото или файл) — я сразу передам его автору канала:"
        )
        await render_screen(call, text, build_cancel_kb("nav:home"))

    @router.message(UserStates.waiting_support_msg)
    async def process_support_msg(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        await state.clear()
        user = message.from_user
        if not user:
            return

        uname = f"@{user.username}" if user.username else "без @username"
        header = (
            f"📩 <b>Новое обращение в поддержку</b>\n"
            f"От: <b>{html.escape(user.full_name)}</b> ({uname}, ID: <code>{user.id}</code>)"
        )
        reply_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↩️ Ответить пользователю",
                        callback_data=f"adm:reply:{user.id}",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            ]
        )

        for admin_id in config.admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=header,
                    parse_mode="HTML",
                    reply_markup=reply_kb,
                )
                await message.copy_to(chat_id=admin_id)
            except Exception as exc:
                logger.warning("Не удалось доставить тикет админу %s: %s", admin_id, exc)

        await message.answer(
            "✅ <b>Сообщение отправлено!</b> Автор ответит вам прямо здесь в боте.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏠 Главное меню",
                            callback_data="nav:home",
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            ),
        )

    return router
