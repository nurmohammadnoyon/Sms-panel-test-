import aiosqlite
import asyncio
import logging
from config import DB_PATH, DEFAULT_SUPPORT_USERNAME, DEFAULT_REFERRAL_AMOUNT, DEFAULT_MIN_WITHDRAW, DEFAULT_OTP_GROUP_LINK

logger = logging.getLogger(__name__)

# ============================================================
# DATABASE INITIALIZATION
# ============================================================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0.0,
                referral_count INTEGER DEFAULT 0,
                referred_by INTEGER DEFAULT NULL,
                otp_count INTEGER DEFAULT 0,
                daily_otp_count INTEGER DEFAULT 0,
                daily_otp_date TEXT DEFAULT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add otp_count if missing
        try:
            await db.execute("ALTER TABLE users ADD COLUMN otp_count INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        # Migration: add daily_otp_count and daily_otp_date if missing
        try:
            await db.execute("ALTER TABLE users ADD COLUMN daily_otp_count INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN daily_otp_date TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # Admins table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Categories (services) table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                emoji TEXT DEFAULT '💥',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Number batches table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS number_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_code TEXT NOT NULL,
                country_name TEXT NOT NULL,
                country_flag TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                numbers_per_user INTEGER DEFAULT 1,
                rate_per_otp REAL DEFAULT 0.0,
                total_numbers INTEGER DEFAULT 0,
                available_numbers INTEGER DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)

        # Numbers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                number TEXT NOT NULL,
                is_used INTEGER DEFAULT 0,
                assigned_to INTEGER DEFAULT NULL,
                assigned_at TIMESTAMP DEFAULT NULL,
                otp_received TEXT DEFAULT NULL,
                FOREIGN KEY (batch_id) REFERENCES number_batches(id)
            )
        """)

        # Migration: add otp_received_at for live-traffic tracking
        try:
            await db.execute("ALTER TABLE numbers ADD COLUMN otp_received_at TIMESTAMP DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # Migration: add saved wallet (payment method) fields to users
        try:
            await db.execute("ALTER TABLE users ADD COLUMN wallet_method TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN wallet_address TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass

        # Migration: hide/unhide number batches from users without deleting them
        try:
            await db.execute("ALTER TABLE number_batches ADD COLUMN is_hidden INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass

        # Released assignments — grace period OTP delivery
        await db.execute("""
            CREATE TABLE IF NOT EXISTS released_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                number TEXT NOT NULL,
                rate_per_otp REAL DEFAULT 0,
                country_name TEXT DEFAULT 'Unknown',
                country_flag TEXT DEFAULT '🌍',
                category_name TEXT DEFAULT '',
                released_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, definition in [
            ("rate_per_otp",   "REAL DEFAULT 0"),
            ("country_name",   "TEXT DEFAULT 'Unknown'"),
            ("country_flag",   "TEXT DEFAULT '🌍'"),
            ("category_name",  "TEXT DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE released_assignments ADD COLUMN {col} {definition}")
                await db.commit()
            except Exception:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                method TEXT NOT NULL,
                address TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP DEFAULT NULL
            )
        """)

        # Bot settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Required channels table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_link TEXT NOT NULL,
                channel_id TEXT DEFAULT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # APIs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS apis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                api_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_type TEXT DEFAULT 'other',
                is_active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE apis ADD COLUMN api_type TEXT DEFAULT 'other'")
            await db.commit()
        except Exception:
            pass
        # Migration: login-type panel credentials
        try:
            await db.execute("ALTER TABLE apis ADD COLUMN username TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE apis ADD COLUMN password TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # User assignments — supports multiple numbers per user
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                number_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                category_name TEXT NOT NULL,
                country_name TEXT NOT NULL,
                country_flag TEXT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (number_id) REFERENCES numbers(id)
            )
        """)
        # Migration: if old table had user_id as PK, recreate it
        try:
            await db.execute("ALTER TABLE user_assignments ADD COLUMN id INTEGER")
        except Exception:
            pass

        # PSCall scrapers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scrapers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT UNIQUE NOT NULL,
                base_url     TEXT NOT NULL DEFAULT '',
                username     TEXT NOT NULL,
                password     TEXT NOT NULL,
                scraper_type TEXT NOT NULL DEFAULT 'agent',
                is_active    INTEGER DEFAULT 1,
                added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, definition in [
            ("base_url",     "TEXT NOT NULL DEFAULT ''"),
            ("scraper_type", "TEXT NOT NULL DEFAULT 'agent'"),
        ]:
            try:
                await db.execute(f"ALTER TABLE scrapers ADD COLUMN {col} {definition}")
                await db.commit()
            except Exception:
                pass

        # Balance logs table — প্রতিটা balance পরিবর্তনের ইতিহাস
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                source TEXT NOT NULL,
                note TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Panel hold settings — কোন প্যানেলের OTP reward hold করা হবে কিনা
        await db.execute("""
            CREATE TABLE IF NOT EXISTS panel_hold_settings (
                panel_name TEXT PRIMARY KEY,
                hold_enabled INTEGER DEFAULT 0,
                hold_days INTEGER DEFAULT 7
            )
        """)

        # Pending rewards — hold করা OTP reward গুলো, hold_days পার হলে balance-এ যোগ হবে
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                panel_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                release_at TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        """)

        # OTP delivery log — প্রতিটা scrape হওয়া OTP এখানে লগ হয়, delivery status সহ।
        # এর মাধ্যমে কোনো OTP silently miss হলেও পরে ধরে retry/resend করা যায়।
        await db.execute("""
            CREATE TABLE IF NOT EXISTS otp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT NOT NULL,
                otp TEXT NOT NULL,
                service TEXT DEFAULT '',
                sms_text TEXT DEFAULT '',
                user_id INTEGER,
                delivered INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                delivered_at TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_otp_log_user ON otp_log(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_otp_log_delivered ON otp_log(delivered)")
        # Migration: permanently_failed flag — bot ব্লক/deactivated ইউজারদের জন্য
        # আর retry না করে বন্ধ করে দেওয়ার flag (যাতে অন্যদের OTP-এর জন্য sweep আটকে না থাকে)
        try:
            await db.execute("ALTER TABLE otp_log ADD COLUMN permanently_failed INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass

        # Initialize default settings
        defaults = {
            "support_username": DEFAULT_SUPPORT_USERNAME,
            "referral_amount": str(DEFAULT_REFERRAL_AMOUNT),
            "min_withdraw": str(DEFAULT_MIN_WITHDRAW),
            "otp_group_link": DEFAULT_OTP_GROUP_LINK,
            "payment_proof_channel_link": "https://t.me/payment_update3",
            "payment_proof_channel_id": "-1003792985653",
            "referral_notify_enabled": "1",
            "otp_grace_minutes": "30",
        }
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
                (key, value)
            )

        await db.commit()
        logger.info("✅ Database initialized successfully.")

# ============================================================
# GRACE PERIOD FUNCTIONS
async def save_released_numbers(user_id: int, numbers: list, rate_per_otp: float = 0,
                                 country_name: str = "Unknown", country_flag: str = "🌍",
                                 category_name: str = ""):
    """Number change হলে পুরানো numbers save করো grace period-এর জন্য — reward hisab রাখার জন্য rate/country-ও সেভ করা হয়"""
    async with aiosqlite.connect(DB_PATH) as db:
        for number in numbers:
            num = str(number).lstrip("+")
            await db.execute(
                "INSERT INTO released_assignments (user_id, number, rate_per_otp, country_name, country_flag, category_name) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, num, rate_per_otp, country_name, country_flag, category_name)
            )
        await db.commit()

async def get_grace_period_user(number: str, grace_minutes: int = 10):
    """Grace period-এর মধ্যে released number-এর user খোঁজো — rate/country সহ (যাতে reward ঠিকমতো যোগ হয়)"""
    if grace_minutes <= 0:
        return None
    num = number.lstrip("+")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT ra.user_id, ra.rate_per_otp, ra.country_name, ra.country_flag, ra.category_name,
                   u.username, u.full_name
            FROM released_assignments ra
            JOIN users u ON ra.user_id = u.user_id
            WHERE (ra.number = ? OR ra.number LIKE ?)
            AND ra.released_at >= datetime('now', ? || ' minutes')
            ORDER BY ra.released_at DESC LIMIT 1
        """, (num, "%" + num[-8:], f"-{grace_minutes}")) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# ============================================================
# USER FUNCTIONS
async def ban_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def unban_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        await db.commit()

async def is_user_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])

# ============================================================

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def add_user(user_id: int, username: str, full_name: str, referred_by: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, referred_by) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, referred_by)
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def update_user_balance(user_id: int, amount: float, source: str = "manual", note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = ROUND(balance + ?, 2) WHERE user_id = ?",
            (amount, user_id)
        )
        await db.execute(
            "INSERT INTO balance_logs (user_id, amount, source, note) VALUES (?, ?, ?, ?)",
            (user_id, amount, source, note)
        )
        await db.commit()

async def increment_referral_count(referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?",
            (referrer_id,)
        )
        await db.commit()

async def get_user_balance(user_id: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return round(row[0], 2) if row else 0.0

async def get_all_users_with_balance():
    """সব ইউজারের balance দেখাবে (balance > 0)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id, username, full_name, balance, otp_count, referral_count
               FROM users WHERE balance > 0 ORDER BY balance DESC"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_user_balance_logs(user_id: int, limit: int = 20):
    """একজন ইউজারের balance ইতিহাস"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT amount, source, note, created_at
               FROM balance_logs WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def reset_user_balance(user_id: int):
    """Admin কর্তৃক ইউজারের balance শূন্য করা"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        old_balance = row[0] if row else 0.0
        await db.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO balance_logs (user_id, amount, source, note) VALUES (?, ?, ?, ?)",
            (user_id, -old_balance, "admin_reset", "Admin কর্তৃক balance রিসেট")
        )
        await db.commit()

