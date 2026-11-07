import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в бот канала!</b>\n\n"
    "Здесь собраны бесплатные гайды, инструкции, подборки сервисов и закрытые материалы.\n\n"
    "👇 Выберите нужный раздел в меню ниже:"
)

DEFAULT_INFO_TEXT = (
    "ℹ️ <b>О проекте и навигация</b>\n\n"
    "Здесь регулярно выходят практические гайды, чек-листы и полезные материалы.\n\n"
    "• По вопросам рекламы и сотрудничества — нажмите кнопку <b>«💬 Связь с автором»</b> в главном меню."
)


@dataclass
class Config:
    bot_token: str
    admin_ids: list[int]
    database_url: str
    default_channel_id: str = ""
    default_channel_url: str = ""


def _parse_admin_ids(raw: str) -> list[int]:
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


def _normalize_db_url(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    database_url = _normalize_db_url(os.getenv("DATABASE_URL", ""))

    missing: list[str] = []
    if not bot_token or "your_bot_token" in bot_token:
        missing.append("BOT_TOKEN (токен нового бота от @BotFather)")
    if not admin_ids_raw or admin_ids_raw == "123456789":
        missing.append("ADMIN_IDS (ваш числовой Telegram ID, можно узнать у @userinfobot)")
    if not database_url or "YOUR-PASSWORD" in database_url:
        missing.append(
            "DATABASE_URL (строка подключения PostgreSQL из Supabase -> Connect -> Transaction/Session Pooler)"
        )

    if missing:
        bullet_list = "\n  - ".join(missing)
        raise ValueError(
            f"Не заполнены обязательные переменные в файле .env:\n  - {bullet_list}\n"
            "Скопируйте .env.example в .env и заполните значения."
        )

    return Config(
        bot_token=bot_token,
        admin_ids=_parse_admin_ids(admin_ids_raw),
        database_url=database_url,
        default_channel_id=os.getenv("CHANNEL_ID", "@neuro_admin_official").strip() or "@neuro_admin_official",
        default_channel_url=os.getenv("CHANNEL_URL", "https://t.me/neuro_admin_official").strip() or "https://t.me/neuro_admin_official",
    )
