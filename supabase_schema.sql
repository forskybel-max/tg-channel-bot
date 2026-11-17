-- Схема таблиц для Supabase (PostgreSQL)
-- Бот автоматически проверяет и создает все таблицы и колонки при запуске.

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    source_param TEXT DEFAULT '',
    referred_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    ref_rewarded BOOLEAN NOT NULL DEFAULT FALSE,
    bonus_stars INTEGER NOT NULL DEFAULT 0,
    referrals_count INTEGER NOT NULL DEFAULT 0,
    paid_orders_count INTEGER NOT NULL DEFAULT 0,
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT 'guides', -- 'guides' (бесплатные гайды) | 'shop' (каталог товаров)
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
    copy_snippet TEXT NOT NULL DEFAULT '',
    is_paid BOOLEAN NOT NULL DEFAULT FALSE,
    price_rub INTEGER NOT NULL DEFAULT 0,
    price_stars INTEGER NOT NULL DEFAULT 0,
    price_bonus_stars INTEGER NOT NULL DEFAULT 0,
    claims_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_items (
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    access_type TEXT NOT NULL DEFAULT 'free', -- 'free' | 'stars' | 'bonus' | 'manual' | 'admin'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    payment_method TEXT NOT NULL,           -- 'stars' | 'bonus' | 'manual'
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,                 -- 'XTR' | 'BONUS' | 'RUB'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'paid' | 'rejected'
    receipt_file_id TEXT NOT NULL DEFAULT '',
    receipt_file_type TEXT NOT NULL DEFAULT '',
    receipt_note TEXT NOT NULL DEFAULT '',
    reviewed_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bonus_transactions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    related_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by);
CREATE INDEX IF NOT EXISTS idx_items_category_id ON items(category_id);
CREATE INDEX IF NOT EXISTS idx_items_paid_active ON items(is_paid, is_active, sort_order);
CREATE INDEX IF NOT EXISTS idx_items_bonus_stars ON items(price_bonus_stars) WHERE is_active = TRUE AND price_bonus_stars > 0;
CREATE INDEX IF NOT EXISTS idx_user_items_item_id ON user_items(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_item_id ON orders(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bonus_tx_user_id ON bonus_transactions(user_id, created_at DESC);

ALTER TABLE bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE bonus_transactions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE bot_settings, users, categories, items, user_items, orders, bonus_transactions FROM anon, authenticated;
