import html
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    TelegramObject,
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

SUB_GATE_TEXT = (
    "🔒 <b>Доступ к боту открыт только для подписчиков канала!</b>\n\n"
    "Чтобы пользоваться ботом, открывать бесплатные гайды и базу материалов, "
    "подпишитесь на наш канал и нажмите зелёную кнопку проверки ниже 👇"
)


class UserStates(StatesGroup):
    waiting_support_msg = State()


class SubscriptionGateMiddleware(BaseMiddleware):
    """Глобальная проверка подписки на канал перед любым взаимодействием с ботом."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self._seen_users_ts: dict[int, float] = {}

    async def _touch_user(
        self, user_id: int, username: str, full_name: str, payload: str = ""
    ) -> None:
        now = time.monotonic()
        last_ts = self._seen_users_ts.get(user_id)
        if payload or last_ts is None or (now - last_ts) > 600.0:
            await self.db.upsert_user(
                user_id=user_id,
                username=username,
                full_name=full_name,
                source_param=payload,
            )
            if len(self._seen_users_ts) > 10000:
                self._seen_users_ts.clear()
            self._seen_users_ts[user_id] = now

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot | None = data.get("bot")
        if bot is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.successful_payment:
                return await handler(event, data)

            user = event.from_user
            if not user:
                return await handler(event, data)

            payload = ""
            if event.text and event.text.startswith("/start"):
                parts = event.text.split(maxsplit=1)
                if len(parts) > 1:
                    payload = parts[1].strip()

            await self._touch_user(
                user_id=user.id,
                username=user.username or "",
                full_name=user.full_name or "",
                payload=payload,
            )

            if user.id in self.config.admin_ids:
                return await handler(event, data)

            is_sub, ch_url = await check_user_subscription(
                bot, self.db, user.id, self.config.admin_ids
            )
            if not is_sub:
                retry_target = (
                    payload
                    if payload.startswith("item_") and len(payload) < 32
                    else "home"
                )
                await render_screen(
                    event,
                    SUB_GATE_TEXT,
                    build_sub_gate_kb(ch_url, f"sub:check:{retry_target}"),
                )
                return None

            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            user = event.from_user
            await self._touch_user(
                user_id=user.id,
                username=user.username or "",
                full_name=user.full_name or "",
            )

            cb_data = event.data or ""
            if user.id in self.config.admin_ids or cb_data.startswith("sub:check:"):
                return await handler(event, data)

            is_sub, ch_url = await check_user_subscription(
                bot, self.db, user.id, self.config.admin_ids
            )
            if not is_sub:
                await event.answer(
                    "Для работы с ботом необходимо подписаться на канал!",
                    show_alert=True,
                )
                retry_target = "home"
                if cb_data.startswith(("item:view:", "item:claim:")):
                    raw_id = cb_data.split(":")[-1]
                    if raw_id.isdigit():
                        retry_target = f"item_{raw_id}"

                await render_screen(
                    event,
                    SUB_GATE_TEXT,
                    build_sub_gate_kb(ch_url, f"sub:check:{retry_target}"),
                )
                return None

            return await handler(event, data)

        return await handler(event, data)


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


def format_item_card_text(
    item: dict[str, Any], settings: dict[str, str], has_access: bool
) -> str:
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
    sub_mw = SubscriptionGateMiddleware(config=config, db=db)
    router.message.middleware(sub_mw)
    router.callback_query.middleware(sub_mw)
    cached_bot_username = ""

    async def get_bot_username(bot: Bot) -> str:
        nonlocal cached_bot_username
        if not cached_bot_username:
            me = await bot.get_me()
            cached_bot_username = me.username or ""
        return cached_bot_username

    async def show_home(event: Message | CallbackQuery, user_id: int) -> None:
        settings = await db.get_all_settings()
        show_paid = settings.get("show_paid_section", "0") == "1"
        channel_url = settings.get("channel_url", "").strip()
        welcome_text = (
            settings.get("welcome_text", "").strip() or "👋 Добро пожаловать!"
        )
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
        bot_uname = await get_bot_username(bot) if user_id in config.admin_ids else ""

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
            bot_username=bot_uname,
        )
        await render_screen(
            event,
            card_text,
            kb,
            photo_id=item.get("cover_photo_id", ""),
        )

    async def handle_item_deeplink(
        event: Message | CallbackQuery,
        bot: Bot,
        user_id: int,
        chat_id: int,
        item_id: int,
    ) -> bool:
        item = await db.get_item(item_id)
        if not item or (not item.get("is_active") and user_id not in config.admin_ids):
            return False

        if not item.get("is_paid"):
            await db.grant_access(user_id, item["id"], access_type="free")
            await deliver_item_content(bot, chat_id, item)
            return True

        await show_item_card(event, bot, user_id, item)
        return True

    @router.callback_query(F.data.startswith("sub:check:"))
    async def cb_sub_check(
        call: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        is_sub, ch_url = await check_user_subscription(
            bot, db, call.from_user.id, config.admin_ids, force_refresh=True
        )
        if not is_sub:
            await call.answer(
                "❌ Подписка пока не найдена! Подпишитесь на канал и нажмите кнопку ещё раз.",
                show_alert=True,
            )
            return

        await state.clear()
        await call.answer("✅ Подписка подтверждена! Добро пожаловать!")

        parts = (call.data or "").split(":", maxsplit=2)
        target = parts[2] if len(parts) == 3 else "home"

        if target.startswith("item_") and call.message:
            raw_id = target[len("item_") :]
            if raw_id.isdigit():
                try:
                    await call.message.delete()
                except TelegramBadRequest:
                    pass
                handled = await handle_item_deeplink(
                    call, bot, call.from_user.id, call.message.chat.id, int(raw_id)
                )
                if handled:
                    return

        await show_home(call, call.from_user.id)

    @router.message(CommandStart())
    async def cmd_start(
        message: Message, command: CommandObject, state: FSMContext, bot: Bot
    ) -> None:
        await state.clear()
        user = message.from_user
        if not user:
            return

        payload = (command.args or "").strip()
        if payload.startswith("item_"):
            raw_id = payload[len("item_") :]
            if raw_id.isdigit():
                handled = await handle_item_deeplink(
                    message, bot, user.id, message.chat.id, int(raw_id)
                )
                if handled:
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
        categories = await db.get_categories(
            section=section, only_with_active_items=True
        )
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
        if not item or (
            not item.get("is_active") and call.from_user.id not in config.admin_ids
        ):
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
