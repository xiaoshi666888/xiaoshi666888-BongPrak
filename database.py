import json
import os
import secrets
import string
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

ORDER_STATUSES = (
    "pending",
    "pending_preorder",
    "awaiting_payment",
    "completed",
    "cancelled",
)
QUEUE_STATUSES = ("waiting", "ordering", "ready", "done", "cancelled")
MINUTES_PER_PARTY = 8


def get_db_connection():
    """Return a psycopg2 connection using the DATABASE_URL DSN."""
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


# Backward-compatible alias
get_connection = get_db_connection


def _cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _table_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return {row["column_name"] for row in cur.fetchall()}


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return cur.fetchone() is not None


def init_db():
    conn = get_db_connection()
    try:
        cur = _cursor(conn)

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_settings (
                id SERIAL PRIMARY KEY,
                name_en TEXT NOT NULL,
                name_km TEXT,
                name_zh TEXT,
                shop_name TEXT,
                logo_url TEXT,
                primary_color TEXT NOT NULL,
                background_color TEXT,
                background_image_url TEXT,
                khqr_url TEXT,
                current_festival_id INTEGER,
                group_invite_link TEXT
            )
            """
        )
        cur.execute(
            """
            INSERT INTO shop_settings
                (id, name_en, name_km, name_zh, logo_url, primary_color, background_color)
            VALUES (1, 'My Shop', 'ហាងរបស់ខ្ញុំ', '我的店铺', NULL, '#FF5722', '#FFFFFF')
            ON CONFLICT (id) DO NOTHING
            """
        )

        columns = _table_columns(cur, "shop_settings")
        for col, default in (
            ("name_en", "'My Shop'"),
            ("name_km", "NULL"),
            ("name_zh", "NULL"),
            ("shop_name", "NULL"),
            ("logo_url", "NULL"),
            ("primary_color", "'#FF5722'"),
            ("background_color", "'#FFFFFF'"),
            ("background_image_url", "NULL"),
            ("khqr_url", "NULL"),
            ("current_festival_id", "NULL"),
            ("group_invite_link", "NULL"),
        ):
            if col not in columns:
                col_type = "INTEGER" if col == "current_festival_id" else "TEXT"
                cur.execute(
                    f"ALTER TABLE shop_settings ADD COLUMN {col} {col_type} DEFAULT {default}"
                )

        if "shop_name" in columns or "shop_name" in _table_columns(cur, "shop_settings"):
            cur.execute(
                """
                UPDATE shop_settings
                SET name_en = COALESCE(NULLIF(name_en, ''), shop_name, 'My Shop'),
                    name_km = COALESCE(NULLIF(name_km, ''), 'ហាងរបស់ខ្ញុំ'),
                    name_zh = COALESCE(NULLIF(name_zh, ''), '我的店铺')
                WHERE id = 1
                """
            )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS menu_items (
                id SERIAL PRIMARY KEY,
                shop_id INTEGER DEFAULT 1,
                category TEXT,
                name_en TEXT,
                name_km TEXT,
                name_zh TEXT,
                price REAL,
                image_url TEXT,
                is_vegetarian INTEGER DEFAULT 0
            )
            """
        )
        menu_columns = _table_columns(cur, "menu_items")
        if "is_vegetarian" not in menu_columns:
            cur.execute(
                "ALTER TABLE menu_items ADD COLUMN is_vegetarian INTEGER DEFAULT 0"
            )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS festivals (
                id SERIAL PRIMARY KEY,
                name_en TEXT NOT NULL,
                name_km TEXT,
                name_zh TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                discount_percent REAL DEFAULT 0,
                is_vegetarian INTEGER DEFAULT 0
            )
            """
        )
        cur.execute("SELECT COUNT(*) AS cnt FROM festivals")
        festival_count = cur.fetchone()["cnt"]
        if festival_count == 0:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO festivals
                    (name_en, name_km, name_zh, start_date, end_date,
                     discount_percent, is_vegetarian)
                VALUES %s
                """,
                [
                    (
                        "Khmer New Year",
                        "ចូលឆ្នាំខ្មែរ",
                        "高棉新年",
                        "2026-04-13",
                        "2026-04-16",
                        10.0,
                        0,
                    ),
                    (
                        "Pchum Ben",
                        "បុណ្យភ្ជុំបិណ្ឌ",
                        "亡人节",
                        "2026-09-25",
                        "2026-09-27",
                        5.0,
                        1,
                    ),
                    (
                        "Water Festival",
                        "បុណ្យអុំទូក",
                        "送水节",
                        "2026-11-14",
                        "2026-11-16",
                        10.0,
                        0,
                    ),
                ],
            )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                shop_id INTEGER DEFAULT 1,
                customer_id INTEGER,
                customer_name TEXT,
                items TEXT,
                total REAL,
                status TEXT DEFAULT 'pending',
                order_type TEXT DEFAULT 'takeaway',
                payment_image_url TEXT,
                payment_amount REAL,
                customer_language TEXT DEFAULT 'en',
                coupon_code TEXT,
                discount_amount REAL DEFAULT 0,
                queue_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        order_columns = _table_columns(cur, "orders")
        for col, ddl in (
            ("payment_image_url", "TEXT"),
            ("payment_amount", "REAL"),
            ("customer_language", "TEXT DEFAULT 'en'"),
            ("coupon_code", "TEXT"),
            ("discount_amount", "REAL DEFAULT 0"),
            ("order_type", "TEXT DEFAULT 'takeaway'"),
            ("queue_id", "INTEGER"),
        ):
            if col not in order_columns:
                cur.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")

        cur.execute(
            "UPDATE orders SET status = 'completed' WHERE status IN ('paid', 'confirmed')"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS queue (
                id SERIAL PRIMARY KEY,
                shop_id INTEGER DEFAULT 1,
                user_id INTEGER NOT NULL,
                queue_number INTEGER NOT NULL,
                party_size INTEGER NOT NULL,
                status TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                value REAL NOT NULL,
                min_order REAL DEFAULT 0,
                shop_id INTEGER DEFAULT 1,
                usage_limit INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                expires_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_coupons (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                coupon_id INTEGER NOT NULL,
                used INTEGER DEFAULT 0,
                UNIQUE(user_id, coupon_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                reward_given INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(referred_id)
            )
            """
        )

        # Seed WELCOME5 if missing
        cur.execute(
            """
            INSERT INTO coupons
                (code, type, value, min_order, shop_id, usage_limit, used_count, expires_at)
            VALUES ('WELCOME5', 'fixed', 5.0, 0, 1, 999999, 0, NULL)
            ON CONFLICT (code) DO NOTHING
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                points INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        customer_cols = _table_columns(cur, "customers")
        if "points" not in customer_cols:
            cur.execute(
                "ALTER TABLE customers ADD COLUMN points INTEGER DEFAULT 0"
            )
        if "first_name" not in customer_cols:
            cur.execute("ALTER TABLE customers ADD COLUMN first_name TEXT")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                image_url TEXT,
                is_featured INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, user_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tiktok_submissions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                order_id INTEGER,
                video_url TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                reward_given INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.commit()
    finally:
        conn.close()


def migrate_legacy_public_urls(new_base_url: str, legacy_hosts: tuple[str, ...] | list[str]) -> int:
    """Rewrite stored absolute URLs that still point at old public hosts."""
    new_base = (new_base_url or "").rstrip("/")
    if not new_base:
        return 0
    updated = 0
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        jobs = [
            ("shop_settings", ("logo_url", "background_image_url", "khqr_url", "group_invite_link")),
            ("menu_items", ("image_url",)),
            ("reviews", ("image_url",)),
            ("orders", ("payment_image_url",)),
        ]
        for table, columns in jobs:
            if not _table_exists(cur, table):
                continue
            table_cols = _table_columns(cur, table)
            for col in columns:
                if col not in table_cols:
                    continue
                cur.execute(
                    f"SELECT id, {col} AS url FROM {table} WHERE {col} IS NOT NULL AND {col} != ''"
                )
                rows = cur.fetchall()
                for row in rows:
                    url = row["url"] or ""
                    if not any(host in url for host in legacy_hosts):
                        continue
                    marker = None
                    for m in ("/static/", "/webapp/"):
                        idx = url.find(m)
                        if idx >= 0:
                            marker = url[idx:]
                            break
                    if not marker:
                        continue
                    new_url = f"{new_base}{marker}"
                    if new_url == url:
                        continue
                    cur.execute(
                        f"UPDATE {table} SET {col} = %s WHERE id = %s",
                        (new_url, row["id"]),
                    )
                    updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated


def backfill_missing_menu_images() -> int:
    """Copy image_url from another item with the same English name when missing."""
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT id, name_en, image_url FROM menu_items")
        rows = cur.fetchall()
        by_name: dict[str, str] = {}
        for row in rows:
            name = (row["name_en"] or "").strip().lower()
            url = (row["image_url"] or "").strip()
            if name and url:
                by_name[name] = url

        updated = 0
        for row in rows:
            current = (row["image_url"] or "").strip()
            if current:
                continue
            name = (row["name_en"] or "").strip().lower()
            donor = by_name.get(name)
            if not donor:
                continue
            cur.execute(
                "UPDATE menu_items SET image_url = %s WHERE id = %s",
                (donor, row["id"]),
            )
            updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def get_shop_settings(shop_id: int):
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, name_en, name_km, name_zh, logo_url, primary_color,
                   background_color, background_image_url, khqr_url,
                   current_festival_id, group_invite_link
            FROM shop_settings WHERE id = %s
            """,
            (shop_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_shop_settings(shop_id: int, **fields) -> bool:
    allowed = {
        "name_en",
        "name_km",
        "name_zh",
        "logo_url",
        "primary_color",
        "background_color",
        "background_image_url",
        "khqr_url",
        "current_festival_id",
        "group_invite_link",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{key} = %s" for key in updates)
    values = list(updates.values()) + [shop_id]

    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE shop_settings SET {set_clause} WHERE id = %s",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_menu_item(
    shop_id: int,
    category: str,
    name_en: str,
    name_km: str,
    name_zh: str,
    price: float,
    image_url: str | None = None,
    is_vegetarian: int = 0,
) -> dict:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            INSERT INTO menu_items
                (shop_id, category, name_en, name_km, name_zh, price, image_url,
                 is_vegetarian)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                shop_id,
                category,
                name_en,
                name_km,
                name_zh,
                price,
                image_url,
                int(bool(is_vegetarian)),
            ),
        )
        item_id = cur.fetchone()["id"]
        conn.commit()
        cur.execute(
            """
            SELECT id, shop_id, category, name_en, name_km, name_zh, price,
                   image_url, is_vegetarian
            FROM menu_items WHERE id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
        return dict(row)
    finally:
        conn.close()


def get_menu_items(shop_id: int) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, shop_id, category, name_en, name_km, name_zh, price,
                   image_url, is_vegetarian
            FROM menu_items
            WHERE shop_id = %s
            ORDER BY LOWER(category), id
            """,
            (shop_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_festivals() -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, name_en, name_km, name_zh, start_date, end_date,
                   discount_percent, is_vegetarian
            FROM festivals
            ORDER BY start_date, id
            """
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_festival(festival_id: int | None) -> dict | None:
    if not festival_id:
        return None
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, name_en, name_km, name_zh, start_date, end_date,
                   discount_percent, is_vegetarian
            FROM festivals WHERE id = %s
            """,
            (int(festival_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_festival(shop_id: int = 1) -> dict | None:
    shop = get_shop_settings(shop_id)
    if not shop:
        return None
    return get_festival(shop.get("current_festival_id"))


def set_active_festival(shop_id: int, festival_id: int | None) -> dict | None:
    update_shop_settings(shop_id, current_festival_id=festival_id)
    return get_active_festival(shop_id)


def create_order(
    shop_id: int,
    items_json: str,
    total: float,
    customer_id: int | None = None,
    customer_name: str | None = None,
    customer_language: str | None = "en",
    coupon_code: str | None = None,
    discount_amount: float = 0,
    order_type: str = "takeaway",
    queue_id: int | None = None,
    status: str = "pending",
) -> dict:
    lang = customer_language if customer_language in ("en", "km", "zh") else "en"
    order_type = (order_type or "takeaway").strip().lower()
    if order_type not in ("takeaway", "dinein"):
        order_type = "takeaway"
    if status not in ORDER_STATUSES:
        status = "pending"
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            INSERT INTO orders
                (shop_id, customer_id, customer_name, items, total, status,
                 customer_language, coupon_code, discount_amount, order_type, queue_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                shop_id,
                customer_id,
                customer_name,
                items_json,
                total,
                status,
                lang,
                coupon_code,
                discount_amount,
                order_type,
                queue_id,
            ),
        )
        order_id = cur.fetchone()["id"]
        conn.commit()
        return get_order(order_id)
    finally:
        conn.close()


def get_order(order_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, shop_id, customer_id, customer_name, items, total, status,
                   created_at, payment_image_url, payment_amount, customer_language,
                   coupon_code, discount_amount, order_type, queue_id
            FROM orders WHERE id = %s
            """,
            (order_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_order_status(order_id: int, status: str) -> bool:
    if status not in ORDER_STATUSES:
        raise ValueError(f"Invalid order status: {status}")
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "UPDATE orders SET status = %s WHERE id = %s",
            (status, order_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_order_payment(
    order_id: int,
    payment_amount: float,
    payment_image_url: str,
    status: str = "awaiting_payment",
) -> bool:
    if status not in ORDER_STATUSES:
        raise ValueError(f"Invalid order status: {status}")
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            UPDATE orders
            SET payment_amount = %s, payment_image_url = %s, status = %s
            WHERE id = %s
            """,
            (payment_amount, payment_image_url, status, order_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def order_number(order_id: int) -> str:
    return f"#{order_id + 1000}"


def count_completed_orders(customer_id: int) -> int:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt FROM orders
            WHERE customer_id = %s AND status = 'completed'
            """,
            (customer_id,),
        )
        row = cur.fetchone()
        return int(row["cnt"] if row else 0)
    finally:
        conn.close()


def generate_coupon_code(prefix: str = "CPN", length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = f"{prefix}{''.join(secrets.choice(alphabet) for _ in range(length))}"
        if not get_coupon_by_code(code):
            return code
    return f"{prefix}{secrets.token_hex(4).upper()}"


def create_coupon(
    code: str,
    coupon_type: str,
    value: float,
    min_order: float = 0,
    shop_id: int = 1,
    usage_limit: int = 1,
    expires_at: str | None = None,
) -> dict:
    if coupon_type not in ("fixed", "percent"):
        raise ValueError("type must be fixed or percent")
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            INSERT INTO coupons
                (code, type, value, min_order, shop_id, usage_limit, used_count, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
            RETURNING id
            """,
            (
                code.strip().upper(),
                coupon_type,
                float(value),
                float(min_order or 0),
                shop_id,
                int(usage_limit),
                expires_at,
            ),
        )
        coupon_id = cur.fetchone()["id"]
        conn.commit()
        return get_coupon_by_id(coupon_id)
    finally:
        conn.close()


def get_coupon_by_id(coupon_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM coupons WHERE id = %s", (coupon_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_coupon_by_code(code: str) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT * FROM coupons WHERE UPPER(code) = UPPER(%s)",
            (code.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def assign_coupon_to_user(user_id: int, coupon_id: int) -> bool:
    """Assign coupon to user if not already assigned. Returns True if newly assigned."""
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT id FROM user_coupons WHERE user_id = %s AND coupon_id = %s",
            (user_id, coupon_id),
        )
        existing = cur.fetchone()
        if existing:
            return False
        cur.execute(
            "INSERT INTO user_coupons (user_id, coupon_id, used) VALUES (%s, %s, 0)",
            (user_id, coupon_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def user_has_coupon(user_id: int, coupon_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT id FROM user_coupons WHERE user_id = %s AND coupon_id = %s",
            (user_id, coupon_id),
        )
        row = cur.fetchone()
        return row is not None
    finally:
        conn.close()


def grant_welcome_coupon(user_id: int) -> dict | None:
    """Give WELCOME5 to user if not already given. Returns coupon dict if newly granted."""
    coupon = get_coupon_by_code("WELCOME5")
    if not coupon:
        coupon = create_coupon(
            code="WELCOME5",
            coupon_type="fixed",
            value=5.0,
            min_order=0,
            usage_limit=999999,
            expires_at=None,
        )
    if assign_coupon_to_user(user_id, coupon["id"]):
        return coupon
    return None


def create_and_assign_fixed_coupon(
    user_id: int,
    value: float,
    code: str | None = None,
    min_order: float = 0,
) -> dict:
    if not code:
        code = generate_coupon_code("REF", 4)
    coupon = create_coupon(
        code=code,
        coupon_type="fixed",
        value=value,
        min_order=min_order,
        usage_limit=1,
        expires_at=(datetime.utcnow() + timedelta(days=90)).strftime("%Y-%m-%d"),
    )
    assign_coupon_to_user(user_id, coupon["id"])
    return coupon


def calc_discount(coupon: dict, total: float) -> float:
    if coupon["type"] == "percent":
        discount = total * (float(coupon["value"]) / 100.0)
    else:
        discount = float(coupon["value"])
    return round(min(max(discount, 0), total), 2)


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        # Accept YYYY-MM-DD or full timestamp
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", ""))
    except ValueError:
        try:
            expiry = datetime.strptime(str(expires_at)[:10], "%Y-%m-%d")
        except ValueError:
            return False
    return datetime.utcnow() > expiry


def validate_coupon(code: str, user_id: int, total: float, shop_id: int = 1) -> dict:
    """
    Returns {valid, discount, reason?, coupon?}
    """
    coupon = get_coupon_by_code(code)
    if not coupon:
        return {"valid": False, "discount": 0, "reason": "not_found"}
    if int(coupon.get("shop_id") or 1) != int(shop_id):
        return {"valid": False, "discount": 0, "reason": "not_found"}
    if _is_expired(coupon.get("expires_at")):
        return {"valid": False, "discount": 0, "reason": "expired"}
    if int(coupon.get("used_count") or 0) >= int(coupon.get("usage_limit") or 1):
        return {"valid": False, "discount": 0, "reason": "usage_limit"}
    if float(total) < float(coupon.get("min_order") or 0):
        return {
            "valid": False,
            "discount": 0,
            "reason": "min_order",
            "min_order": float(coupon.get("min_order") or 0),
        }

    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT id, used FROM user_coupons
            WHERE user_id = %s AND coupon_id = %s
            """,
            (user_id, coupon["id"]),
        )
        uc = cur.fetchone()
        # Personal coupons (WELCOME/REF) must be assigned and unused
        personal_prefix = coupon["code"].upper().startswith(
            ("WELCOME", "REF_", "POINTS100", "TIKTOK5")
        )
        if personal_prefix:
            if not uc:
                return {"valid": False, "discount": 0, "reason": "not_assigned"}
            if int(uc["used"] or 0) == 1:
                return {"valid": False, "discount": 0, "reason": "already_used"}
        elif uc and int(uc["used"] or 0) == 1:
            return {"valid": False, "discount": 0, "reason": "already_used"}
    finally:
        conn.close()

    discount = calc_discount(coupon, float(total))
    return {
        "valid": True,
        "discount": discount,
        "coupon": {
            "id": coupon["id"],
            "code": coupon["code"],
            "type": coupon["type"],
            "value": coupon["value"],
            "min_order": coupon["min_order"],
        },
    }


def mark_coupon_used(code: str, user_id: int) -> bool:
    coupon = get_coupon_by_code(code)
    if not coupon:
        return False
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            UPDATE coupons SET used_count = used_count + 1 WHERE id = %s
            """,
            (coupon["id"],),
        )
        cur.execute(
            "SELECT id FROM user_coupons WHERE user_id = %s AND coupon_id = %s",
            (user_id, coupon["id"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE user_coupons SET used = 1 WHERE user_id = %s AND coupon_id = %s",
                (user_id, coupon["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO user_coupons (user_id, coupon_id, used) VALUES (%s, %s, 1)",
                (user_id, coupon["id"]),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def get_user_unused_coupons(user_id: int) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT c.id, c.code, c.type, c.value, c.min_order, c.expires_at, c.usage_limit, c.used_count
            FROM user_coupons uc
            JOIN coupons c ON c.id = uc.coupon_id
            WHERE uc.user_id = %s AND uc.used = 0
            ORDER BY uc.id DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            coupon = dict(row)
            if _is_expired(coupon.get("expires_at")):
                continue
            if int(coupon.get("used_count") or 0) >= int(coupon.get("usage_limit") or 1):
                continue
            result.append(coupon)
        return result
    finally:
        conn.close()


def create_referral(referrer_id: int, referred_id: int) -> dict | None:
    if referrer_id == referred_id:
        return None
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT * FROM referrals WHERE referred_id = %s",
            (referred_id,),
        )
        existing = cur.fetchone()
        if existing:
            return dict(existing)
        cur.execute(
            """
            INSERT INTO referrals (referrer_id, referred_id, status, reward_given)
            VALUES (%s, %s, 'pending', 0)
            RETURNING id
            """,
            (referrer_id, referred_id),
        )
        referral_id = cur.fetchone()["id"]
        conn.commit()
        cur.execute(
            "SELECT * FROM referrals WHERE id = %s",
            (referral_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_referral_for_referred(referred_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT * FROM referrals WHERE referred_id = %s",
            (referred_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def process_referral_rewards(referred_id: int) -> list[dict]:
    """
    When referred user completes first order, give both sides a $1 coupon.
    Returns list of created coupon dicts with user_id.
    """
    referral = get_referral_for_referred(referred_id)
    if not referral or int(referral.get("reward_given") or 0) == 1:
        return []
    if referral.get("status") == "rewarded":
        return []

    # First completed order only (caller should check count == 1 after marking completed)
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    created = []
    for uid in (int(referral["referrer_id"]), int(referred_id)):
        code = f"REF_{uid}_{ts}"
        coupon = create_and_assign_fixed_coupon(uid, value=1.0, code=code)
        created.append({"user_id": uid, "coupon": coupon})

    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            UPDATE referrals
            SET reward_given = 1, status = 'rewarded'
            WHERE id = %s
            """,
            (referral["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    return created


# --- Customers / points / reviews ---


def ensure_customer(user_id: int, first_name: str | None = None) -> dict:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT user_id, first_name, points FROM customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            if first_name and not row["first_name"]:
                cur.execute(
                    "UPDATE customers SET first_name = %s WHERE user_id = %s",
                    (first_name, user_id),
                )
                conn.commit()
                cur.execute(
                    "SELECT user_id, first_name, points FROM customers WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
            return dict(row)

        cur.execute(
            "INSERT INTO customers (user_id, first_name, points) VALUES (%s, %s, 0)",
            (user_id, first_name),
        )
        conn.commit()
        cur.execute(
            "SELECT user_id, first_name, points FROM customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row)
    finally:
        conn.close()


def get_customer_points(user_id: int) -> int:
    customer = ensure_customer(user_id)
    return int(customer.get("points") or 0)


def add_customer_points(user_id: int, amount: int, first_name: str | None = None) -> int:
    ensure_customer(user_id, first_name=first_name)
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "UPDATE customers SET points = COALESCE(points, 0) + %s WHERE user_id = %s",
            (int(amount), user_id),
        )
        conn.commit()
        cur.execute(
            "SELECT points FROM customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return int(row["points"] if row else 0)
    finally:
        conn.close()


def redeem_points_for_coupon(user_id: int, cost: int = 100, value: float = 1.0) -> dict:
    """
    Deduct points and create a POINTS100 $1 coupon for the user.
    Returns {ok, points?, coupon?, error?}
    """
    ensure_customer(user_id)
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT points FROM customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        points = int(row["points"] if row else 0)
        if points < cost:
            return {"ok": False, "error": "insufficient_points", "points": points}

        cur.execute(
            "UPDATE customers SET points = points - %s WHERE user_id = %s AND points >= %s",
            (cost, user_id, cost),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"ok": False, "error": "insufficient_points", "points": points}
        conn.commit()
    finally:
        conn.close()

    code = f"POINTS100_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    coupon = create_and_assign_fixed_coupon(
        user_id=user_id,
        value=value,
        code=code,
        min_order=0,
    )
    return {
        "ok": True,
        "points": get_customer_points(user_id),
        "coupon": coupon,
    }


def get_review_by_order_user(order_id: int, user_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT * FROM reviews WHERE order_id = %s AND user_id = %s",
            (order_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_review(
    order_id: int,
    user_id: int,
    rating: int,
    comment: str | None = None,
    image_url: str | None = None,
    first_name: str | None = None,
) -> dict:
    if rating < 1 or rating > 5:
        raise ValueError("rating must be 1-5")
    if get_review_by_order_user(order_id, user_id):
        raise ValueError("already_reviewed")

    ensure_customer(user_id, first_name=first_name)
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            INSERT INTO reviews (order_id, user_id, rating, comment, image_url, is_featured)
            VALUES (%s, %s, %s, %s, %s, 0)
            RETURNING id
            """,
            (order_id, user_id, int(rating), comment, image_url),
        )
        review_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    points = 5 + (10 if image_url else 0)
    new_balance = add_customer_points(user_id, points, first_name=first_name)
    review = get_review(review_id)
    return {"review": review, "points_awarded": points, "points": new_balance}


def get_review(review_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_recent_reviews(limit: int = 20) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT r.*, c.first_name, o.customer_name
            FROM reviews r
            LEFT JOIN customers c ON c.user_id = r.user_id
            LEFT JOIN orders o ON o.id = r.order_id
            ORDER BY r.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_review_featured(review_id: int, featured: bool = True) -> bool:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "UPDATE reviews SET is_featured = %s WHERE id = %s",
            (1 if featured else 0, review_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_review(review_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_featured_reviews(shop_id: int = 1, limit: int = 20) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT r.id, r.order_id, r.user_id, r.rating, r.comment, r.image_url,
                   r.created_at, COALESCE(c.first_name, o.customer_name, 'Guest') AS first_name
            FROM reviews r
            LEFT JOIN customers c ON c.user_id = r.user_id
            LEFT JOIN orders o ON o.id = r.order_id
            WHERE r.is_featured = 1
              AND (o.shop_id = %s OR o.shop_id IS NULL)
            ORDER BY r.id DESC
            LIMIT %s
            """,
            (shop_id, limit),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_tiktok_submission(
    user_id: int,
    video_url: str,
    order_id: int | None = None,
) -> dict:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            INSERT INTO tiktok_submissions (user_id, order_id, video_url, status, reward_given)
            VALUES (%s, %s, %s, 'pending', 0)
            RETURNING id
            """,
            (user_id, order_id, video_url.strip()),
        )
        submission_id = cur.fetchone()["id"]
        conn.commit()
        return get_tiktok_submission(submission_id)
    finally:
        conn.close()


def get_tiktok_submission(submission_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT * FROM tiktok_submissions WHERE id = %s",
            (submission_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_tiktok_submission(
    submission_id: int,
    status: str,
    reward_given: int | None = None,
) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        if reward_given is None:
            cur.execute(
                "UPDATE tiktok_submissions SET status = %s WHERE id = %s",
                (status, submission_id),
            )
        else:
            cur.execute(
                """
                UPDATE tiktok_submissions
                SET status = %s, reward_given = %s
                WHERE id = %s
                """,
                (status, int(reward_given), submission_id),
            )
        conn.commit()
        return get_tiktok_submission(submission_id)
    finally:
        conn.close()


def get_queue_entry(queue_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM queue WHERE id = %s", (queue_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_queue_for_user(shop_id: int, user_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = %s AND user_id = %s
              AND status IN ('waiting', 'ordering', 'ready')
            ORDER BY id DESC
            LIMIT 1
            """,
            (shop_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_active_queue(shop_id: int = 1) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = %s AND status IN ('waiting', 'ordering', 'ready')
            ORDER BY queue_number ASC, id ASC
            """,
            (shop_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def estimate_queue_wait(shop_id: int, queue_number: int) -> int:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT COUNT(*) AS ahead
            FROM queue
            WHERE shop_id = %s
              AND status = 'waiting'
              AND queue_number < %s
            """,
            (shop_id, queue_number),
        )
        row = cur.fetchone()
        ahead = int(row["ahead"] if row else 0)
        return max(0, ahead * MINUTES_PER_PARTY)
    finally:
        conn.close()


def join_queue(shop_id: int, user_id: int, party_size: int) -> dict:
    party_size = max(1, min(int(party_size), 50))
    existing = get_active_queue_for_user(shop_id, user_id)
    if existing:
        wait = estimate_queue_wait(shop_id, int(existing["queue_number"]))
        return {**existing, "estimated_wait": wait, "already_in_queue": True}

    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT COALESCE(MAX(queue_number), 0) AS max_num
            FROM queue
            WHERE shop_id = %s
              AND created_at::date = CURRENT_DATE
            """,
            (shop_id,),
        )
        row = cur.fetchone()
        next_num = int(row["max_num"] or 0) + 1
        cur.execute(
            """
            INSERT INTO queue (shop_id, user_id, queue_number, party_size, status)
            VALUES (%s, %s, %s, %s, 'waiting')
            RETURNING id
            """,
            (shop_id, user_id, next_num, party_size),
        )
        queue_id = cur.fetchone()["id"]
        conn.commit()
        entry = get_queue_entry(queue_id)
        wait = estimate_queue_wait(shop_id, next_num)
        return {**entry, "estimated_wait": wait, "already_in_queue": False}
    finally:
        conn.close()


def update_queue_status(queue_id: int, status: str) -> dict | None:
    if status not in QUEUE_STATUSES:
        raise ValueError(f"Invalid queue status: {status}")
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            "UPDATE queue SET status = %s WHERE id = %s",
            (status, queue_id),
        )
        conn.commit()
        return get_queue_entry(queue_id)
    finally:
        conn.close()


def advance_next_waiting(shop_id: int = 1) -> dict | None:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = %s AND status = 'waiting'
            ORDER BY queue_number ASC, id ASC
            LIMIT 1
            """,
            (shop_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        queue_id = int(row["id"])
    finally:
        conn.close()
    return update_queue_status(queue_id, "ordering")


def get_orders_in_range(shop_id: int, start_date: str, end_date: str) -> list[dict]:
    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT *
            FROM orders
            WHERE shop_id = %s
              AND created_at::date >= %s::date
              AND created_at::date <= %s::date
            ORDER BY id ASC
            """,
            (shop_id, start_date, end_date),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_order_stats(shop_id: int, period: str = "today") -> dict:
    period = (period or "today").lower()
    if period == "week":
        start_expr = "(CURRENT_DATE - INTERVAL '6 days')"
        end_expr = "CURRENT_DATE"
        label = "week"
    else:
        start_expr = "CURRENT_DATE"
        end_expr = "CURRENT_DATE"
        label = "today"

    conn = get_db_connection()
    try:
        cur = _cursor(conn)
        cur.execute(
            f"""
            SELECT id, items, total, status, created_at, order_type
            FROM orders
            WHERE shop_id = %s
              AND created_at::date >= {start_expr}
              AND created_at::date <= {end_expr}
              AND status != 'cancelled'
            ORDER BY id ASC
            """,
            (shop_id,),
        )
        rows = cur.fetchall()
        orders = [dict(row) for row in rows]
    finally:
        conn.close()

    revenue = 0.0
    item_counts: dict[str, int] = {}
    for order in orders:
        if order.get("status") in ("completed", "awaiting_payment", "pending", "pending_preorder"):
            if order.get("status") == "completed":
                revenue += float(order.get("total") or 0)
        try:
            items = json.loads(order.get("items") or "[]")
        except Exception:
            items = []
        if not isinstance(items, list):
            continue
        for item in items:
            name = (
                item.get("name_en")
                or item.get("name_zh")
                or item.get("name_km")
                or "Item"
            )
            qty = int(item.get("quantity") or item.get("qty") or 1)
            item_counts[name] = item_counts.get(name, 0) + qty

    top_items = sorted(item_counts.items(), key=lambda x: (-x[1], x[0]))[:5]
    return {
        "period": label,
        "total_orders": len(orders),
        "revenue": round(revenue, 2),
        "top_items": [{"name": name, "qty": qty} for name, qty in top_items],
    }
