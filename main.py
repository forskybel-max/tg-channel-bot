import asyncio
import logging
import os
import sys

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.config import load_config
from app.database import Database
from app.handlers.admin import setup_admin_router
from app.handlers.payments import setup_payments_router
from app.handlers.user import setup_user_router


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def start_healthcheck_server(port: int) -> web.AppRunner:
    """HTTP Healthcheck для облачного деплоя (Render / Koyeb / Railway)."""
    async def handle_health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "tg_channel_bot"})

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.getLogger("main").info("Healthcheck HTTP-сервер запущен на порту %d", port)
    return runner


async def refresh_bot_profile_counter(bot: Bot, db: Database) -> None:
    """Обновляет счетчик участников в шапке профиля бота (Short Description)."""
    try:
        cnt = await db.get_total_users_count()
        formatted = f"{max(1, cnt):,}".replace(",", " ")
        short_desc = (
            f"👥 Участников: {formatted} • Бесплатные гайды и база материалов @neuro_admin_official"
        )
        await bot.set_my_short_description(short_description=short_desc[:120])
    except Exception:
        pass


async def keep_alive_task(bot: Bot, db: Database) -> None:
    """Периодический self-ping для бесплатного облака и обновление счетчика в профиле бота."""
    tick = 0
    while True:
        await asyncio.sleep(600)
        tick += 1
        external_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        if external_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{external_url}/health", timeout=10):
                        pass
            except Exception:
                pass
        if tick % 3 == 0:  # каждые 30 минут
            await refresh_bot_profile_counter(bot, db)


async def configure_bot_commands(bot: Bot, admin_ids: list[int]) -> None:
    user_cmds = [BotCommand(command="start", description="🏠 Главное меню и материалы")]
    admin_cmds = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="admin", description="⚙️ Админ-панель"),
    ]
    try:
        await bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
        for aid in admin_ids:
            try:
                await bot.set_my_commands(
                    admin_cmds, scope=BotCommandScopeChat(chat_id=aid)
                )
            except Exception:
                pass
    except Exception:
        pass


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("main")

    try:
        config = load_config()
    except ValueError as err:
        logger.error("\n%s", err)
        return

    db = Database(config.database_url)
    logger.info("Подключение к базе данных Supabase (PostgreSQL)...")
    await db.connect()
    await db.init_schema(
        default_channel_id=config.default_channel_id,
        default_channel_url=config.default_channel_url,
    )
    logger.info("База данных готова, таблицы проверены!")

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(setup_admin_router(config, db))
    dp.include_router(setup_payments_router(config, db))
    dp.include_router(setup_user_router(config, db))

    health_runner: web.AppRunner | None = None
    port_env = os.getenv("PORT", "").strip()
    if port_env.isdigit():
        health_runner = await start_healthcheck_server(int(port_env))

    await configure_bot_commands(bot, config.admin_ids)
    await refresh_bot_profile_counter(bot, db)
    ping_task = asyncio.create_task(keep_alive_task(bot, db))

    me = await bot.get_me()
    logger.info("====================================================")
    logger.info("БОТ ЗАПУЩЕН: @%s", me.username)
    logger.info("Админ-панель: /admin (доступна ID: %s)", config.admin_ids)
    logger.info("====================================================")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Остановка бота...")
        ping_task.cancel()
        if health_runner:
            await health_runner.cleanup()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
