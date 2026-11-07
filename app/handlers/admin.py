import asyncio
import html
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import Config
from app.database import Database
from app.handlers.user import render_screen
from app.keyboards import (
    build_admin_item_manage_kb,
    build_admin_main_kb,
    build_admin_settings_kb,
    build_cancel_kb,
    build_order_review_kb,
)
from app.services.delivery import deliver_item_content

logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    # Создание материала
    new_title = State()
    new_description = State()
    new_content = State()
    new_prices = State()

    # Редактирование материала
    edit_item_field = State()
    edit_item_file = State()
    edit_item_cover = State()

    # Категории
    new_cat_title = State()

    # Настройки
    edit_setting_text = State()
    edit_setting_photo = State()

    # Рассылка
    broadcast_msg = State()
    broadcast_btn = State()

    # Ответ в поддержку
    reply_user = State()


def _extract_html(message: Message) -> str:
    if message.text or message.caption:
        try:
            return (message.html_text or "").strip()
        except Exception:
            return (message.text or message.caption or "").strip()
    return ""


def _extract_media(message: Message) -> tuple[str, str]:
    """Возвращает (file_id, file_type) из сообщения."""
    if message.document:
        return message.document.file_id, "document"
    if message.video:
        return message.video.file_id, "video"
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.audio:
        return message.audio.file_id, "audio"
    return "", ""