async def set_user_wallet(user_id: int, method: str, address: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET wallet_method = ?, wallet_address = ? WHERE user_id = ?",
            (method, address, user_id)
        )
        await db.commit()

async def get_user_wallet(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wallet_method, wallet_address FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row["wallet_method"] and row["wallet_address"]:
                return {"method": row["wallet_method"], "address": row["wallet_address"]}
            return None

async def get_total_withdrawn(user_id: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM withdraw_requests WHERE user_id = ? AND status = 'completed'",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return round(row[0], 2) if row else 0.0

async def get_total_referral_earnings(user_id: int) -> float:
    """রেফার করা ইউজারদের OTP থেকে এখন পর্যন্ত মোট কত বোনাস পেয়েছে তা বের করে"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM balance_logs WHERE user_id = ? AND source = 'referral_otp_bonus'",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return round(row[0], 2) if row else 0.0

async def count_live_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_user_otp_stats(user_id: int):
    """Return (daily_otp_count, total_otp_count) for a user. Resets daily at midnight BD time."""
    from datetime import datetime, timezone, timedelta
    bd_tz = timezone(timedelta(hours=6))
    today_bd = datetime.now(bd_tz).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT otp_count, daily_otp_count, daily_otp_date FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0, 0
            total = row["otp_count"] or 0
            daily = row["daily_otp_count"] or 0
            last_date = row["daily_otp_date"]
            if last_date != today_bd:
                daily = 0
            return daily, total

async def increment_otp_count(user_id: int):
    """Increment the OTP received count for a user. Resets every 24 hours (BD time)."""
    from datetime import datetime, timezone, timedelta
    bd_tz = timezone(timedelta(hours=6))
    today_bd = datetime.now(bd_tz).strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT daily_otp_count, daily_otp_date FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row and row["daily_otp_date"] == today_bd:
            new_daily = (row["daily_otp_count"] or 0) + 1
        else:
            new_daily = 1
        await db.execute(
            "UPDATE users SET otp_count = otp_count + 1, daily_otp_count = ?, daily_otp_date = ? WHERE user_id = ?",
            (new_daily, today_bd, user_id)
        )
        await db.commit()

async def get_leaderboard(limit: int = 10):
    """Return top N users by total OTP count."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, username, full_name, otp_count FROM users ORDER BY otp_count DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_daily_leaderboard(limit: int = 30):
    """Return top N users by today's OTP count with reward. Resets every 24 hours (BD time)."""
    from datetime import datetime, timezone, timedelta
    bd_tz = timezone(timedelta(hours=6))
    now_bd = datetime.now(bd_tz)
    today_bd = now_bd.strftime("%Y-%m-%d")
    today_start_utc = now_bd.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.user_id, u.username, u.full_name,
               CASE WHEN u.daily_otp_date = ? THEN u.daily_otp_count ELSE 0 END AS daily_otp_count,
               COALESCE((
                   SELECT SUM(bl.amount)
                   FROM balance_logs bl
                   WHERE bl.user_id = u.user_id
                   AND bl.source = 'otp_reward'
                   AND bl.created_at >= ?
               ), 0) AS daily_reward
               FROM users u
               WHERE u.daily_otp_date = ? AND u.daily_otp_count > 0
               ORDER BY u.daily_otp_count DESC LIMIT ?""",
            (today_bd, today_start_utc, today_bd, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# ============================================================
# ADMIN FUNCTIONS
# ============================================================

async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def add_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_all_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM admins") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# ============================================================
# CATEGORY FUNCTIONS
# ============================================================

async def get_all_categories():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM categories ORDER BY name") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def add_category(name: str, emoji: str = "💥"):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO categories (name, emoji) VALUES (?, ?)", (name.upper(), emoji))
            await db.commit()
            return True
        except Exception:
            return False

async def delete_category(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM categories WHERE name = ?", (name.upper(),))
        await db.commit()

async def get_category_by_name(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM categories WHERE name = ?", (name.upper(),)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# ============================================================
# NUMBER BATCH FUNCTIONS
# ============================================================

async def add_number_batch(country_code, country_name, country_flag, category_id, numbers_list, numbers_per_user, rate_per_otp):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO number_batches 
               (country_code, country_name, country_flag, category_id, numbers_per_user, rate_per_otp, total_numbers, available_numbers)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (country_code, country_name, country_flag, category_id, numbers_per_user, rate_per_otp, len(numbers_list), len(numbers_list))
        )
        batch_id = cursor.lastrowid
        for number in numbers_list:
            await db.execute(
                "INSERT INTO numbers (batch_id, number) VALUES (?, ?)",
                (batch_id, number.strip())
            )
        await db.commit()
        return batch_id

async def get_all_batches():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT nb.*, c.name as category_name, c.emoji as category_emoji
            FROM number_batches nb
            JOIN categories c ON nb.category_id = c.id
            ORDER BY nb.id DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def delete_batch(batch_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM numbers WHERE batch_id = ?", (batch_id,))
        await db.execute("DELETE FROM number_batches WHERE id = ?", (batch_id,))
        await db.execute("DELETE FROM user_assignments WHERE batch_id = ?", (batch_id,))
        await db.commit()

async def toggle_batch_hidden(batch_id: int) -> bool:
    """Batch-এর is_hidden ফ্ল্যাগ টগল করে। রিটার্ন করে নতুন অবস্থা (True=hidden)।"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT is_hidden FROM number_batches WHERE id = ?", (batch_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            new_state = 0 if row["is_hidden"] else 1
        await db.execute("UPDATE number_batches SET is_hidden = ? WHERE id = ?", (new_state, batch_id))
        await db.commit()
        return bool(new_state)

async def get_categories_with_numbers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT DISTINCT c.id, c.name, c.emoji
            FROM categories c
            JOIN number_batches nb ON c.id = nb.category_id
            WHERE nb.available_numbers > 0 AND nb.is_hidden = 0
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_countries_for_category(category_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT nb.id as batch_id, nb.country_name, nb.country_flag, nb.available_numbers,
                   nb.numbers_per_user, nb.country_code, nb.rate_per_otp
            FROM number_batches nb
            JOIN categories c ON nb.category_id = c.id
            WHERE c.name = ? AND nb.available_numbers > 0 AND nb.is_hidden = 0
            ORDER BY nb.country_name
        """, (category_name.upper(),)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_next_number(batch_id: int):
    """Get next available number from a batch."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM numbers WHERE batch_id = ? AND is_used = 0 LIMIT 1",
            (batch_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_next_numbers(batch_id: int, count: int):
    """Get next N available numbers from a batch."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM numbers WHERE batch_id = ? AND is_used = 0 LIMIT ?",
            (batch_id, count)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def assign_number_to_user(user_id: int, number_id: int, batch_id: int, category_name: str, country_name: str, country_flag: str):
    """Assign a single number to a user (call in a loop for multiple)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE numbers SET is_used = 1, assigned_to = ?, assigned_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id, number_id)
        )
        await db.execute(
            "UPDATE number_batches SET available_numbers = available_numbers - 1 WHERE id = ?",
            (batch_id,)
        )
        await db.execute("""
            INSERT INTO user_assignments 
            (user_id, number_id, batch_id, category_name, country_name, country_flag)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, number_id, batch_id, category_name, country_name, country_flag))
        await db.commit()

async def get_user_assignments(user_id: int):
    """Get all active number assignments for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT ua.*, n.number,
                   nb.rate_per_otp, nb.country_code
            FROM user_assignments ua
            JOIN numbers n ON ua.number_id = n.id
            JOIN number_batches nb ON ua.batch_id = nb.id
            WHERE ua.user_id = ?
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_user_assignment(user_id: int):
    """Get first active assignment for a user (backwards compat)."""
    rows = await get_user_assignments(user_id)
    return rows[0] if rows else None

async def release_user_assignment(user_id: int):
    """Release all number assignments for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_assignments WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_status_summary():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.name as category_name, c.emoji, nb.country_flag, nb.country_name, nb.available_numbers
            FROM number_batches nb
            JOIN categories c ON nb.category_id = c.id
            WHERE nb.available_numbers > 0
            ORDER BY c.name, nb.country_name
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# ============================================================
# WITHDRAW FUNCTIONS
# ============================================================

async def create_withdraw_request(user_id: int, username: str, full_name: str, method: str, address: str, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO withdraw_requests (user_id, username, full_name, method, address, amount) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, method, address, amount)
        )
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_pending_withdraw_requests():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM withdraw_requests WHERE status = 'pending' ORDER BY created_at") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def update_withdraw_status(request_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE withdraw_requests SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, request_id)
        )
        if status == "rejected":
            async with db.execute("SELECT user_id, amount FROM withdraw_requests WHERE id = ?", (request_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (row[1], row[0]))
        await db.commit()

async def get_withdraw_request(request_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM withdraw_requests WHERE id = ?", (request_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# ============================================================
# SETTINGS FUNCTIONS
# ============================================================

async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ============================================================
# REQUIRED CHANNELS FUNCTIONS
# ============================================================

async def get_required_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def add_required_channel(channel_link: str, channel_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO required_channels (channel_link, channel_id) VALUES (?, ?)",
            (channel_link, channel_id)
        )
        await db.commit()

async def delete_required_channel(channel_id_db: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM required_channels WHERE id = ?", (channel_id_db,))
        await db.commit()

async def update_channel_id(row_id: int, channel_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE required_channels SET channel_id = ? WHERE id = ?", (channel_id, row_id))
        await db.commit()

# ============================================================
# API MANAGEMENT FUNCTIONS
# ============================================================

async def get_all_apis():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM apis WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def add_api(name: str, api_url: str, api_key: str, api_type: str = "other",
                  username: str = None, password: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO apis (name, api_url, api_key, api_type, username, password) VALUES (?, ?, ?, ?, ?, ?)",
                (name, api_url, api_key, api_type, username, password)
            )
            await db.commit()
            return True
        except Exception:
            return False

async def delete_api(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM apis WHERE name = ?", (name,))
        await db.commit()

async def get_api_by_name(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM apis WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# ============================================================
# OTP FUNCTIONS
# ============================================================

async def save_otp_to_number(number: str, otp: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE numbers SET otp_received = ?, otp_received_at = CURRENT_TIMESTAMP WHERE number = ?",
            (otp, number)
        )
        await db.commit()

async def get_live_traffic_stats(window_minutes: int = 5):
    """Return live OTP traffic stats for the last `window_minutes`.

    Returns a dict: {
        "window_minutes": int,
        "total": int,
        "countries": [{"country_name", "country_flag", "count", "percent"}, ...]  # sorted desc
    }
    """
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT nb.country_name, nb.country_flag, COUNT(*) as cnt
            FROM numbers n
            JOIN number_batches nb ON n.batch_id = nb.id
            WHERE n.otp_received_at IS NOT NULL AND n.otp_received_at >= ?
            GROUP BY nb.country_name, nb.country_flag
            ORDER BY cnt DESC
        """, (since,)) as cursor:
            rows = await cursor.fetchall()

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM numbers WHERE assigned_at IS NOT NULL AND assigned_at >= ?",
            (since,)
        ) as cursor:
            assigned_row = await cursor.fetchone()
            assigned_total = assigned_row["cnt"] if assigned_row else 0

    total = sum(r["cnt"] for r in rows)
    results_sent_percent = round((total / assigned_total) * 100, 1) if assigned_total else 0.0
    countries = []
    for r in rows:
        percent = round((r["cnt"] / total) * 100, 1) if total else 0.0
        countries.append({
            "country_name": r["country_name"],
            "country_flag": r["country_flag"],
            "count": r["cnt"],
            "percent": percent
        })
    return {
        "window_minutes": window_minutes,
        "total": total,
        "results_sent_percent": results_sent_percent,
        "countries": countries
    }

async def get_assignment_by_number(number: str):
    """Find who has this number assigned — checks all user_assignments rows."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cn = number.lstrip("+")
        # সব possible format try করো
        candidates = list(dict.fromkeys([
            cn, "+" + cn,
            cn[1:] if len(cn) > 7 else None,
            cn[2:] if len(cn) > 8 else None,
            cn[3:] if len(cn) > 9 else None,
        ]))
        candidates = [c for c in candidates if c]
        for candidate in candidates:
            async with db.execute("""
                SELECT ua.user_id, ua.batch_id, ua.category_name,
                       ua.country_name, ua.country_flag,
                       n.number, nb.rate_per_otp
                FROM user_assignments ua
                JOIN numbers n ON ua.number_id = n.id
                JOIN number_batches nb ON ua.batch_id = nb.id
                WHERE n.number = ?
            """, (candidate,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        # LIKE suffix match — শেষের ৬-১০ সংখ্যা দিয়ে খোঁজো
        for suffix_len in [10, 9, 8, 7, 6]:
            if len(cn) >= suffix_len:
                suffix = cn[-suffix_len:]
                async with db.execute("""
                    SELECT ua.user_id, ua.batch_id, ua.category_name,
                           ua.country_name, ua.country_flag,
                           n.number, nb.rate_per_otp
                    FROM user_assignments ua
                    JOIN numbers n ON ua.number_id = n.id
                    JOIN number_batches nb ON ua.batch_id = nb.id
                    WHERE n.number LIKE ?
                """, ("%" + suffix,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
    return None

# ============================================================
# OTP DELIVERY LOG — কোনো OTP miss হওয়া আটকাতে
# ============================================================

async def log_otp_event(number: str, otp: str, service: str, sms_text: str, user_id=None) -> int:
    """নতুন scrape হওয়া OTP লগ করো (delivered=0 দিয়ে শুরু), log id রিটার্ন করে।"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO otp_log (number, otp, service, sms_text, user_id) VALUES (?, ?, ?, ?, ?)",
            (number, otp, service, sms_text, user_id)
        )
        await db.commit()
        return cursor.lastrowid

async def mark_otp_delivered(log_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE otp_log SET delivered = 1, delivered_at = CURRENT_TIMESTAMP WHERE id = ?",
            (log_id,)
        )
        await db.commit()

async def set_otp_log_user(log_id: int, user_id: int):
    """পরে assignment খুঁজে পেলে log-এ user_id বসিয়ে দাও।"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE otp_log SET user_id = ? WHERE id = ?", (user_id, log_id))
        await db.commit()

async def increment_otp_attempt(log_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE otp_log SET attempts = attempts + 1 WHERE id = ?", (log_id,))
        await db.commit()

async def mark_otp_permanently_failed(log_id: int):
    """ইউজার বট ব্লক/deactivated করলে এই OTP-এর জন্য retry বন্ধ করে দাও (আর sweep-এ আসবে না)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE otp_log SET permanently_failed = 1 WHERE id = ?", (log_id,))
        await db.commit()

async def get_undelivered_otps(max_age_minutes: int = 1440, max_attempts: int = 300):
    """
    যেসব OTP এখনো delivered হয়নি (এবং খুব পুরোনো না, retry limit পার হয়নি,
    permanently failed মার্ক করা হয়নি), সেগুলো ফেরত দেয় — periodic re-delivery sweep-এর জন্য।
    ডিফল্ট window ২৪ ঘণ্টা ও attempts limit ৩০০ — যাতে সাময়িক নেটওয়ার্ক/API সমস্যায়
    কোনো OTP কখনোই miss হয়ে না যায়।
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"""
            SELECT * FROM otp_log
            WHERE delivered = 0
              AND permanently_failed = 0
              AND attempts < ?
              AND created_at >= datetime('now', ? || ' minutes')
            ORDER BY created_at ASC
        """, (max_attempts, f"-{max_age_minutes}")) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_last_otp_for_user(user_id: int):
    """ইউজারের সবচেয়ে সাম্প্রতিক OTP — 'আমার সর্বশেষ OTP' বাটনের জন্য (push miss হলেও pull করে নিতে পারবে)।"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM otp_log WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_assignments_map() -> dict:
    """সব active assignment এর number → row map — সব format-এ store করে"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT ua.user_id, ua.country_name, ua.country_flag,
                   n.number, nb.rate_per_otp
            FROM user_assignments ua
            JOIN numbers n ON ua.number_id = n.id
            JOIN number_batches nb ON ua.batch_id = nb.id
        """) as cursor:
            rows = await cursor.fetchall()
    result = {}
    for row in rows:
        row = dict(row)
        num = row["number"].lstrip("+")
        # সব format store করো
        result[num] = row
        result["+" + num] = row
        # country code strip versions
        for strip_len in [1, 2, 3]:
            if len(num) > strip_len + 6:
                result[num[strip_len:]] = row
    return result

