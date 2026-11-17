import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.config import Config
from app.database import Database
from app.emojis import ce
from app.handlers.user import SubscriptionGateMiddleware, render_screen
from app.keyboards import (
    build_cancel_kb,
    build_manual_pay_kb,
    build_order_review_kb,
)
from app.services.delivery import deliver_item_content

logger = logging.getLogger(__name__)


class PaymentStates(StatesGroup):
    waiting_receipt = State()


def _strip_html(raw: str) -> str:
    clean = re.sub(r"<[^>]+>", "", raw or "").strip()
    return clean or "Оплата цифрового материала"


async def notify_purchase_bonuses(bot: Bot, db: Database, buyer_id: int) -> None:
    """Начисляет бонусы за покупку рефереру и самому покупателю и рассылает уведомления."""
    res = await db.process_purchase_bonuses(buyer_id)
    if not res:
        return

    settings = await db.get_all_settings()
    use_ce = settings.get("use_custom_emoji", "1") == "1"

    buyer_bonus = int(res.get("buyer_bonus") or 0)
    if buyer_bonus > 0:
        try:
            await bot.send_message(
                chat_id=buyer_id,
                text=(
                    f"{ce('star', use_ce)} <b>Бонус за покупку!</b>\n"
                    f"Тебе начислено <b>+{buyer_bonus}</b> {ce('star', use_ce)} на бонусный баланс."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    referrer_id = res.get("referrer_id")
    ref_bonus = int(res.get("ref_bonus") or 0)
    if referrer_id and ref_bonus > 0:
        uname = res.get("buyer_username")
        if uname:
            buyer_label = f"@{html.escape(uname)}"
        else:
            bname = html.escape(res.get("buyer_name") or f"ID {buyer_id}")
            buyer_label = f"<b>{bname}</b>"

        action_str = (
            "за первую покупку" if res.get("is_first") else "за покупку"
        )
        ref_msg = (
            f"{ce('coin', use_ce)} Тебе начислено <b>{ref_bonus}</b> {ce('star', use_ce)} "
            f"{action_str} {buyer_label}"
        )
        try:
            await bot.send_message(
                chat_id=int(referrer_id),
                text=ref_msg,
                parse_mode="HTML",
            )
        except Exception:
            pass


def setup_payments_router(config: Config, db: Database) -> Router:
    router = Router(name="payments")
    router.callback_query.middleware(SubscriptionGateMiddleware(config=config, db=db))

    # ==========================================
    # 1. TELEGRAM STARS (XTR)
    # ==========================================

    @router.callback_query(F.data.startswith("pay:stars:"))
    async def cb_pay_stars(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return

        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item or not item.get("is_active"):
            await call.answer("Материал недоступен", show_alert=True)
            return

        if await db.has_access(call.from_user.id, item_id):
            await call.answer("У вас уже открыт доступ!", show_alert=True)
            await deliver_item_content(bot, call.message.chat.id, item)
            return

        enable_stars = await db.get_setting("enable_stars", "1")
        stars_amount = int(item.get("price_stars") or 0)
        if enable_stars != "1" or stars_amount <= 0:
            await call.answer(
                "Оплата через Telegram Stars недоступна для этого товара",
                show_alert=True,
            )
            return

        await call.answer()
        title = (item.get("title") or "Материал")[:32]
        desc = _strip_html(item.get("description") or item.get("title") or "")[:250]

        await bot.send_invoice(
            chat_id=call.message.chat.id,
            title=title,
            description=desc,
            payload=f"stars_item:{item_id}:{call.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars_amount)],
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"⭐️ Оплатить {stars_amount} Stars",
                            pay=True,
                            style=ButtonStyle.PRIMARY,
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="✖️ Отмена",
                            callback_data=f"item:view:{item_id}",
                            style=ButtonStyle.DANGER,
                        )
                    ],
                ]
            ),
        )

    @router.pre_checkout_query()
    async def on_pre_checkout(query: PreCheckoutQuery) -> None:
        payload = query.invoice_payload or ""
        if payload.startswith("stars_item:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                item = await db.get_item(int(parts[1]))
                if not item or not item.get("is_active"):
                    await query.answer(
                        ok=False, error_message="Этот товар сейчас снят с продажи."
                    )
                    return
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def on_successful_stars_payment(message: Message, bot: Bot) -> None:
        sp = message.successful_payment
        if not sp or not message.from_user:
            return

        payload = sp.invoice_payload or ""
        if not payload.startswith("stars_item:"):
            return

        parts = payload.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            return

        item_id = int(parts[1])
        user = message.from_user
        item = await db.get_item(item_id)

        order_id = await db.create_order(
            user_id=user.id,
            item_id=item_id,
            payment_method="stars",
            amount=sp.total_amount,
            currency=sp.currency,
            status="paid",
            receipt_note=sp.telegram_payment_charge_id,
        )
        await db.grant_access(user.id, item_id, access_type="stars")

        await message.answer(
            "✅ <b>Оплата прошла успешно!</b> Спасибо за покупку — ваш материал ниже 👇",
            parse_mode="HTML",
        )
        if item:
            await deliver_item_content(bot, message.chat.id, item)

        await notify_purchase_bonuses(bot, db, user.id)

        uname = f"@{user.username}" if user.username else "без @username"
        item_title = html.escape(item["title"]) if item else f"#{item_id}"
        notify_text = (
            f"💰 <b>Новая продажа за Telegram Stars!</b>\n"
            f"Заказ: <code>#{order_id}</code>\n"
            f"Товар: <b>{item_title}</b>\n"
            f"Сумма: <b>⭐️ {sp.total_amount} XTR</b>\n"
            f"Покупатель: <b>{html.escape(user.full_name)}</b> ({uname}, <code>{user.id}</code>)"
        )
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(admin_id, notify_text, parse_mode="HTML")
            except Exception:
                pass

    # ==========================================
    # 2. ПОКУПКА ЗА БОНУСНЫЕ ЗВЁЗДЫ (ОБМЕН БОНУСОВ)
    # ==========================================

    @router.callback_query(F.data.startswith("pay:bonus:"))
    async def cb_pay_bonus(call: CallbackQuery, bot: Bot) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return

        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item or not item.get("is_active"):
            await call.answer("Материал недоступен", show_alert=True)
            return

        ok, status = await db.spend_bonus_for_item(call.from_user.id, item_id)
        if not ok:
            if status == "already_owned":
                await call.answer("У вас уже открыт доступ!", show_alert=True)
                await deliver_item_content(bot, call.message.chat.id, item)
                return
            if status.startswith("insufficient:"):
                _, bal, cost = status.split(":")
                await call.answer(
                    f"❌ Недостаточно бонусных звёзд!\nВаш баланс: {bal} ⭐️, нужно: {cost} ⭐️.\nПриглашайте друзей в разделе «Бонусная система»!",
                    show_alert=True,
                )
                return
            await call.answer("Этот товар нельзя обменять за бонусы", show_alert=True)
            return

        await call.answer("🎉 Бонусы обменяны! Отправляю материал...")
        cost = int(item.get("price_bonus_stars") or 0)
        await call.message.answer(
            f"🎁 <b>Обмен успешно выполнен!</b> Списано <b>{cost} ⭐️</b> с бонусного баланса.",
            parse_mode="HTML",
        )
        await deliver_item_content(bot, call.message.chat.id, item)

        user = call.from_user
        uname = f"@{user.username}" if user.username else "без @username"
        notify_text = (
            f"🎁 <b>Обмен бонусных звёзд!</b>\n"
            f"Товар: <b>{html.escape(item['title'])}</b>\n"
            f"Списано бонусов: <b>{cost} ⭐️</b>\n"
            f"Пользователь: <b>{html.escape(user.full_name)}</b> ({uname}, <code>{user.id}</code>)"
        )
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(admin_id, notify_text, parse_mode="HTML")
            except Exception:
                pass

    # ==========================================
    # 3. ПОЛУАВТОМАТ ПО РЕКВИЗИТАМ (СБП / КАРТА / КРИПТА)
    # ==========================================

    @router.callback_query(F.data.startswith("pay:manual:"))
    async def cb_pay_manual(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        await state.clear()
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit() or not call.message:
            await call.answer()
            return

        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item or not item.get("is_active"):
            await call.answer("Материал недоступен", show_alert=True)
            return

        if await db.has_access(call.from_user.id, item_id):
            await call.answer("У вас уже открыт доступ!", show_alert=True)
            await deliver_item_content(bot, call.message.chat.id, item)
            return

        settings = await db.get_all_settings()
        price_rub = int(item.get("price_rub") or 0)
        requisites = settings.get("payment_requisites", "").strip()
        instructions = settings.get("payment_instructions", "").strip()

        if settings.get("enable_manual_pay", "0") != "1" or price_rub <= 0:
            await call.answer("Этот способ оплаты сейчас отключен", show_alert=True)
            return

        if not requisites:
            await call.answer(
                "Реквизиты еще не заполнены администратором. Напишите в поддержку.",
                show_alert=True,
            )
            return

        await call.answer()
        text = (
            f"💳 <b>Оплата материала: «{html.escape(item['title'])}»</b>\n\n"
            f"Сумма к оплате: <b>{price_rub} ₽</b>\n"
            f"Реквизиты: <code>{html.escape(requisites)}</code>\n\n"
            f"{instructions}"
        )
        await render_screen(
            call,
            text,
            build_manual_pay_kb(item_id=item_id, requisites=requisites),
        )

    @router.callback_query(F.data.startswith("pay:manual_proof:"))
    async def cb_pay_manual_proof(call: CallbackQuery, state: FSMContext) -> None:
        raw_id = (call.data or "").split(":")[-1]
        if not raw_id.isdigit():
            await call.answer()
            return

        item_id = int(raw_id)
        item = await db.get_item(item_id)
        if not item:
            await call.answer("Товар не найден", show_alert=True)
            return

        await call.answer()
        await state.set_state(PaymentStates.waiting_receipt)
        await state.update_data(pay_item_id=item_id)

        text = (
            f"🧾 <b>Подтверждение оплаты — «{html.escape(item['title'])}»</b>\n\n"
            "Отправьте сюда <b>скриншот / PDF-чек</b> перевода или напишите комментарий "
            "(время перевода / имя отправителя):"
        )
        await render_screen(call, text, build_cancel_kb(f"pay:manual:{item_id}"))

    @router.message(PaymentStates.waiting_receipt)
    async def process_manual_receipt(
        message: Message, state: FSMContext, bot: Bot
    ) -> None:
        data = await state.get_data()
        item_id = data.get("pay_item_id")
        user = message.from_user
        if not item_id or not user:
            await state.clear()
            return

        item = await db.get_item(int(item_id))
        if not item:
            await state.clear()
            await message.answer("Товар не найден.")
            return

        file_id = ""
        file_type = ""
        note = (message.caption or message.text or "").strip()

        if message.photo:
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif message.document:
            file_id = message.document.file_id
            file_type = "document"
        elif note:
            file_type = "text"
        else:
            await message.answer(
                "Пожалуйста, отправьте скриншот чека (фото/файл) или текстовое сообщение с деталями перевода."
            )
            return

        await state.clear()
        price_rub = int(item.get("price_rub") or 0)
        order_id = await db.create_order(
            user_id=user.id,
            item_id=item["id"],
            payment_method="manual",
            amount=price_rub,
            currency="RUB",
            status="pending",
            receipt_file_id=file_id,
            receipt_file_type=file_type,
            receipt_note=note,
        )

        await message.answer(
            f"⏳ <b>Заявка #{order_id} отправлена на проверку!</b>\n\n"
            "Как только администратор подтвердит перевод, бот сразу же пришлет вам материал сюда в чат.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏠 В главное меню",
                            callback_data="nav:home",
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            ),
        )

        uname = f"@{user.username}" if user.username else "без @username"
        admin_caption = (
            f"🧾 <b>Заявка на оплату #{order_id}</b>\n"
            f"Товар: <b>{html.escape(item['title'])}</b>\n"
            f"Сумма: <b>{price_rub} ₽</b>\n"
            f"Покупатель: <b>{html.escape(user.full_name)}</b> ({uname}, <code>{user.id}</code>)"
        )
        if note:
            admin_caption += f"\nКомментарий: <i>{html.escape(note[:400])}</i>"

        review_kb = build_order_review_kb(order_id=order_id, user_id=user.id)
        for admin_id in config.admin_ids:
            try:
                if file_type == "photo" and file_id:
                    await bot.send_photo(
                        chat_id=admin_id,
                        photo=file_id,
                        caption=admin_caption[:1024],
                        parse_mode="HTML",
                        reply_markup=review_kb,
                    )
                elif file_type == "document" and file_id:
                    await bot.send_document(
                        chat_id=admin_id,
                        document=file_id,
                        caption=admin_caption[:1024],
                        parse_mode="HTML",
                        reply_markup=review_kb,
                    )
                else:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_caption,
                        parse_mode="HTML",
                        reply_markup=review_kb,
                    )
            except Exception as exc:
                logger.warning(
                    "Ошибка отправки заявки #%s админу %s: %s", order_id, admin_id, exc
                )

    return router