def setup_admin_router(config: Config, db: Database) -> Router:
    router = Router(name="admin")
    cached_bot_username = ""

    # Глобальный фильтр прав администратора на весь роутер
    router.message.filter(F.from_user.id.in_(config.admin_ids))
    router.callback_query.filter(F.from_user.id.in_(config.admin_ids))

    async def show_admin_home(event: Message | CallbackQuery) -> None:
        stats = await db.get_stats()
        text = (
            "⚙️ <b>Панель управления ботом</b>\n\n"
            f"👥 Пользователей: <b>{stats['total_users']}</b> (за 24ч: +{stats['new_24h']})\n"
            f"📘 Бесплатных гайдов: <b>{stats['free_items']}</b>\n"
            f"💎 Платных продуктов: <b>{stats['paid_items']}</b>\n"
            f"📥 Выдано материалов: <b>{stats['total_claims']}</b>\n"
            f"🧾 Ожидают проверки чеков: <b>{stats['pending_orders']}</b>"
        )
        await render_screen(
            event,
            text,
            build_admin_main_kb(pending_orders=stats["pending_orders"]),
        )

    async def show_admin_item(
        event: Message | CallbackQuery, bot: Bot, item_id: int
    ) -> None:
        item = await db.get_item(item_id)
        if not item:
            if isinstance(event, CallbackQuery):
                await event.answer("Материал не найден", show_alert=True)
            return

        nonlocal cached_bot_username
        if not cached_bot_username:
            me = await bot.get_me()
            cached_bot_username = me.username or ""
        bot_username = cached_bot_username
        deep_link = f"https://t.me/{bot_username}?start=item_{item['id']}"

        kind_str = "💎 Платный товар" if item.get("is_paid") else "📘 Бесплатный гайд"
        status_str = "🟢 Опубликован" if item.get("is_active") else "🔴 Скрыт"
        cat_str = html.escape(item.get("category_title") or "Без папки (в корне раздела)")
        file_str = f"✅ {item['file_type']}" if item.get("file_id") else "нет"
        cover_str = "✅ есть" if item.get("cover_photo_id") else "нет"
        copy_str = (
            f"<code>{html.escape(item['copy_snippet'][:40])}</code>"
            if item.get("copy_snippet")
            else "нет"
        )

        text = (
            f"🛠 <b>Материал #{item['id']}: {html.escape(item['title'])}</b>\n\n"
            f"• <b>Тип:</b> {kind_str}\n"
            f"• <b>Статус:</b> {status_str}\n"
            f"• <b>Категория:</b> {cat_str}\n"
            f"• <b>Цена:</b> {item.get('price_rub', 0)} ₽ / ⭐️ {item.get('price_stars', 0)} Stars\n"
            f"• <b>Файл внутри:</b> {file_str} | <b>Обложка:</b> {cover_str}\n"
            f"• <b>Кнопка-копирка:</b> {copy_str}\n"
            f"• <b>Получили / купили:</b> {item.get('claims_count', 0)} чел.\n\n"
            f"🔗 <b>Прямая ссылка для кнопки под постом:</b>\n"
            f"<code>{deep_link}</code>"
        )
        await render_screen(
            event,
            text,
            build_admin_item_manage_kb(item, bot_username=bot_username),
        )

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext) -> None:
        await state.clear()
        await show_admin_home(message)

    @router.callback_query(F.data == "adm:menu")
    async def cb_admin_menu(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        await show_admin_home(call)

    # ==========================================
    # СТАТИСТИКА
    # ==========================================

    @router.callback_query(F.data == "adm:stats")
    async def cb_stats(call: CallbackQuery) -> None:
        await call.answer()
        st = await db.get_stats()
        top_lines = []
        for idx, it in enumerate(st["top_items"], start=1):
            ic = "💎" if it["is_paid"] else "📘"
            top_lines.append(
                f"{idx}. {ic} {html.escape(it['title'])} — <b>{it['claims_count']}</b>"
            )
        top_block = "\n".join(top_lines) if top_lines else "<i>Пока нет выдач</i>"

        text = (
            "📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: <b>{st['total_users']}</b>\n"
            f"🟢 Активных (для рассылки): <b>{st['active_users']}</b>\n"
            f"🆕 Новых за 24 часа: <b>+{st['new_24h']}</b>\n"
            f"📅 Новых за 7 дней: <b>+{st['new_7d']}</b>\n\n"
            f"📥 Всего выдано материалов: <b>{st['total_claims']}</b>\n"
            f"💰 Оплаченных заказов: <b>{st['paid_orders']}</b>\n\n"
            f"🏆 <b>Топ материалов по скачиваниям:</b>\n{top_block}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:stats")],
                [InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")],
            ]
        )
        await render_screen(call, text, kb)

    # ==========================================
    # КАТЕГОРИИ (ПАПКИ)
    # ==========================================

    async def render_categories_admin(event: Message | CallbackQuery) -> None:
        cats = await db.get_categories()
        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="➕ Папка в «Гайды»",
                    callback_data="adm:cat_add:guides",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="➕ Папка в «Продукты»",
                    callback_data="adm:cat_add:shop",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        ]
        for c in cats:
            sec_badge = "📚" if c["section"] == "guides" else "🔥"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{sec_badge} {c['title']} ({c['active_count']})",
                        callback_data="adm:noop",
                    ),
                    InlineKeyboardButton(
                        text="🗑 Удалить",
                        callback_data=f"adm:cat_del:{c['id']}",
                        style=ButtonStyle.DANGER,
                    ),
                ]
            )
        rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")])

        text = (
            "📁 <b>Категории (папки каталога)</b>\n\n"
            "Категории необязательны: материалы без категории отображаются прямо в корне раздела.\n"
            "При удалении папки сами материалы не удаляются, а просто переходят в корень раздела."
        )
        await render_screen(event, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data == "adm:noop")
    async def cb_noop(call: CallbackQuery) -> None:
        await call.answer()

    @router.callback_query(F.data == "adm:cats")
    async def cb_cats(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        await render_categories_admin(call)

    @router.callback_query(F.data.startswith("adm:cat_add:"))
    async def cb_cat_add(call: CallbackQuery, state: FSMContext) -> None:
        section = (call.data or "").split(":")[-1]
        await call.answer()
        await state.set_state(AdminStates.new_cat_title)
        await state.update_data(cat_section=section)
        sec_name = "📚 Бесплатные гайды" if section == "guides" else "🔥 Продукты"
        await render_screen(
            call,
            f"📁 Введите название новой папки для раздела <b>«{sec_name}»</b>:",
            build_cancel_kb("adm:cats"),
        )

    @router.message(AdminStates.new_cat_title)
    async def process_new_cat_title(message: Message, state: FSMContext) -> None:
        title = (message.text or "").strip()
        if not title:
            await message.answer("Отправьте текстовое название категории.")
            return
        data = await state.get_data()
        section = data.get("cat_section", "guides")
        await state.clear()
        await db.create_category(title=title, section=section)
        await render_categories_admin(message)

    @router.callback_query(F.data.startswith("adm:cat_del:"))
    async def cb_cat_del(call: CallbackQuery) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if raw_id.isdigit():
            await db.delete_category(int(raw_id))
            await call.answer("Папка удалена")
        await render_categories_admin(call)

    # ==========================================
    # СОЗДАНИЕ И УПРАВЛЕНИЕ МАТЕРИАЛАМИ
    # ==========================================

    @router.callback_query(F.data == "adm:items")
    async def cb_items_list(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        items = await db.get_all_items_admin()

        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="➕ Добавить новый материал",
                    callback_data="adm:add_item",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
        for it in items[:40]:
            ic = "💎" if it["is_paid"] else "📘"
            st = "🟢" if it["is_active"] else "🔴"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{st} {ic} #{it['id']} {it['title']} ({it['claims_count']})"[:64],
                        callback_data=f"adm:item:{it['id']}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")])

        text = (
            f"📚 <b>Все материалы ({len(items)})</b>\n\n"
            "Нажмите на материал для настройки, получения ссылки в пост или смены цены:"
        )
        await render_screen(call, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data == "adm:add_item")
    async def cb_add_item_start(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📘 Бесплатный гайд / Инфо",
                        callback_data="adm:new_type:free",
                        style=ButtonStyle.SUCCESS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💎 Платный товар / Доступ",
                        callback_data="adm:new_type:paid",
                        style=ButtonStyle.PRIMARY,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✖️ Отмена",
                        callback_data="adm:menu",
                        style=ButtonStyle.DANGER,
                    )
                ],
            ]
        )
        await render_screen(
            call,
            "➕ <b>Новый материал</b>\n\nКакой формат создаём? (Позже тип можно переключить в 1 клик)",
            kb,
        )

    @router.callback_query(F.data.startswith("adm:new_type:"))
    async def cb_new_type(call: CallbackQuery, state: FSMContext) -> None:
        is_paid = (call.data or "").endswith(":paid")
        await call.answer()
        await state.set_state(AdminStates.new_title)
        await state.update_data(is_paid=is_paid)
        await render_screen(
            call,
            "✏️ <b>Шаг 1 из 3 — Название</b>\n\nВведите название гайда или товара:",
            build_cancel_kb("adm:menu"),
        )

    @router.message(AdminStates.new_title)
    async def process_new_title(message: Message, state: FSMContext) -> None:
        title = (message.text or "").strip()
        if not title:
            await message.answer("Пожалуйста, отправьте название текстом.")
            return
        await state.update_data(title=title)
        await state.set_state(AdminStates.new_description)
        await message.answer(
            "📝 <b>Шаг 2 из 3 — Описание на витрине</b>\n\n"
            "Отправьте описание карточки, которое увидит человек до открытия/покупки "
            "(поддерживается форматирование Telegram, либо отправьте <code>-</code>, чтобы пропустить):",
            parse_mode="HTML",
            reply_markup=build_cancel_kb("adm:menu"),
        )

    @router.message(AdminStates.new_description)
    async def process_new_desc(message: Message, state: FSMContext) -> None:
        raw = _extract_html(message)
        desc = "" if raw == "-" else raw
        await state.update_data(description=desc)
        await state.set_state(AdminStates.new_content)
        await message.answer(
            "🎁 <b>Шаг 3 из 3 — Начинка материала</b>\n\n"
            "Отправьте то, что бот выдаст пользователю:\n"
            "• PDF / ZIP / документ с подписью или без\n"
            "• Видео или фото\n"
            "• Или просто текст со ссылками (например, на Notion / закрытый чат / статью):",
            parse_mode="HTML",
            reply_markup=build_cancel_kb("adm:menu"),
        )

    @router.message(AdminStates.new_content)
    async def process_new_content(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        content_text = _extract_html(message)
        file_id, file_type = _extract_media(message)
        if not content_text and not file_id:
            await message.answer("Отправьте текст, ссылку или прикрепите файл/видео/фото.")
            return

        data = await state.get_data()
        await state.update_data(
            content_text=content_text, file_id=file_id, file_type=file_type
        )

        if data.get("is_paid"):
            await state.set_state(AdminStates.new_prices)
            await message.answer(
                "💳 <b>Укажите стоимость товара</b>\n\n"
                "Отправьте две цифры через пробел: <code>Цена_в_рублях Цена_в_Stars</code>\n"
                "Например: <code>990 500</code>\n"
                "• Если только рубли: <code>990 0</code>\n"
                "• Если только Stars: <code>0 500</code>\n"
                "• Если пока «Скоро в продаже»: <code>0 0</code>",
                parse_mode="HTML",
                reply_markup=build_cancel_kb("adm:menu"),
            )
            return

        await state.clear()
        item_id = await db.create_item(
            title=data["title"],
            description=data.get("description", ""),
            content_text=content_text,
            file_id=file_id,
            file_type=file_type,
            is_paid=False,
        )
        await show_admin_item(message, bot, item_id)

    @router.message(AdminStates.new_prices)
    async def process_new_prices(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        parts = (message.text or "").strip().split()
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            await message.answer(
                "Введите два целых числа через пробел, например: <code>990 500</code> или <code>0 0</code>",
                parse_mode="HTML",
            )
            return

        data = await state.get_data()
        await state.clear()
        item_id = await db.create_item(
            title=data["title"],
            description=data.get("description", ""),
            content_text=data.get("content_text", ""),
            file_id=data.get("file_id", ""),
            file_type=data.get("file_type", ""),
            is_paid=True,
            price_rub=int(parts[0]),
            price_stars=int(parts[1]),
        )
        await show_admin_item(message, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item:"))
    async def cb_item_manage(
        call: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        await state.clear()
        await call.answer()
        raw_id = (call.data or "").split(":")[-1]
        if raw_id.isdigit():
            await show_admin_item(call, bot, int(raw_id))

    @router.callback_query(F.data.startswith("adm:item_test:"))
    async def cb_item_test(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return
        item = await db.get_item(int(raw_id))
        if not item:
            await call.answer("Не найдено", show_alert=True)
            return
        await call.answer("Отправляю тестовую выдачу 👁")
        await deliver_item_content(bot, call.message.chat.id, item)

    @router.callback_query(F.data.startswith("adm:item_toggle_active:"))
    async def cb_item_toggle_active(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit():
            return
        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item:
            return
        new_val = not bool(item.get("is_active"))
        await db.update_item_field(item_id, "is_active", new_val)
        await call.answer("Опубликовано!" if new_val else "Скрыто из каталога")
        await show_admin_item(call, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_toggle_paid:"))
    async def cb_item_toggle_paid(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit():
            return
        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item:
            return
        new_val = not bool(item.get("is_paid"))
        await db.update_item_field(item_id, "is_paid", new_val)
        await db.update_item_field(item_id, "category_id", None)
        await call.answer(
            "Переведено в Платные товары (не забудьте указать цену!)"
            if new_val
            else "Переведено в Бесплатные гайды!"
        )
        await show_admin_item(call, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_edit:"))
    async def cb_item_edit_field(call: CallbackQuery, state: FSMContext) -> None:
        parts = (call.data or "").split(":")
        if len(parts) != 4 or not parts[2].isdigit():
            return
        item_id = int(parts[2])
        field = parts[3]

        prompts = {
            "title": "Введите новое название материала:",
            "description": "Отправьте новое описание карточки (или <code>-</code>, чтобы очистить):",
            "content_text": "Отправьте новый внутренний текст/ссылку материала (или <code>-</code>, чтобы очистить):",
            "price_rub": "Введите цену в рублях (целое число, например <code>990</code> или <code>0</code>):",
            "price_stars": "Введите цену в Telegram Stars (целое число, например <code>500</code> или <code>0</code>):",
            "copy_snippet": (
                "Отправьте текст (до 256 симв.) для синей кнопки быстрого копирования под материалом "
                "(например, готовый промпт или промокод; отправьте <code>-</code>, чтобы убрать кнопку):"
            ),
        }
        await call.answer()
        await state.set_state(AdminStates.edit_item_field)
        await state.update_data(edit_item_id=item_id, edit_field=field)
        await render_screen(
            call,
            prompts.get(field, "Введите новое значение:"),
            build_cancel_kb(f"adm:item:{item_id}"),
        )

    @router.message(AdminStates.edit_item_field)
    async def process_edit_item_field(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        item_id = int(data["edit_item_id"])
        field = data["edit_field"]

        if field in ("price_rub", "price_stars"):
            raw_num = (message.text or "").strip()
            if not raw_num.isdigit():
                await message.answer("Введите целое неотрицательное число (например, 0 или 990).")
                return
            val: Any = int(raw_num)
        elif field in ("description", "content_text"):
            txt = _extract_html(message)
            val = "" if txt == "-" else txt
        else:
            txt = (message.text or "").strip()
            if field == "title" and not txt:
                await message.answer("Название не может быть пустым.")
                return
            val = "" if txt == "-" else txt

        await state.clear()
        await db.update_item_field(item_id, field, val)
        await show_admin_item(message, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_file:"))
    async def cb_item_file(call: CallbackQuery, state: FSMContext) -> None:
        item_id = int((call.data or "").split(":")[-1])
        await call.answer()
        await state.set_state(AdminStates.edit_item_file)
        await state.update_data(edit_item_id=item_id)
        await render_screen(
            call,
            "📎 Отправьте новый файл (PDF/документ, видео, фото или аудио), который будет выдаваться пользователю, "
            "или отправьте <code>-</code>, чтобы удалить прикрепленный файл:",
            build_cancel_kb(f"adm:item:{item_id}"),
        )

    @router.message(AdminStates.edit_item_file)
    async def process_item_file(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        item_id = int(data["edit_item_id"])
        if (message.text or "").strip() == "-":
            await state.clear()
            await db.update_item_field(item_id, "file_id", "")
            await db.update_item_field(item_id, "file_type", "")
            await show_admin_item(message, bot, item_id)
            return

        file_id, file_type = _extract_media(message)
        if not file_id:
            await message.answer("Прикрепите документ, видео, фото или отправьте <code>-</code>.", parse_mode="HTML")
            return
        await state.clear()
        await db.update_item_field(item_id, "file_id", file_id)
        await db.update_item_field(item_id, "file_type", file_type)
        await show_admin_item(message, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_cover:"))
    async def cb_item_cover(call: CallbackQuery, state: FSMContext) -> None:
        item_id = int((call.data or "").split(":")[-1])
        await call.answer()
        await state.set_state(AdminStates.edit_item_cover)
        await state.update_data(edit_item_id=item_id)
        await render_screen(
            call,
            "🖼 Отправьте картинку (как фото) для обложки карточки товара/гайда на витрине, "
            "или отправьте <code>-</code>, чтобы убрать обложку:",
            build_cancel_kb(f"adm:item:{item_id}"),
        )

    @router.message(AdminStates.edit_item_cover)
    async def process_item_cover(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        item_id = int(data["edit_item_id"])
        if (message.text or "").strip() == "-":
            await state.clear()
            await db.update_item_field(item_id, "cover_photo_id", "")
            await show_admin_item(message, bot, item_id)
            return
        if not message.photo:
            await message.answer("Отправьте изображение именно как Фото (не файлом) или <code>-</code>.", parse_mode="HTML")
            return
        await state.clear()
        await db.update_item_field(item_id, "cover_photo_id", message.photo[-1].file_id)
        await show_admin_item(message, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_cat:"))
    async def cb_item_cat_choose(call: CallbackQuery) -> None:
        item_id = int((call.data or "").split(":")[-1])
        item = await db.get_item(item_id)
        if not item:
            return
        section = "shop" if item.get("is_paid") else "guides"
        cats = await db.get_categories(section=section)

        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="📂 Без папки (в корне раздела)",
                    callback_data=f"adm:item_setcat:{item_id}:0",
                )
            ]
        ]
        for c in cats:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"📁 {c['title']}",
                        callback_data=f"adm:item_setcat:{item_id}:{c['id']}",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm:item:{item_id}")]
        )
        await call.answer()
        await render_screen(
            call,
            "📁 Выберите папку для размещения материала:",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("adm:item_setcat:"))
    async def cb_item_setcat(call: CallbackQuery, bot: Bot) -> None:
        parts = (call.data or "").split(":")
        item_id = int(parts[2])
        cat_id = int(parts[3])
        await db.update_item_field(item_id, "category_id", cat_id if cat_id > 0 else None)
        await call.answer("Категория обновлена")
        await show_admin_item(call, bot, item_id)

    @router.callback_query(F.data.startswith("adm:item_del_ask:"))
    async def cb_item_del_ask(call: CallbackQuery) -> None:
        item_id = int((call.data or "").split(":")[-1])
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Да, удалить навсегда",
                        callback_data=f"adm:item_del_yes:{item_id}",
                        style=ButtonStyle.DANGER,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"adm:item:{item_id}",
                    )
                ],
            ]
        )
        await call.answer()
        await render_screen(call, f"⚠️ Точно удалить материал #{item_id}?", kb)

    @router.callback_query(F.data.startswith("adm:item_del_yes:"))
    async def cb_item_del_yes(call: CallbackQuery, state: FSMContext) -> None:
        item_id = int((call.data or "").split(":")[-1])
        await db.delete_item(item_id)
        await call.answer("Материал удален")
        await cb_items_list(call, state)

    # ==========================================
    # ЗАЯВКИ НА ОПЛАТУ (ПОЛУАВТОМАТ)
    # ==========================================

    @router.callback_query(F.data == "adm:orders")
    async def cb_orders_list(call: CallbackQuery) -> None:
        await call.answer()
        pending = await db.get_pending_orders()
        if not pending:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")]
                ]
            )
            await render_screen(
                call,
                "💳 <b>Заявки на оплату</b>\n\nСейчас нет неразобранных чеков — все чисто! ✅",
                kb,
            )
            return

        rows: list[list[InlineKeyboardButton]] = []
        for o in pending[:25]:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🧾 #{o['id']} • {o['item_title']} ({o['amount']} ₽)",
                        callback_data=f"adm:ord_view:{o['id']}",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")])
        await render_screen(
            call,
            f"💳 <b>Ожидают проверки ({len(pending)}):</b>\nНажмите на заявку, чтобы посмотреть чек:",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("adm:ord_view:"))
    async def cb_order_view(call: CallbackQuery, bot: Bot) -> None:
        order_id = int((call.data or "").split(":")[-1])
        order = await db.get_order(order_id)
        if not order or not call.message:
            await call.answer("Заявка не найдена", show_alert=True)
            return

        await call.answer()
        uname = f"@{order['username']}" if order.get("username") else "без @username"
        caption = (
            f"🧾 <b>Заявка #{order['id']}</b> ({order['status']})\n"
            f"Товар: <b>{html.escape(order['item_title'])}</b>\n"
            f"Сумма: <b>{order['amount']} {order['currency']}</b>\n"
            f"Покупатель: <b>{html.escape(order.get('full_name') or '')}</b> ({uname}, <code>{order['user_id']}</code>)"
        )
        if order.get("receipt_note"):
            caption += f"\nКомментарий: <i>{html.escape(order['receipt_note'][:400])}</i>"

        kb = (
            build_order_review_kb(order["id"], order["user_id"])
            if order["status"] == "pending"
            else InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ К заявкам", callback_data="adm:orders")]
                ]
            )
        )
        fid = order.get("receipt_file_id", "")
        ftype = order.get("receipt_file_type", "")
        if ftype == "photo" and fid:
            await bot.send_photo(
                call.message.chat.id, fid, caption=caption[:1024], parse_mode="HTML", reply_markup=kb
            )
        elif ftype == "document" and fid:
            await bot.send_document(
                call.message.chat.id, fid, caption=caption[:1024], parse_mode="HTML", reply_markup=kb
            )
        else:
            await render_screen(call, caption, kb)

    @router.callback_query(F.data.startswith("adm:ord_ok:"))
    async def cb_order_approve(call: CallbackQuery, bot: Bot) -> None:
        order_id = int((call.data or "").split(":")[-1])
        resolved = await db.resolve_order(order_id, "paid", call.from_user.id)
        if not resolved:
            await call.answer("Эта заявка уже была обработана ранее!", show_alert=True)
            return

        await call.answer("✅ Оплата подтверждена! Материал отправлен покупателю.")
        if call.message:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await call.message.answer(
                f"✅ Заказ <b>#{order_id}</b> подтвержден, доступ выдан!", parse_mode="HTML"
            )

        item = await db.get_item(resolved["item_id"])
        try:
            await bot.send_message(
                chat_id=resolved["user_id"],
                text="🎉 <b>Ваша оплата подтверждена!</b> Доступ к материалу открыт 👇",
                parse_mode="HTML",
            )
            if item:
                await deliver_item_content(bot, resolved["user_id"], item)
        except Exception as exc:
            logger.warning("Не удалось отправить купленный товар юзеру %s: %s", resolved["user_id"], exc)

    @router.callback_query(F.data.startswith("adm:ord_no:"))
    async def cb_order_reject(call: CallbackQuery, bot: Bot) -> None:
        order_id = int((call.data or "").split(":")[-1])
        resolved = await db.resolve_order(order_id, "rejected", call.from_user.id)
        if not resolved:
            await call.answer("Эта заявка уже была обработана ранее!", show_alert=True)
            return

        await call.answer("❌ Заявка отклонена")
        if call.message:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await call.message.answer(
                f"❌ Заказ <b>#{order_id}</b> отклонен.", parse_mode="HTML"
            )

        try:
            await bot.send_message(
                chat_id=resolved["user_id"],
                text=(
                    f"⚠️ <b>Заявка на оплату #{order_id} не была подтверждена.</b>\n"
                    "Если произошла ошибка, пожалуйста, напишите через кнопку «💬 Связь с автором»."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # ==========================================
    # НАСТРОЙКИ БОТА И ВИТРИНЫ
    # ==========================================

    async def show_settings_screen(event: Message | CallbackQuery) -> None:
        s = await db.get_all_settings()
        ch_id = html.escape(s.get("channel_id") or "не задан")
        ch_url = html.escape(s.get("channel_url") or "не задана")
        req = html.escape(s.get("payment_requisites") or "не заданы")
        w_photo = "установлена ✅" if s.get("welcome_photo_id") else "нет"

        text = (
            "⚙️ <b>Настройки бота, подписки и оплат</b>\n\n"
            f"• <b>Канал для проверки подписки:</b> <code>{ch_id}</code>\n"
            f"• <b>Ссылка на канал:</b> {ch_url}\n"
            f"• <b>Реквизиты полуавтомата:</b> <code>{req}</code>\n"
            f"• <b>Обложка /start:</b> {w_photo}\n\n"
            "<i>💡 Чтобы проверка подписки работала, добавьте этого бота в администраторы вашего канала (достаточно любых минимальных прав).</i>"
        )
        await render_screen(event, text, build_admin_settings_kb(s))

    @router.callback_query(F.data == "adm:settings")
    async def cb_settings(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        await show_settings_screen(call)

    @router.callback_query(F.data.startswith("adm:set_toggle:"))
    async def cb_set_toggle(call: CallbackQuery) -> None:
        key = (call.data or "").split(":")[-1]
        cur = await db.get_setting(key, "0")
        new_val = "0" if cur == "1" else "1"
        await db.set_setting(key, new_val)
        await call.answer("Настройка обновлена!")
        await show_settings_screen(call)

    @router.callback_query(F.data.startswith("adm:set_edit:"))
    async def cb_set_edit(call: CallbackQuery, state: FSMContext) -> None:
        key = (call.data or "").split(":")[-1]
        hints = {
            "channel_id": (
                "📢 <b>ID или @username канала</b>\n\n"
                "Отправьте <code>@username</code> канала, его ID вида <code>-100...</code> "
                "ИЛИ просто <b>перешлите сюда любой пост из вашего канала</b> — я определю ID автоматически!\n"
                "(Для очистки отправьте <code>-</code>)"
            ),
            "channel_url": (
                "🔗 <b>Ссылка на канал</b>\n\n"
                "Отправьте ссылку вида <code>https://t.me/...</code> (можно закрытую инвайт-ссылку):"
            ),
            "payment_requisites": (
                "🏦 <b>Реквизиты для перевода</b>\n\n"
                "Укажите номер карты / телефон СБП / USDT-кошелек (пользователи смогут скопировать его в 1 клик):"
            ),
            "payment_instructions": (
                "📝 <b>Инструкция на экране оплаты</b>\n\n"
                "Например: <i>«Переведите по СБП на Т-Банк (Иван И.) и нажмите кнопку Я оплатил»</i>:"
            ),
            "welcome_text": "👋 Отправьте новый приветственный текст для главного меню (/start):",
            "info_text": "ℹ️ Отправьте новый текст для раздела «О проекте»:",
        }
        await call.answer()
        await state.set_state(AdminStates.edit_setting_text)
        await state.update_data(setting_key=key)
        await render_screen(
            call,
            hints.get(key, "Введите новое значение:"),
            build_cancel_kb("adm:settings"),
        )

    @router.message(AdminStates.edit_setting_text)
    async def process_setting_text(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        key = data["setting_key"]

        if key == "channel_id" and message.forward_from_chat:
            val = str(message.forward_from_chat.id)
            if message.forward_from_chat.username and not await db.get_setting("channel_url"):
                await db.set_setting(
                    "channel_url", f"https://t.me/{message.forward_from_chat.username}"
                )
        elif key in ("welcome_text", "info_text", "payment_instructions"):
            raw = _extract_html(message)
            val = "" if raw == "-" else raw
        else:
            raw = (message.text or "").strip()
            val = "" if raw == "-" else raw

        await state.clear()
        await db.set_setting(key, val)
        await show_settings_screen(message)

    @router.callback_query(F.data.startswith("adm:set_photo:"))
    async def cb_set_photo(call: CallbackQuery, state: FSMContext) -> None:
        key = (call.data or "").split(":")[-1]
        await call.answer()
        await state.set_state(AdminStates.edit_setting_photo)
        await state.update_data(setting_key=key)
        await render_screen(
            call,
            "🖼 Отправьте картинку (как Фото) для баннера главного меню, или <code>-</code>, чтобы убрать картинку:",
            build_cancel_kb("adm:settings"),
        )

    @router.message(AdminStates.edit_setting_photo)
    async def process_setting_photo(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        key = data["setting_key"]
        if (message.text or "").strip() == "-":
            await state.clear()
            await db.set_setting(key, "")
            await show_settings_screen(message)
            return
        if not message.photo:
            await message.answer("Пожалуйста, отправьте фото или <code>-</code>.", parse_mode="HTML")
            return
        await state.clear()
        await db.set_setting(key, message.photo[-1].file_id)
        await show_settings_screen(message)

    # ==========================================
    # РАССЫЛКА ПО БАЗЕ ПОЛЬЗОВАТЕЛЕЙ
    # ==========================================

    @router.callback_query(F.data == "adm:broadcast")
    async def cb_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
        await call.answer()
        await state.set_state(AdminStates.broadcast_msg)
        await render_screen(
            call,
            "📢 <b>Создание рассылки по базе</b>\n\n"
            "Отправьте пост для рассылки (текст, фото с подписью, видео или документ — "
            "все форматирование и эмодзи сохранятся):",
            build_cancel_kb("adm:menu"),
        )

    @router.message(AdminStates.broadcast_msg)
    async def process_broadcast_msg(message: Message, state: FSMContext) -> None:
        await state.update_data(
            bc_chat_id=message.chat.id, bc_message_id=message.message_id
        )
        await state.set_state(AdminStates.broadcast_btn)
        await message.answer(
            "🔗 <b>Добавить кнопку под пост рассылки?</b>\n\n"
            "Отправьте в формате: <code>Текст кнопки | https://...</code>\n"
            "Или отправьте <code>-</code>, если кнопка не нужна:",
            parse_mode="HTML",
            reply_markup=build_cancel_kb("adm:menu"),
        )

    @router.message(AdminStates.broadcast_btn)
    async def process_broadcast_btn(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        raw = (message.text or "").strip()
        btn_markup: InlineKeyboardMarkup | None = None
        btn_text = ""
        btn_url = ""

        if raw != "-":
            if "|" not in raw:
                await message.answer(
                    "Используйте формат <code>Текст | https://...</code> или отправьте <code>-</code>.",
                    parse_mode="HTML",
                )
                return
            left, right = [p.strip() for p in raw.split("|", maxsplit=1)]
            if not left or not (right.startswith("http://") or right.startswith("https://") or right.startswith("tg://")):
                await message.answer("Ссылка должна начинаться с https://")
                return
            btn_text, btn_url = left, right
            btn_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=btn_text, url=btn_url, style=ButtonStyle.PRIMARY
                        )
                    ]
                ]
            )

        await state.update_data(bc_btn_text=btn_text, bc_btn_url=btn_url)
        data = await state.get_data()
        users = await db.get_all_active_user_ids()

        await message.answer("👁 <b>Предпросмотр вашей рассылки:</b>", parse_mode="HTML")
        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=data["bc_chat_id"],
            message_id=data["bc_message_id"],
            reply_markup=btn_markup,
        )

        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🚀 Отправить ({len(users)} чел.)",
                        callback_data="adm:bc_go",
                        style=ButtonStyle.SUCCESS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✖️ Отмена",
                        callback_data="adm:menu",
                        style=ButtonStyle.DANGER,
                    )
                ],
            ]
        )
        await message.answer(
            f"Готово к отправке по <b>{len(users)}</b> активным пользователям. Запускаем?",
            parse_mode="HTML",
            reply_markup=confirm_kb,
        )

    @router.callback_query(F.data == "adm:bc_go")
    async def cb_broadcast_go(
        call: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        await state.clear()
        if not data.get("bc_message_id") or not call.message:
            await call.answer("Сессия рассылки истекла", show_alert=True)
            return

        await call.answer("Рассылка запущена!")
        btn_markup: InlineKeyboardMarkup | None = None
        if data.get("bc_btn_text") and data.get("bc_btn_url"):
            btn_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=data["bc_btn_text"],
                            url=data["bc_btn_url"],
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            )

        user_ids = await db.get_all_active_user_ids()
        status_msg = await call.message.edit_text(
            f"⏳ Рассылка выполняется... (0 / {len(user_ids)})"
        )

        sent = 0
        blocked = 0
        errors = 0

        for uid in user_ids:
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=data["bc_chat_id"],
                    message_id=data["bc_message_id"],
                    reply_markup=btn_markup,
                )
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                try:
                    await bot.copy_message(
                        chat_id=uid,
                        from_chat_id=data["bc_chat_id"],
                        message_id=data["bc_message_id"],
                        reply_markup=btn_markup,
                    )
                    sent += 1
                except Exception:
                    errors += 1
            except TelegramForbiddenError:
                blocked += 1
                await db.set_user_blocked(uid, True)
            except Exception:
                errors += 1

            await asyncio.sleep(0.05)

        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"• Доставлено: <b>{sent}</b>\n"
            f"• Отписались / заблокировали бота: <b>{blocked}</b>\n"
            f"• Прочих ошибок: <b>{errors}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:menu")]
                ]
            ),
        )

    # ==========================================
    # ОТВЕТ ПОЛЬЗОВАТЕЛЮ В БОТЕ
    # ==========================================

    @router.callback_query(F.data.startswith("adm:reply:"))
    async def cb_reply_user(call: CallbackQuery, state: FSMContext) -> None:
        uid = int((call.data or "").split(":")[-1])
        await call.answer()
        await state.set_state(AdminStates.reply_user)
        await state.update_data(reply_uid=uid)
        if call.message:
            await call.message.answer(
                f"↩️ Отправьте ответ для пользователя <code>{uid}</code> (текст, фото или файл):",
                parse_mode="HTML",
                reply_markup=build_cancel_kb("adm:menu"),
            )

    @router.message(AdminStates.reply_user)
    async def process_reply_user(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        uid = data.get("reply_uid")
        await state.clear()
        if not uid:
            return

        try:
            await bot.send_message(
                chat_id=uid,
                text="💬 <b>Ответ от автора канала:</b>",
                parse_mode="HTML",
            )
            await message.copy_to(chat_id=uid)
            await message.answer("✅ Ответ доставлен пользователю!")
        except Exception as exc:
            await message.answer(f"⚠️ Не удалось доставить сообщение: {exc}")

    return router