async def is_referral_notify_on() -> bool:
    """রেফার কমিশন নোটিফিকেশন অন/অফ আছে কিনা চেক করে (ডিফল্ট: অন)"""
    val = await get_setting("referral_notify_enabled")
    return (val or "1") == "1"

async def reward_user_for_otp(user_id: int, amount: float, bot=None, panel_name: str = None):
    """
    panel_name দেওয়া থাকলে এবং সেই প্যানেলের hold ON থাকলে reward সরাসরি balance-এ
    না গিয়ে pending_rewards-এ জমা হবে, hold_days পার হলে main balance-এ আসবে।
    """
    hold = await get_panel_hold_setting(panel_name) if panel_name else None
    if hold and hold["hold_enabled"]:
        await add_pending_reward(user_id, amount, panel_name, hold["hold_days"])
    else:
        await update_user_balance(user_id, amount, source="otp_reward", note=f"OTP reward ৳{amount}")
    await increment_otp_count(user_id)

    # Referrer bonus: প্রতিটি OTP এর জন্য (admin panel থেকে configurable)
    referral_otp_bonus = float(await get_setting("referral_amount") or "0.1")
    user = await get_user(user_id)
    if user and user.get("referred_by"):
        referrer_id = user["referred_by"]
        referrer = await get_user(referrer_id)
        if referrer:
            await update_user_balance(
                referrer_id, referral_otp_bonus,
                source="referral_otp_bonus",
                note=f"Referral OTP bonus from user {user_id}"
            )
            if bot and await is_referral_notify_on():
                try:
                    ref_name = user.get("full_name") or user.get("username") or str(user_id)
                    new_bal = await get_user_balance(referrer_id)
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            f"🎊 <b>অভিনন্দন!</b>\n\n"
                            f"👤 আপনার রেফার <b>{ref_name}</b> একটি OTP রিসিভ করেছে।\n"
                            f"💰 আপনি পেয়েছেন <b>+৳{referral_otp_bonus}</b> বোনাস!\n\n"
                            f"👛 আপনার বর্তমান ব্যালেন্স: <b>৳{new_bal:.2f}</b>"
                        ),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

