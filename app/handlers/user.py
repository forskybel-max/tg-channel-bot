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
from app.emojis import ce, strip_custom_emoji_from_markup
from app.keyboards import (
    build_bonus_system_kb,
    build_cancel_kb,
    build_catalog_kb,
    build_exchange_kb,
    build_item_card_kb,
    build_main_menu_kb,
    build_my_items_kb,
    build_profile_kb,
    build_sub_gate_kb,
    format_price_badge,
)
from app.services.delivery import deliver_item_content
from app.services.subscription import check_user_subscription

logger = logging.getLogger(__name__)

SUB_GATE_TEXT = (
    "🔒 <b>Доступ к боту открыт только для подписчиков канала!</b>\n\n"
    "Чтобы пользоваться ботом, открывать бесплатные гайды, каталог и получать бонусные звёзды, "
    "подпишитесь на наш канал и нажмите зелёную кнопку проверки ниже 👇"
)


class UserStates(StatesGroup):
    waiting_support_msg = State()


def _parse_ref_id(payload: str) -> int | None:
    if payload.startswith("ref_"):
        raw = payload[len("ref_") :].strip()
        if raw.isdigit():
            return int(raw)
    return None


async def notify_referrer_if_needed(bot: Bot, db: Database, user_id: int) -> None:
    """Если новый пользователь пришел по рефке и подписался на канал — начисляет +1 звезду и шлет пуш."""
    reward = await db.process_referral_join(user_id)
    if not reward:
        return

    settings = await db.get_all_settings()
    use_ce = settings.get("use_custom_emoji", "1") == "1"

    uname = reward.get("friend_username")
    if uname:
        friend_label = f"@{html.escape(uname)}"
    else:
        fname = html.escape(reward.get("friend_name") or f"ID {reward['friend_id']}")
        friend_label = f"<b>{fname}</b>"

    bonus = reward["bonus"]
    star_word = (
        "бонусная звезда начислена"
        if bonus == 1
        else f"бонусных звёзд начислено"
    )
    msg_text = (
        f"{ce('rocket', use_ce)} <b>Приглашение успешно!</b>\n\n"
        f"{ce('check_box', use_ce)} Твой друг {friend_label} присоединился к боту\n\n"
        f"{ce('star', use_ce)} <b>+{bonus} {star_word}</b>"
    )
    try:
        await bot.send_message(
            chat_id=reward["referrer_id"],
            text=msg_text,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.debug("Не удалось отправить пуш рефереру %s: %s", reward["referrer_id"], exc)


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
        ref_id = _parse_ref_id(payload)
        if payload or ref_id or last_ts is None or (now - last_ts) > 600.0:
            await self.db.upsert_user(
                user_id=user_id,
                username=username,
                full_name=full_name,
                source_param=payload,
                referrer_id=ref_id,
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

            if user.id not in self.config.admin_ids:
                is_sub, ch_url = await check_user_subscription(
                    bot, self.db, user.id, self.config.admin_ids
                )
                if not is_sub:
                    settings = await self.db.get_all_settings()
                    use_ce = settings.get("use_custom_emoji", "1") == "1"
                    retry_target = (
                        payload
                        if payload.startswith("item_") and len(payload) < 32
                        else "home"
                    )
                    await render_screen(
                        event,
                        SUB_GATE_TEXT,
                        build_sub_gate_kb(
                            ch_url, f"sub:check:{retry_target}", use_ce=use_ce
                        ),
                    )
                    return None

            await notify_referrer_if_needed(bot, self.db, user.id)
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
                settings = await self.db.get_all_settings()
                use_ce = settings.get("use_custom_emoji", "1") == "1"
                retry_target = "home"
                if cb_data.startswith(("item:view:", "item:claim:")):
                    raw_id = cb_data.split(":")[-1]
                    if raw_id.isdigit():
                        retry_target = f"item_{raw_id}"

                await render_screen(
                    event,
                    SUB_GATE_TEXT,
                    build_sub_gate_kb(
                        ch_url, f"sub:check:{retry_target}", use_ce=use_ce
                    ),
                )
                return None

            await notify_referrer_if_needed(bot, self.db, user.id)
            return await handler(event, data)

        return await handler(event, data)


async def render_screen(
    event: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    photo_id: str = "",
) -> None:
    """Плавная отрисовка экрана с автоматическим фоллбэком кастомных эмодзи."""
    photo_id = (photo_id or "").strip()

    async def _send_new(msg_target: Message, markup: InlineKeyboardMarkup) -> None:
        if photo_id:
            try:
                await msg_target.answer_photo(
                    photo=photo_id,
                    caption=text[:1024],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                return
            except TelegramBadRequest as exc:
                if "CUSTOM_EMOJI" in str(exc).upper():
                    fallback_kb = strip_custom_emoji_from_markup(markup)
                    await msg_target.answer_photo(
                        photo=photo_id,
                        caption=text[:1024],
                        parse_mode="HTML",
                        reply_markup=fallback_kb,
                    )
                    return

        try:
            await msg_target.answer(
                text=text[:4096],
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "CUSTOM_EMOJI" in str(exc).upper():
                fallback_kb = strip_custom_emoji_from_markup(markup)
                await msg_target.answer(
                    text=text[:4096],
                    parse_mode="HTML",
                    reply_markup=fallback_kb,
                    disable_web_page_preview=True,
                )
            else:
                fallback_kb = strip_custom_emoji_from_markup(markup)
                await msg_target.answer(
                    text=text[:4096],
                    reply_markup=fallback_kb,
                    disable_web_page_preview=True,
                )

    if isinstance(event, Message):
        await _send_new(event, reply_markup)
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
        err_up = str(exc).upper()
        if "MESSAGE IS NOT MODIFIED" in err_up:
            return
        if "CUSTOM_EMOJI" in err_up:
            fallback_kb = strip_custom_emoji_from_markup(reply_markup)
            try:
                if not photo_id and not has_current_photo and msg.text is not None:
                    await msg.edit_text(
                        text=text[:4096],
                        parse_mode="HTML",
                        reply_markup=fallback_kb,
                        disable_web_page_preview=True,
                    )
                    return
            except TelegramBadRequest:
                pass

    try:
        await msg.delete()
    except TelegramBadRequest:
        pass

    await _send_new(msg, reply_markup)


def format_item_card_text(
    item: dict[str, Any],
    settings: dict[str, str],
    has_access: bool,
    user_bonus: int = 0,
) -> str:
    use_ce = settings.get("use_custom_emoji", "1") == "1"
    icon = (
        ce("diamond", use_ce)
        if item.get("is_paid")
        else ce("book", use_ce)
    )
    title = html.escape(item.get("title", "Материал"))
    desc = (item.get("description") or "").strip()

    if has_access:
        status_line = f"{ce('check', use_ce)} <b>Доступ открыт</b>"
    elif not item.get("is_paid") and int(item.get("price_bonus_stars") or 0) <= 0:
        status_line = f"{ce('gift', use_ce)} <b>Доступно бесплатно</b>"
    else:
        badge = format_price_badge(item, settings)
        status_line = f"{ce('star', use_ce)} <b>Стоимость:</b> {badge}"
        if int(item.get("price_bonus_stars") or 0) > 0:
            status_line += f"\n{ce('coin', use_ce)} <b>Ваши бонусы:</b> {user_bonus} ⭐️"

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
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        show_paid = settings.get("show_paid_section", "1") == "1"
        channel_url = settings.get("channel_url", "").strip()
        welcome_text = (
            settings.get("welcome_text", "").strip()
            or f"{ce('star', use_ce)} <b>Добро пожаловать!</b>"
        )
        welcome_photo = settings.get("welcome_photo_id", "").strip()

        if settings.get("show_profile_in_home", "1") == "1":
            u = await db.get_user(user_id)
            bonus_stars = int(u["bonus_stars"]) if u else 0
            refs_cnt = int(u["referrals_count"]) if u else 0
            profile_block = (
                f"{ce('id_card', use_ce)} Telegram ID: <code>{user_id}</code>\n"
                f"{ce('star', use_ce)} Бонусы: <b>{bonus_stars} ⭐️</b>\n"
                f"{ce('users', use_ce)} Рефералов: <b>{refs_cnt}</b>"
            )
            welcome_text = f"{welcome_text}\n\n{profile_block}"

        kb = build_main_menu_kb(
            show_paid_section=show_paid,
            is_admin=user_id in config.admin_ids,
            channel_url=channel_url,
            use_ce=use_ce,
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
        u = await db.get_user(user_id)
        user_bonus = int(u["bonus_stars"]) if u else 0
        bot_uname = await get_bot_username(bot) if user_id in config.admin_ids else ""

        if item.get("category_id"):
            sec = "shop" if item.get("is_paid") else "guides"
            back_cb = f"cat:{sec}:{item['category_id']}"
        else:
            back_cb = "nav:shop" if item.get("is_paid") else "nav:guides"

        card_text = format_item_card_text(item, settings, has_access, user_bonus=user_bonus)
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

        if not item.get("is_paid") and int(item.get("price_bonus_stars") or 0) <= 0:
            await db.grant_access(user_id, item["id"], access_type="free")
            await deliver_item_content(bot, chat_id, item)
            return True

        await show_item_card(event, bot, user_id, item)
        return True

    @router.callback_query(F.data.startswith("sub:check:"))
    async def cb_sub_check(
        call: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        is_sub, _ = await check_user_subscription(
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
        await notify_referrer_if_needed(bot, db, call.from_user.id)

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
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        categories = await db.get_categories(
            section=section, only_with_active_items=True
        )
        uncat_items = await db.get_catalog_items(
            is_paid=is_paid, uncategorized_only=True
        )

        if section == "guides":
            header = f"{ce('books', use_ce)} <b>Бесплатные гайды и база знаний</b>"
            empty_hint = (
                "Здесь пока нет опубликованных гайдов. Скоро добавим свежие материалы!"
            )
        else:
            header = f"{ce('cart', use_ce)} <b>Каталог товаров и доступов</b>"
            empty_hint = "Товары в каталоге сейчас пополняются. Загляните чуть позже!"

        if not categories and not uncat_items:
            text = f"{header}\n\n<i>{empty_hint}</i>"
        else:
            text = f"{header}\n\n{ce('point_down', use_ce)} Выберите нужную категорию или позицию:"

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
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        items = await db.get_catalog_items(is_paid=is_paid, category_id=cat_id)
        icon = ce("books" if section == "guides" else "bags", use_ce)
        text = (
            f"{icon} <b>{html.escape(category['title'])}</b>\n\n"
            f"{ce('point_down', use_ce)} Доступные материалы в разделе:"
        )
        if not items:
            text = f"{icon} <b>{html.escape(category['title'])}</b>\n\n<i>В этой категории пока пусто.</i>"

        kb = build_catalog_kb(
            section=section,
            categories=[],
            items=items,
            settings=settings,
            in_category=True,
        )
        await render_screen(call, text, kb)

    @router.callback_query(F.data == "nav:profile")
    async def cb_profile(call: CallbackQuery, bot: Bot) -> None:
        await call.answer()
        uid = call.from_user.id
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        u = await db.get_user(uid)
        owned = await db.get_user_items(uid)
        bot_uname = await get_bot_username(bot)
        ref_link = f"https://t.me/{bot_uname}?start=ref_{uid}"

        bonus_stars = int(u["bonus_stars"]) if u else 0
        refs_cnt = int(u["referrals_count"]) if u else 0
        orders_cnt = int(u["paid_orders_count"]) if u else 0
        uname_str = f"@{call.from_user.username}" if call.from_user.username else "—"

        text = (
            f"{ce('id_card', use_ce)} <b>Личный профиль</b>\n\n"
            f"▪ <b>Telegram ID:</b> <code>{uid}</code>\n"
            f"▪ <b>Username:</b> {html.escape(uname_str)}\n"
            f"▪ <b>Бонусный баланс:</b> <b>{bonus_stars}</b> {ce('star', use_ce)}\n"
            f"▪ <b>Приглашено друзей:</b> <b>{refs_cnt}</b> {ce('users', use_ce)}\n"
            f"▪ <b>Покупок в каталоге:</b> <b>{orders_cnt}</b>\n"
            f"▪ <b>Открыто материалов:</b> <b>{len(owned)}</b>\n\n"
            f"{ce('link', use_ce)} <b>Ваша реф. ссылка:</b>\n<code>{ref_link}</code>"
        )
        await render_screen(call, text, build_profile_kb(use_ce=use_ce))

    @router.callback_query(F.data == "nav:bonuses")
    async def cb_bonuses(call: CallbackQuery, bot: Bot) -> None:
        await call.answer()
        uid = call.from_user.id
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        u = await db.get_user(uid)
        bot_uname = await get_bot_username(bot)
        ref_link = f"https://t.me/{bot_uname}?start=ref_{uid}"

        bonus_stars = int(u["bonus_stars"]) if u else 0
        refs_cnt = int(u["referrals_count"]) if u else 0

        r_join = settings.get("ref_join_bonus", "1")
        r_first = settings.get("ref_first_buy_bonus", "15")
        r_rep = settings.get("ref_repeat_buy_bonus", "5")
        s_first = settings.get("self_first_buy_bonus", "20")
        s_rep = settings.get("self_repeat_buy_bonus", "5")
        banner_id = settings.get("bonus_banner_photo_id", "").strip()

        star_ic = ce("star", use_ce)
        text = (
            f"{ce('sparkle', use_ce)} <b>Бонусная система</b>\n"
            f"Приглашай друзей — получай звёзды!\n\n"
            f"{ce('bags', use_ce)} <b>Покупай сам</b>\n"
            f"▪ Первая покупка → <b>+{s_first}</b> {star_ic}\n"
            f"▪ Каждая следующая → <b>+{s_rep}</b> {star_ic}\n\n"
            f"{ce('users', use_ce)} <b>Приглашай друзей</b>\n"
            f"▪ Новый друг по ссылке → <b>+{r_join}</b> {star_ic}\n"
            f"▪ Его первая покупка → <b>+{r_first}</b> {star_ic}\n"
            f"▪ Его следующие покупки → <b>+{r_rep}</b> {star_ic}\n\n"
            f"{ce('coin', use_ce)} <b>Твои бонусы:</b> <b>{bonus_stars}</b> {star_ic} "
            f"(друзей: <b>{refs_cnt}</b>)\n\n"
            f"{ce('link', use_ce)} <b>Твоя ссылка для приглашений:</b>\n"
            f"<code>{ref_link}</code>"
        )
        await render_screen(
            call,
            text,
            build_bonus_system_kb(ref_link=ref_link, use_ce=use_ce),
            photo_id=banner_id,
        )

    @router.callback_query(F.data == "nav:exchange")
    async def cb_exchange(call: CallbackQuery) -> None:
        await call.answer()
        uid = call.from_user.id
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        u = await db.get_user(uid)
        bonus_stars = int(u["bonus_stars"]) if u else 0
        items = await db.get_bonus_exchange_items()

        header = (
            f"{ce('exchange', use_ce)} <b>Обмен бонусных звёзд</b>\n\n"
            f"{ce('coin', use_ce)} Ваш доступный баланс: <b>{bonus_stars}</b> {ce('star', use_ce)}\n\n"
        )
        if not items:
            text = (
                f"{header}"
                "<i>Сейчас список бонусных товаров пополняется. "
                "Приглашайте друзей и копите звёзды — скоро здесь появятся эксклюзивные материалы!</i>"
            )
        else:
            text = (
                f"{header}"
                f"{ce('point_down', use_ce)} Выберите товар, который хотите забрать за накопленные бонусные звёзды:"
            )

        await render_screen(
            call,
            text,
            build_exchange_kb(items=items, user_bonus=bonus_stars, use_ce=use_ce),
        )

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
        if item.get("is_paid") or int(item.get("price_bonus_stars") or 0) > 0:
            await call.answer("Этот материал находится в каталоге", show_alert=True)
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
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        items = await db.get_user_items(call.from_user.id)
        if not items:
            text = (
                f"{ce('gift', use_ce)} <b>Мои материалы и покупки</b>\n\n"
                "У вас пока нет открытых гайдов или покупок.\n"
                "Загляните в раздел <b>«📚 Гайды»</b> или <b>«🛒 Каталог»</b>!"
            )
        else:
            text = (
                f"{ce('gift', use_ce)} <b>Мои материалы ({len(items)})</b>\n\n"
                f"{ce('point_down', use_ce)} Нажмите на любой материал, чтобы открыть его снова:"
            )
        await render_screen(call, text, build_my_items_kb(items, use_ce=use_ce))

    @router.callback_query(F.data == "nav:info")
    async def cb_info(call: CallbackQuery) -> None:
        await call.answer()
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        info_text = settings.get("info_text", "ℹ️ Информация скоро появится.")
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
        settings = await db.get_all_settings()
        use_ce = settings.get("use_custom_emoji", "1") == "1"
        text = (
            f"{ce('chat', use_ce)} <b>Поддержка и сотрудничество</b>\n\n"
            "Напишите ваш вопрос, предложение или запрос одним сообщением "
            "(можно прикрепить фото или файл) — я сразу передам его автору:"
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
