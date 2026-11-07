import ssl
from typing import Any
from urllib.parse import urlparse
import asyncpg

from app.config import DEFAULT_INFO_TEXT, DEFAULT_WELCOME_TEXT

ALLOWED_ITEM_FIELDS = {
    "category_id",
    "title",
    "description",
    "cover_photo_id",
    "content_text",
    "file_id",
    "file_type",
    "copy_snippet",
    "is_paid",
    "price_rub",
    "price_stars",
    "is_active",
    "sort_order",
}


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        parsed = urlparse(self.database_url)
        host = (parsed.hostname or "").lower()
        is_local = host in ("localhost", "127.0.0.1", "::1")

        ssl_ctx: ssl.SSLContext | None = None
        if not is_local:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        # statement_cache_size=0 обязателен для корректной работы с Supabase Pooler (PgBouncer :6543)
        self.pool = await asyncpg.create_pool(
            dsn=self.database_url,
            min_size=1,
            max_size=10,
            statement_cache_size=0,
            command_timeout=30,
            ssl=ssl_ctx,
        )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized. Call await db.connect() first.")
        return self.pool

    async def init_schema(
        self, default_channel_id: str = "", default_channel_url: str = ""
    ) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
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
                    section TEXT NOT NULL DEFAULT 'guides',
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
                    file_type TEXT NOT NULL DEFAULT '',
                    copy_snippet TEXT NOT NULL DEFAULT '',
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
                    access_type TEXT NOT NULL DEFAULT 'free',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    payment_method TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
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
                """
            )

            defaults = {
                "welcome_text": DEFAULT_WELCOME_TEXT,
                "welcome_photo_id": "",
                "info_text": DEFAULT_INFO_TEXT,
                "require_sub": "1" if default_channel_id else "0",
                "channel_id": default_channel_id,
                "channel_url": default_channel_url,
                "show_paid_section": "0",
                "enable_stars": "1",
                "enable_manual_pay": "1",
                "payment_requisites": "",
                "payment_instructions": (
                    "Переведите точную сумму по реквизитам ниже, затем нажмите "
                    "<b>«✅ Я оплатил»</b> и отправьте скриншот чека."
                ),
            }
            for k, v in defaults.items():
                await conn.execute(
                    "INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    k,
                    v,
                )

    # --- Настройки ---

    async def get_setting(self, key: str, default: str = "") -> str:
        pool = self._require_pool()
        val = await pool.fetchval("SELECT value FROM bot_settings WHERE key = $1", key)
        return val if val is not None else default

    async def get_all_settings(self) -> dict[str, str]:
        pool = self._require_pool()
        rows = await pool.fetch("SELECT key, value FROM bot_settings")
        return {r["key"]: r["value"] for r in rows}

    async def set_setting(self, key: str, value: str) -> None:
        pool = self._require_pool()
        await pool.execute(
            """
            INSERT INTO bot_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            key,
            value,
        )

    # --- Пользователи и статистика ---

    async def upsert_user(
        self, user_id: int, username: str, full_name: str, source_param: str = ""
    ) -> bool:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO users (user_id, username, full_name, source_param, is_blocked, last_active_at)
            VALUES ($1, $2, $3, $4, FALSE, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                is_blocked = FALSE,
                last_active_at = NOW()
            RETURNING (xmax = 0) AS is_new
            """,
            user_id,
            username or "",
            full_name or "",
            source_param or "",
        )
        return bool(row["is_new"]) if row else False

    async def set_user_blocked(self, user_id: int, blocked: bool = True) -> None:
        pool = self._require_pool()
        await pool.execute(
            "UPDATE users SET is_blocked = $2 WHERE user_id = $1", user_id, blocked
        )

    async def get_all_active_user_ids(self) -> list[int]:
        pool = self._require_pool()
        rows = await pool.fetch(
            "SELECT user_id FROM users WHERE is_blocked = FALSE ORDER BY created_at ASC"
        )
        return [int(r["user_id"]) for r in rows]

    async def get_stats(self) -> dict[str, Any]:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            active_users = (
                await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE") or 0
            )
            new_24h = (
                await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours'"
                )
                or 0
            )
            new_7d = (
                await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'"
                )
                or 0
            )
            free_items = (
                await conn.fetchval("SELECT COUNT(*) FROM items WHERE is_paid = FALSE") or 0
            )
            paid_items = (
                await conn.fetchval("SELECT COUNT(*) FROM items WHERE is_paid = TRUE") or 0
            )
            total_claims = await conn.fetchval("SELECT COUNT(*) FROM user_items") or 0
            paid_orders = (
                await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'paid'") or 0
            )
            pending_orders = (
                await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'pending'") or 0
            )
            top_items = await conn.fetch(
                """
                SELECT id, title, claims_count, is_paid
                FROM items
                ORDER BY claims_count DESC, id DESC
                LIMIT 5
                """
            )
            return {
                "total_users": int(total_users),
                "active_users": int(active_users),
                "new_24h": int(new_24h),
                "new_7d": int(new_7d),
                "free_items": int(free_items),
                "paid_items": int(paid_items),
                "total_claims": int(total_claims),
                "paid_orders": int(paid_orders),
                "pending_orders": int(pending_orders),
                "top_items": [dict(r) for r in top_items],
            }

    # --- Категории ---

    async def create_category(self, title: str, section: str = "guides") -> int:
        pool = self._require_pool()
        cat_id = await pool.fetchval(
            "INSERT INTO categories (title, section) VALUES ($1, $2) RETURNING id",
            title.strip(),
            section,
        )
        return int(cat_id)

    async def get_categories(
        self, section: str | None = None, only_with_active_items: bool = False
    ) -> list[dict[str, Any]]:
        pool = self._require_pool()
        is_paid_filter = None
        if section == "guides":
            is_paid_filter = False
        elif section == "shop":
            is_paid_filter = True

        if section:
            rows = await pool.fetch(
                """
                SELECT c.*,
                       COUNT(i.id) FILTER (
                           WHERE i.is_active = TRUE AND ($2::boolean IS NULL OR i.is_paid = $2)
                       ) AS active_count
                FROM categories c
                LEFT JOIN items i ON i.category_id = c.id
                WHERE c.section = $1
                GROUP BY c.id
                ORDER BY c.sort_order ASC, c.id ASC
                """,
                section,
                is_paid_filter,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT c.*,
                       COUNT(i.id) FILTER (WHERE i.is_active = TRUE) AS active_count
                FROM categories c
                LEFT JOIN items i ON i.category_id = c.id
                GROUP BY c.id
                ORDER BY c.section ASC, c.sort_order ASC, c.id ASC
                """
            )

        result = [dict(r) for r in rows]
        if only_with_active_items:
            result = [r for r in result if int(r.get("active_count") or 0) > 0]
        return result

    async def get_category(self, cat_id: int) -> dict[str, Any] | None:
        pool = self._require_pool()
        row = await pool.fetchrow("SELECT * FROM categories WHERE id = $1", cat_id)
        return dict(row) if row else None

    async def delete_category(self, cat_id: int) -> None:
        pool = self._require_pool()
        await pool.execute("DELETE FROM categories WHERE id = $1", cat_id)

    # --- Материалы (Гайды и Товары) ---

    async def create_item(
        self,
        title: str,
        description: str = "",
        cover_photo_id: str = "",
        content_text: str = "",
        file_id: str = "",
        file_type: str = "",
        copy_snippet: str = "",
        category_id: int | None = None,
        is_paid: bool = False,
        price_rub: int = 0,
        price_stars: int = 0,
    ) -> int:
        pool = self._require_pool()
        item_id = await pool.fetchval(
            """
            INSERT INTO items (
                category_id, title, description, cover_photo_id,
                content_text, file_id, file_type, copy_snippet,
                is_paid, price_rub, price_stars, is_active
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, TRUE)
            RETURNING id
            """,
            category_id,
            title.strip(),
            description.strip(),
            cover_photo_id,
            content_text.strip(),
            file_id,
            file_type,
            copy_snippet.strip(),
            is_paid,
            max(0, int(price_rub)),
            max(0, int(price_stars)),
        )
        return int(item_id)

    async def update_item_field(self, item_id: int, field: str, value: Any) -> None:
        if field not in ALLOWED_ITEM_FIELDS:
            raise ValueError(f"Forbidden field update: {field}")
        pool = self._require_pool()
        await pool.execute(
            f"UPDATE items SET {field} = $1 WHERE id = $2",
            value,
            item_id,
        )

    async def get_item(self, item_id: int) -> dict[str, Any] | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            SELECT i.*, c.title AS category_title
            FROM items i
            LEFT JOIN categories c ON c.id = i.category_id
            WHERE i.id = $1
            """,
            item_id,
        )
        return dict(row) if row else None

    async def get_catalog_items(
        self,
        is_paid: bool,
        category_id: int | None = None,
        uncategorized_only: bool = False,
    ) -> list[dict[str, Any]]:
        pool = self._require_pool()
        if category_id is not None:
            rows = await pool.fetch(
                """
                SELECT * FROM items
                WHERE is_active = TRUE AND is_paid = $1 AND category_id = $2
                ORDER BY sort_order ASC, id DESC
                """,
                is_paid,
                category_id,
            )
        elif uncategorized_only:
            rows = await pool.fetch(
                """
                SELECT * FROM items
                WHERE is_active = TRUE AND is_paid = $1 AND category_id IS NULL
                ORDER BY sort_order ASC, id DESC
                """,
                is_paid,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT * FROM items
                WHERE is_active = TRUE AND is_paid = $1
                ORDER BY sort_order ASC, id DESC
                """,
                is_paid,
            )
        return [dict(r) for r in rows]

    async def get_all_items_admin(self) -> list[dict[str, Any]]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT i.*, c.title AS category_title
            FROM items i
            LEFT JOIN categories c ON c.id = i.category_id
            ORDER BY i.is_paid ASC, i.sort_order ASC, i.id DESC
            """
        )
        return [dict(r) for r in rows]

    async def delete_item(self, item_id: int) -> None:
        pool = self._require_pool()
        await pool.execute("DELETE FROM items WHERE id = $1", item_id)

    # --- Доступы пользователя ---

    async def has_access(self, user_id: int, item_id: int) -> bool:
        pool = self._require_pool()
        val = await pool.fetchval(
            "SELECT 1 FROM user_items WHERE user_id = $1 AND item_id = $2",
            user_id,
            item_id,
        )
        return val is not None

    async def grant_access(
        self, user_id: int, item_id: int, access_type: str = "free"
    ) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchval(
                    """
                    INSERT INTO user_items (user_id, item_id, access_type)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, item_id) DO NOTHING
                    RETURNING 1
                    """,
                    user_id,
                    item_id,
                    access_type,
                )
                if inserted:
                    await conn.execute(
                        "UPDATE items SET claims_count = claims_count + 1 WHERE id = $1",
                        item_id,
                    )
                    return True
                return False

    async def get_user_items(self, user_id: int) -> list[dict[str, Any]]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT i.*, ui.access_type, ui.created_at AS granted_at
            FROM user_items ui
            JOIN items i ON i.id = ui.item_id
            WHERE ui.user_id = $1
            ORDER BY ui.created_at DESC
            """,
            user_id,
        )
        return [dict(r) for r in rows]

    # --- Заказы (Stars и Полуавтомат) ---

    async def create_order(
        self,
        user_id: int,
        item_id: int,
        payment_method: str,
        amount: int,
        currency: str,
        status: str = "pending",
        receipt_file_id: str = "",
        receipt_file_type: str = "",
        receipt_note: str = "",
    ) -> int:
        pool = self._require_pool()
        order_id = await pool.fetchval(
            """
            INSERT INTO orders (
                user_id, item_id, payment_method, amount, currency,
                status, receipt_file_id, receipt_file_type, receipt_note
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            user_id,
            item_id,
            payment_method,
            int(amount),
            currency,
            status,
            receipt_file_id,
            receipt_file_type,
            receipt_note,
        )
        return int(order_id)

    async def get_order(self, order_id: int) -> dict[str, Any] | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            SELECT o.*, i.title AS item_title, u.username, u.full_name
            FROM orders o
            JOIN items i ON i.id = o.item_id
            JOIN users u ON u.user_id = o.user_id
            WHERE o.id = $1
            """,
            order_id,
        )
        return dict(row) if row else None

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        pool = self._require_pool()
        rows = await pool.fetch(
            """
            SELECT o.*, i.title AS item_title, u.username, u.full_name
            FROM orders o
            JOIN items i ON i.id = o.item_id
            JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'pending'
            ORDER BY o.created_at ASC
            """
        )
        return [dict(r) for r in rows]

    async def resolve_order(
        self, order_id: int, new_status: str, admin_id: int
    ) -> dict[str, Any] | None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE orders
                    SET status = $2, reviewed_by = $3, updated_at = NOW()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    order_id,
                    new_status,
                    admin_id,
                )
                if not row:
                    return None
                order = dict(row)
                if new_status == "paid":
                    inserted = await conn.fetchval(
                        """
                        INSERT INTO user_items (user_id, item_id, access_type)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, item_id) DO NOTHING
                        RETURNING 1
                        """,
                        order["user_id"],
                        order["item_id"],
                        order["payment_method"],
                    )
                    if inserted:
                        await conn.execute(
                            "UPDATE items SET claims_count = claims_count + 1 WHERE id = $1",
                            order["item_id"],
                        )
                return order