# ============================================================
# OTP REWARD HOLD SYSTEM
# ============================================================

async def get_panel_hold_setting(panel_name: str):
    """একটা প্যানেলের hold setting রিটার্ন করে; সেট করা না থাকলে None"""
    if not panel_name:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM panel_hold_settings WHERE panel_name = ?", (panel_name,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_panel_names() -> list:
    """API ও Scraper — দুই ধরনের প্যানেলের নাম একসাথে রিটার্ন করে"""
    async with aiosqlite.connect(DB_PATH) as db:
        names = []
        async with db.execute("SELECT name FROM apis") as cursor:
            names += [row[0] for row in await cursor.fetchall()]
        async with db.execute("SELECT name FROM scrapers") as cursor:
            names += [row[0] for row in await cursor.fetchall()]
        return names

async def get_all_panel_hold_settings() -> list:
    """সব প্যানেল + তাদের hold status (সেট করা না থাকলে ডিফল্ট OFF/7 দিন) — এডমিন মেনুর জন্য"""
    panel_names = await get_all_panel_names()
    result = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for name in panel_names:
            async with db.execute(
                "SELECT * FROM panel_hold_settings WHERE panel_name = ?", (name,)
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                result.append(dict(row))
            else:
                result.append({"panel_name": name, "hold_enabled": 0, "hold_days": 7})
    return result

async def set_panel_hold_enabled(panel_name: str, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO panel_hold_settings (panel_name, hold_enabled, hold_days)
               VALUES (?, ?, 7)
               ON CONFLICT(panel_name) DO UPDATE SET hold_enabled = excluded.hold_enabled""",
            (panel_name, 1 if enabled else 0)
        )
        await db.commit()

async def set_panel_hold_days(panel_name: str, days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO panel_hold_settings (panel_name, hold_enabled, hold_days)
               VALUES (?, 0, ?)
               ON CONFLICT(panel_name) DO UPDATE SET hold_days = excluded.hold_days""",
            (panel_name, days)
        )
        await db.commit()

async def add_pending_reward(user_id: int, amount: float, panel_name: str, hold_days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO pending_rewards (user_id, amount, panel_name, release_at)
               VALUES (?, ?, ?, datetime('now', ? || ' days'))""",
            (user_id, amount, panel_name, hold_days)
        )
        await db.commit()

async def get_user_pending_rewards(user_id: int):
    """একজন ইউজারের এখনো hold-এ থাকা reward গুলো (release_at সহ)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM pending_rewards
               WHERE user_id = ? AND status = 'pending'
               ORDER BY release_at ASC""",
            (user_id,)
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def release_matured_rewards() -> list:
    """যেসব pending reward-এর hold সময় পার হয়ে গেছে সেগুলো main balance-এ move করে।
    রিটার্ন করে released reward গুলোর লিস্ট (ইউজারকে নোটিফাই করার জন্য)"""
    released = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_rewards WHERE status = 'pending' AND release_at <= datetime('now')"
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        for row in rows:
            await db.execute(
                "UPDATE users SET balance = ROUND(balance + ?, 2) WHERE user_id = ?",
                (row["amount"], row["user_id"])
            )
            await db.execute(
                "INSERT INTO balance_logs (user_id, amount, source, note) VALUES (?, ?, ?, ?)",
                (row["user_id"], row["amount"], "otp_reward_release",
                 f"Hold reward released — {row['panel_name']}")
            )
            await db.execute(
                "UPDATE pending_rewards SET status = 'released' WHERE id = ?", (row["id"],)
            )
            released.append(row)
        await db.commit()
    return released

# ============================================================
# SCRAPER FUNCTIONS
# ============================================================

async def get_all_scrapers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM scrapers") as cur:
            return [dict(r) for r in await cur.fetchall()]

async def add_scraper(name: str, base_url: str, username: str, password: str,
                      scraper_type: str = "agent") -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO scrapers (name, base_url, username, password, scraper_type) VALUES (?, ?, ?, ?, ?)",
                (name, base_url, username, password, scraper_type)
            )
            await db.commit()
            return True
        except Exception:
            return False

async def get_scrapers_by_type(scraper_type: str = "agent"):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scrapers WHERE scraper_type = ? AND is_active = 1",
            (scraper_type,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def delete_scraper(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM scrapers WHERE name = ?", (name,))
        await db.commit()

async def get_scraper_by_name(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM scrapers WHERE name = ?", (name,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
