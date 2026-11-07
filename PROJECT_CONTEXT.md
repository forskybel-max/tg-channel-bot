# Контекст проекта: Telegram Channel Guides & Shop Bot

## 1. Общее описание и статус
Публичный бот для Telegram-канала: выдача бесплатных гайдов за подписку, база знаний по категориям, обратная связь и встроенная витрина продаж (Telegram Stars + полуавтомат по реквизитам СБП/карта/USDT) с новыми цветными и копирующими инлайн-кнопками Bot API 2026.

* **Бот в Telegram:** `@neuro_admin_store_bot`
* **Локальная папка проекта:** `C:\Users\User\.gemini\antigravity\scratch\tg_channel_bot`
* **Локальное окружение Python:** `.venv` (`Python 3.12`, `Aiogram 3.31+`, `asyncpg`)
* **Локальные секреты:** `C:\Users\User\.gemini\antigravity\scratch\tg_channel_bot\.env` (в `.gitignore`)
* **GitHub репозиторий (приватный):** `https://github.com/forskybel-max/tg-channel-bot` (ветка `main`, включен `autoDeploy` на Render)
* **База данных (Supabase PostgreSQL):**
  * Project Name: `tg-channel-bot`
  * Project Ref / ID: `lbbaaazvopewqxkmwapf` (`us-west-1`)
  * Подключение через IPv4 Supavisor Pooler (`aws-0-us-west-1.pooler.supabase.com:6543`, роль `bot_backend`, `statement_cache_size=0`, включен RLS на всех таблицах).
* **Хостинг (Render Free Tier, Docker, Oregon):**
  * Dashboard: `https://dashboard.render.com/web/srv-dbnl34gu01pc73d2e3lg`
  * Service ID: `srv-dbnl34gu01pc73d2e3lg`
  * Public Healthcheck URL: `https://tg-channel-bot-wnj4.onrender.com/health`

---

## 2. Структура проекта
* `main.py` — точка входа: подключение пула PostgreSQL, автопроверка таблиц, настройка команд `/start` и `/admin`, запуск HTTP `/health` и self-ping `RENDER_EXTERNAL_URL`.
* `app/config.py` — чтение `.env` (`BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, `CHANNEL_ID`, `CHANNEL_URL`).
* `app/database.py` — слой PostgreSQL (`asyncpg`) для настроек, юзеров, категорий, материалов, доступов и заказов.
* `app/keyboards.py` — инлайн-клавиатуры с `ButtonStyle` (`primary`, `success`, `danger`), `CopyTextButton` и `DisabledButton`.
* `app/services/subscription.py` — проверка подписки на канал (`get_chat_member`).
* `app/services/delivery.py` — универсальная отправка гайдов/товаров (PDF, видео, фото, аудио, HTML-текст + кнопка копирования промпта/кода).
* `app/handlers/user.py` — пользовательская витрина, deep-links вида `?start=item_X`, раздел «Мои материалы» и тикеты поддержки.
* `app/handlers/payments.py` — автооплата `Telegram Stars (XTR)` и полуавтомат по реквизитам со сбором чеков.
* `app/handlers/admin.py` — полная админ-панель `/admin`: управление материалами, папками, чеками, настройками подписки и рассылкой по базе.
* `supabase_schema.sql` — SQL-схема всех таблиц, индексов и политик безопасности.

---

## 3. Важные нюансы
1. **Не запускать локально одновременно с Render:** пока сервис работает на Render, локальный запуск `start.bat` вызовет `TelegramConflictError` (два процесса читают один `BOT_TOKEN`).
2. **Деплой обновлений:** достаточно закоммитить изменения и сделать `git push origin main` — Render автоматически пересоберет контейнер.
