-- Схема таблиц для Supabase (PostgreSQL)
-- Примечание: бот создает эти таблицы АВТОМАТИЧЕСКИ при первом запуске через DATABASE_URL!
-- Этот файл приложен для удобства просмотра структуры или ручного запуска в Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    source_param TEXT DEFAULT '',
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT 'guides', -- 'guides' (бесплатные гайды/база знаний) | 'shop' (платные продукты)
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cover_photo_id TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    file_id TEXT NOT NULL DEFAULT '',
    file_type TEXT NOT NULL DEFAULT '',     -- 'document' | 'video' | 'photo' | 'audio' | ''
    copy_snippet TEXT NOT NULL DEFAULT '',  -- Текст для кнопки быстрого копирования (промпт, код, ссылка)
    is_paid BOOLEAN NOT NULL DEFAULT FALSE,
    price_rub INTEGER NOT NULL DEFAULT 0,
    price_stars INTEGER NOT NULL DEFAULT 0,
    claims_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_items (
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    access_type TEXT NOT NULL DEFAULT 'free', -- 'free' | 'stars' | 'manual' | 'admin'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    payment_method TEXT NOT NULL,           -- 'stars' | 'manual'
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,                 -- 'XTR' | 'RUB'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'paid' | 'rejected'
    receipt_file_id TEXT NOT NULL DEFAULT '',
    receipt_file_type TEXT NOT NULL DEFAULT '',
    receipt_note TEXT NOT NULL DEFAULT '',
    reviewed_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_items_category_id ON items(category_id);
CREATE INDEX IF NOT EXISTS idx_items_paid_active ON items(is_paid, is_active, sort_order);
CREATE INDEX IF NOT EXISTS idx_user_items_item_id ON user_items(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_item_id ON orders(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at DESC);

ALTER TABLE bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE bot_settings, users, categories, items, user_items, orders FROM anon, authenticated;
