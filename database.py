import json
import sqlite3
import secrets
import string
from datetime import datetime, timedelta

DB_PATH = "shop.db"

ORDER_STATUSES = (
    "pending",
    "pending_preorder",
    "awaiting_payment",
    "completed",
    "cancelled",
)
QUEUE_STATUSES = ("waiting", "ordering", "ready", "done", "cancelled")
MINUTES_PER_PARTY = 8


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_settings (
                id INTEGER PRIMARY KEY,
                name_en TEXT NOT NULL,
                name_km TEXT,
                name_zh TEXT,
                logo_url TEXT,
                primary_color TEXT NOT NULL,
                background_color TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO shop_settings
                (id, name_en, name_km, name_zh, logo_url, primary_color, background_color)
            VALUES (1, 'My Shop', 'ហាងរបស់ខ្ញុំ', '我的店铺', NULL, '#FF5722', '#FFFFFF')
            """
        )

        columns = {row[1] for row in conn.execute("PRAGMA table_info(shop_settings)")}
        for col, default in (
            ("name_en", "'My Shop'"),
            ("name_km", "NULL"),
            ("name_zh", "NULL"),
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
                conn.execute(
                    f"ALTER TABLE shop_settings ADD COLUMN {col} {col_type} DEFAULT {default}"
                )

        if "shop_name" in columns:
            conn.execute(
                """
                UPDATE shop_settings
                SET name_en = COALESCE(NULLIF(name_en, ''), shop_name, 'My Shop'),
                    name_km = COALESCE(NULLIF(name_km, ''), 'ហាងរបស់ខ្ញុំ'),
                    name_zh = COALESCE(NULLIF(name_zh, ''), '我的店铺')
                WHERE id = 1
                """
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        menu_columns = {row[1] for row in conn.execute("PRAGMA table_info(menu_items)")}
        if "is_vegetarian" not in menu_columns:
            conn.execute(
                "ALTER TABLE menu_items ADD COLUMN is_vegetarian INTEGER DEFAULT 0"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS festivals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        festival_count = conn.execute("SELECT COUNT(*) FROM festivals").fetchone()[0]
        if festival_count == 0:
            conn.executemany(
                """
                INSERT INTO festivals
                    (name_en, name_km, name_zh, start_date, end_date,
                     discount_percent, is_vegetarian)
                VALUES (?, ?, ?, ?, ?, ?, ?)
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER DEFAULT 1,
                customer_id INTEGER,
                customer_name TEXT,
                items TEXT,
                total REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        order_columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
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
                conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")

        conn.execute(
            "UPDATE orders SET status = 'completed' WHERE status IN ('paid', 'confirmed')"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER DEFAULT 1,
                user_id INTEGER NOT NULL,
                queue_number INTEGER NOT NULL,
                party_size INTEGER NOT NULL,
                status TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                coupon_id INTEGER NOT NULL,
                used INTEGER DEFAULT 0,
                UNIQUE(user_id, coupon_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        conn.execute(
            """
            INSERT OR IGNORE INTO coupons
                (code, type, value, min_order, shop_id, usage_limit, used_count, expires_at)
            VALUES ('WELCOME5', 'fixed', 5.0, 0, 1, 999999, 0, NULL)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                points INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        customer_cols = {row[1] for row in conn.execute("PRAGMA table_info(customers)")}
        if "points" not in customer_cols:
            conn.execute(
                "ALTER TABLE customers ADD COLUMN points INTEGER DEFAULT 0"
            )
        if "first_name" not in customer_cols:
            conn.execute("ALTER TABLE customers ADD COLUMN first_name TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tiktok_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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


def get_shop_settings(shop_id: int):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name_en, name_km, name_zh, logo_url, primary_color,
                   background_color, background_image_url, khqr_url,
                   current_festival_id, group_invite_link
            FROM shop_settings WHERE id = ?
            """,
            (shop_id,),
        ).fetchone()
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

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [shop_id]

    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE shop_settings SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
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
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO menu_items
                (shop_id, category, name_en, name_km, name_zh, price, image_url,
                 is_vegetarian)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        conn.commit()
        item_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, shop_id, category, name_en, name_km, name_zh, price,
                   image_url, is_vegetarian
            FROM menu_items WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_menu_items(shop_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, shop_id, category, name_en, name_km, name_zh, price,
                   image_url, is_vegetarian
            FROM menu_items
            WHERE shop_id = ?
            ORDER BY category COLLATE NOCASE, id
            """,
            (shop_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_festivals() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name_en, name_km, name_zh, start_date, end_date,
                   discount_percent, is_vegetarian
            FROM festivals
            ORDER BY start_date, id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_festival(festival_id: int | None) -> dict | None:
    if not festival_id:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name_en, name_km, name_zh, start_date, end_date,
                   discount_percent, is_vegetarian
            FROM festivals WHERE id = ?
            """,
            (int(festival_id),),
        ).fetchone()
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
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO orders
                (shop_id, customer_id, customer_name, items, total, status,
                 customer_language, coupon_code, discount_amount, order_type, queue_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        conn.commit()
        order_id = cursor.lastrowid
        return get_order(order_id)
    finally:
        conn.close()


def get_order(order_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, shop_id, customer_id, customer_name, items, total, status,
                   created_at, payment_image_url, payment_amount, customer_language,
                   coupon_code, discount_amount, order_type, queue_id
            FROM orders WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_order_status(order_id: int, status: str) -> bool:
    if status not in ORDER_STATUSES:
        raise ValueError(f"Invalid order status: {status}")
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id),
        )
        conn.commit()
        return cursor.rowcount > 0
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
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE orders
            SET payment_amount = ?, payment_image_url = ?, status = ?
            WHERE id = ?
            """,
            (payment_amount, payment_image_url, status, order_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def order_number(order_id: int) -> str:
    return f"#{order_id + 1000}"


def count_completed_orders(customer_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM orders
            WHERE customer_id = ? AND status = 'completed'
            """,
            (customer_id,),
        ).fetchone()
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
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO coupons
                (code, type, value, min_order, shop_id, usage_limit, used_count, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
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
        conn.commit()
        return get_coupon_by_id(cursor.lastrowid)
    finally:
        conn.close()


def get_coupon_by_id(coupon_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_coupon_by_code(code: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM coupons WHERE UPPER(code) = UPPER(?)",
            (code.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def assign_coupon_to_user(user_id: int, coupon_id: int) -> bool:
    """Assign coupon to user if not already assigned. Returns True if newly assigned."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM user_coupons WHERE user_id = ? AND coupon_id = ?",
            (user_id, coupon_id),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO user_coupons (user_id, coupon_id, used) VALUES (?, ?, 0)",
            (user_id, coupon_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def user_has_coupon(user_id: int, coupon_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM user_coupons WHERE user_id = ? AND coupon_id = ?",
            (user_id, coupon_id),
        ).fetchone()
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

    conn = get_connection()
    try:
        uc = conn.execute(
            """
            SELECT id, used FROM user_coupons
            WHERE user_id = ? AND coupon_id = ?
            """,
            (user_id, coupon["id"]),
        ).fetchone()
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
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE coupons SET used_count = used_count + 1 WHERE id = ?
            """,
            (coupon["id"],),
        )
        existing = conn.execute(
            "SELECT id FROM user_coupons WHERE user_id = ? AND coupon_id = ?",
            (user_id, coupon["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE user_coupons SET used = 1 WHERE user_id = ? AND coupon_id = ?",
                (user_id, coupon["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO user_coupons (user_id, coupon_id, used) VALUES (?, ?, 1)",
                (user_id, coupon["id"]),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def get_user_unused_coupons(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.code, c.type, c.value, c.min_order, c.expires_at, c.usage_limit, c.used_count
            FROM user_coupons uc
            JOIN coupons c ON c.id = uc.coupon_id
            WHERE uc.user_id = ? AND uc.used = 0
            ORDER BY uc.id DESC
            """,
            (user_id,),
        ).fetchall()
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
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM referrals WHERE referred_id = ?",
            (referred_id,),
        ).fetchone()
        if existing:
            return dict(existing)
        cursor = conn.execute(
            """
            INSERT INTO referrals (referrer_id, referred_id, status, reward_given)
            VALUES (?, ?, 'pending', 0)
            """,
            (referrer_id, referred_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM referrals WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_referral_for_referred(referred_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM referrals WHERE referred_id = ?",
            (referred_id,),
        ).fetchone()
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

    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE referrals
            SET reward_given = 1, status = 'rewarded'
            WHERE id = ?
            """,
            (referral["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    return created


# --- Customers / points / reviews ---


def ensure_customer(user_id: int, first_name: str | None = None) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT user_id, first_name, points FROM customers WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            if first_name and not row["first_name"]:
                conn.execute(
                    "UPDATE customers SET first_name = ? WHERE user_id = ?",
                    (first_name, user_id),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT user_id, first_name, points FROM customers WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            return dict(row)

        conn.execute(
            "INSERT INTO customers (user_id, first_name, points) VALUES (?, ?, 0)",
            (user_id, first_name),
        )
        conn.commit()
        row = conn.execute(
            "SELECT user_id, first_name, points FROM customers WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_customer_points(user_id: int) -> int:
    customer = ensure_customer(user_id)
    return int(customer.get("points") or 0)


def add_customer_points(user_id: int, amount: int, first_name: str | None = None) -> int:
    ensure_customer(user_id, first_name=first_name)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE customers SET points = COALESCE(points, 0) + ? WHERE user_id = ?",
            (int(amount), user_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT points FROM customers WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["points"] if row else 0)
    finally:
        conn.close()


def redeem_points_for_coupon(user_id: int, cost: int = 100, value: float = 1.0) -> dict:
    """
    Deduct points and create a POINTS100 $1 coupon for the user.
    Returns {ok, points?, coupon?, error?}
    """
    ensure_customer(user_id)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT points FROM customers WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        points = int(row["points"] if row else 0)
        if points < cost:
            return {"ok": False, "error": "insufficient_points", "points": points}

        conn.execute(
            "UPDATE customers SET points = points - ? WHERE user_id = ? AND points >= ?",
            (cost, user_id, cost),
        )
        if conn.total_changes == 0:
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
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM reviews WHERE order_id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
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
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO reviews (order_id, user_id, rating, comment, image_url, is_featured)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (order_id, user_id, int(rating), comment, image_url),
        )
        conn.commit()
        review_id = cursor.lastrowid
    finally:
        conn.close()

    points = 5 + (10 if image_url else 0)
    new_balance = add_customer_points(user_id, points, first_name=first_name)
    review = get_review(review_id)
    return {"review": review, "points_awarded": points, "points": new_balance}


def get_review(review_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_recent_reviews(limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT r.*, c.first_name, o.customer_name
            FROM reviews r
            LEFT JOIN customers c ON c.user_id = r.user_id
            LEFT JOIN orders o ON o.id = r.order_id
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_review_featured(review_id: int, featured: bool = True) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE reviews SET is_featured = ? WHERE id = ?",
            (1 if featured else 0, review_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_review(review_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_featured_reviews(shop_id: int = 1, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.order_id, r.user_id, r.rating, r.comment, r.image_url,
                   r.created_at, COALESCE(c.first_name, o.customer_name, 'Guest') AS first_name
            FROM reviews r
            LEFT JOIN customers c ON c.user_id = r.user_id
            LEFT JOIN orders o ON o.id = r.order_id
            WHERE r.is_featured = 1
              AND (o.shop_id = ? OR o.shop_id IS NULL)
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (shop_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_tiktok_submission(
    user_id: int,
    video_url: str,
    order_id: int | None = None,
) -> dict:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO tiktok_submissions (user_id, order_id, video_url, status, reward_given)
            VALUES (?, ?, ?, 'pending', 0)
            """,
            (user_id, order_id, video_url.strip()),
        )
        conn.commit()
        return get_tiktok_submission(cursor.lastrowid)
    finally:
        conn.close()


def get_tiktok_submission(submission_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM tiktok_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_tiktok_submission(
    submission_id: int,
    status: str,
    reward_given: int | None = None,
) -> dict | None:
    conn = get_connection()
    try:
        if reward_given is None:
            conn.execute(
                "UPDATE tiktok_submissions SET status = ? WHERE id = ?",
                (status, submission_id),
            )
        else:
            conn.execute(
                """
                UPDATE tiktok_submissions
                SET status = ?, reward_given = ?
                WHERE id = ?
                """,
                (status, int(reward_given), submission_id),
            )
        conn.commit()
        return get_tiktok_submission(submission_id)
    finally:
        conn.close()


def get_queue_entry(queue_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM queue WHERE id = ?", (queue_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_queue_for_user(shop_id: int, user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = ? AND user_id = ?
              AND status IN ('waiting', 'ordering', 'ready')
            ORDER BY id DESC
            LIMIT 1
            """,
            (shop_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_active_queue(shop_id: int = 1) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = ? AND status IN ('waiting', 'ordering', 'ready')
            ORDER BY queue_number ASC, id ASC
            """,
            (shop_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def estimate_queue_wait(shop_id: int, queue_number: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS ahead
            FROM queue
            WHERE shop_id = ?
              AND status = 'waiting'
              AND queue_number < ?
            """,
            (shop_id, queue_number),
        ).fetchone()
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

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(queue_number), 0) AS max_num
            FROM queue
            WHERE shop_id = ?
              AND date(created_at) = date('now', 'localtime')
            """,
            (shop_id,),
        ).fetchone()
        next_num = int(row["max_num"] or 0) + 1
        cursor = conn.execute(
            """
            INSERT INTO queue (shop_id, user_id, queue_number, party_size, status)
            VALUES (?, ?, ?, ?, 'waiting')
            """,
            (shop_id, user_id, next_num, party_size),
        )
        conn.commit()
        entry = get_queue_entry(cursor.lastrowid)
        wait = estimate_queue_wait(shop_id, next_num)
        return {**entry, "estimated_wait": wait, "already_in_queue": False}
    finally:
        conn.close()


def update_queue_status(queue_id: int, status: str) -> dict | None:
    if status not in QUEUE_STATUSES:
        raise ValueError(f"Invalid queue status: {status}")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE queue SET status = ? WHERE id = ?",
            (status, queue_id),
        )
        conn.commit()
        return get_queue_entry(queue_id)
    finally:
        conn.close()


def advance_next_waiting(shop_id: int = 1) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM queue
            WHERE shop_id = ? AND status = 'waiting'
            ORDER BY queue_number ASC, id ASC
            LIMIT 1
            """,
            (shop_id,),
        ).fetchone()
        if not row:
            return None
        queue_id = int(row["id"])
    finally:
        conn.close()
    return update_queue_status(queue_id, "ordering")


def get_orders_in_range(shop_id: int, start_date: str, end_date: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE shop_id = ?
              AND date(created_at) >= date(?)
              AND date(created_at) <= date(?)
            ORDER BY id ASC
            """,
            (shop_id, start_date, end_date),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_order_stats(shop_id: int, period: str = "today") -> dict:
    period = (period or "today").lower()
    if period == "week":
        start_expr = "date('now', 'localtime', '-6 days')"
        end_expr = "date('now', 'localtime')"
        label = "week"
    else:
        start_expr = "date('now', 'localtime')"
        end_expr = "date('now', 'localtime')"
        label = "today"

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT id, items, total, status, created_at, order_type
            FROM orders
            WHERE shop_id = ?
              AND date(created_at) >= {start_expr}
              AND date(created_at) <= {end_expr}
              AND status != 'cancelled'
            ORDER BY id ASC
            """,
            (shop_id,),
        ).fetchall()
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
