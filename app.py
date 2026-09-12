"""
====================================================
  SMS OTP PREMIUM TELEGRAM BOT — UPDATED VERSION
  Features: Multi-number Get, Leaderboard, ৳ Currency,
  OTP Count Ranking, Full Admin Panel, API Integration
====================================================
"""

import asyncio
import logging
import os
import re
from datetime import datetime

from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

import database as db
from config import BOT_TOKEN, OWNER_ID, COUNTRY_CODES, OTP_GROUP_ID, get_country_iso2
from keyboards import (
    main_menu_keyboard,
    services_keyboard,
    countries_keyboard,
    wallet_card_keyboard,
    payment_method_keyboard,
    support_keyboard,
    leaderboard_keyboard,
    admin_panel_keyboard,
    settings_keyboard,
    category_management_keyboard,
    manage_numbers_keyboard,
    withdraw_action_keyboard,
    req_channels_keyboard,
    api_management_keyboard,
    api_system_keyboard,
    api_type_keyboard,
    scraping_system_keyboard,
    agent_panel_keyboard,
    client_panel_keyboard,
    evs_panel_keyboard,
    crapi_panel_keyboard,
    add_numbers_service_keyboard,
    broadcast_confirm_keyboard,
    channel_join_keyboard,
    numbers_assigned_keyboard,
    withdraw_method_toggle_keyboard,
    panel_hold_menu_keyboard,
)
from api_handler import start_api_polling, check_api_health, get_service_emoji
from scraper import start_scraper_polling

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# CONVERSATION STATES
# ============================================================
(
    STATE_ADD_NUM_WAITING_NUMBERS,
    STATE_ADD_NUM_WAITING_CATEGORY,
    STATE_ADD_NUM_WAITING_PER_USER,
    STATE_ADD_NUM_WAITING_RATE,
    STATE_WITHDRAW_WAITING_ADDRESS,
    STATE_WITHDRAW_WAITING_AMOUNT,
    STATE_SETTING_WAITING_VALUE,
    STATE_ADD_ADMIN_WAITING_ID,
    STATE_REMOVE_ADMIN_WAITING_ID,
    STATE_BROADCAST_WAITING_MSG,
    STATE_ADD_CATEGORY_WAITING_NAME,
    STATE_ADD_CHANNEL_WAITING_LINK,
    STATE_API_WAITING_NAME,
    STATE_API_WAITING_URL,
    STATE_API_WAITING_KEY,
    STATE_SCRAPER_WAITING_NAME,
    STATE_SCRAPER_WAITING_URL,
    STATE_SCRAPER_WAITING_USERNAME,
    STATE_SCRAPER_WAITING_PASSWORD,
    STATE_SETWALLET_WAITING_ADDRESS,
) = range(20)

# ============================================================
# HELPERS
# ============================================================

def InlineKeyBoardBack():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="primary")]])

def InlineKeyboardMarkupBack():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="primary")]])

def detect_country(number: str):
    clean = re.sub(r'[\s\-\+]', '', number)
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
        if clean.startswith(code):
            info = COUNTRY_CODES[code]
            return code, info["name"], info["flag"]
    return None, "Unknown", "🌍"

def parse_numbers_from_text(text: str) -> list:
    lines = text.strip().splitlines()
    numbers = []
    for line in lines:
        line = line.strip()
        if line and re.search(r'\d{6,}', line):
            numbers.append(line)
    return numbers

PAYMENT_PROOF_CHANNEL_ID = -1003792985653
PAYMENT_PROOF_CHANNEL_LINK = "https://t.me/payment_update3"

async def _check_payment_proof_membership(bot, user_id: int) -> bool:
    """Payment proof channel-এ join আছে কিনা চেক করো"""
    try:
        raw_id = await db.get_setting("payment_proof_channel_id")
        channel_id = int(raw_id) if raw_id else PAYMENT_PROOF_CHANNEL_ID
    except Exception:
        channel_id = PAYMENT_PROOF_CHANNEL_ID
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception:
        return True  # চেক করতে না পারলে allow করো

async def _send_proof_channel_join_prompt(update):
    """Payment proof channel join না করলে এই message দেখাবে"""
    try:
        proof_link = await db.get_setting("payment_proof_channel_link") or PAYMENT_PROOF_CHANNEL_LINK
    except Exception:
        proof_link = PAYMENT_PROOF_CHANNEL_LINK

    await update.message.reply_text(
        "🔒 <b>এই ফিচার ব্যবহার করতে আমাদের Payment Proof Channel-এ Join করুন!</b>\n\n"
        "✅ Join করার পর <b>Verify</b> বাটনে চাপুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Join Payment Proof Channel", url=proof_link, style="success")],
            [InlineKeyboardButton("✅ Verify", callback_data="verify_proof_channel", style="primary")],
        ])
    )


async def get_disabled_methods() -> list:
    try:
        val = await db.get_setting("disabled_withdraw_methods") or ""
        return [m.strip() for m in val.split(",") if m.strip()]
    except Exception:
        return []

async def is_withdraw_system_on() -> bool:
    try:
        val = await db.get_setting("withdraw_system_enabled") or "1"
        return val.strip() == "1"
    except Exception:
        return True

async def check_channel_membership(bot: Bot, user_id: int, channels: list) -> bool:
    for ch in channels:
        channel_id = ch.get("channel_id") if isinstance(ch, dict) else ch["channel_id"]
        channel_link = ch.get("channel_link") if isinstance(ch, dict) else ch["channel_link"]
        if not channel_id:
            try:
                username = channel_link.strip().rstrip('/').split('/')[-1]
                chat = await bot.get_chat(f"@{username}")
                channel_id = str(chat.id)
                await db.update_channel_id(ch.get("id") if isinstance(ch, dict) else ch["id"], channel_id)
            except Exception:
                continue
        try:
            member = await bot.get_chat_member(chat_id=int(channel_id), user_id=user_id)
            if member.status in ["left", "kicked", "banned"]:
                return False
        except Exception:
            pass
    return True

async def is_user_admin_or_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or await db.is_admin(user_id)

async def get_main_menu(user_id: int):
    is_adm = await is_user_admin_or_owner(user_id)
    return main_menu_keyboard(is_adm)

def _build_number_text(assignments: list) -> str:
    """Build the text block showing all assigned numbers (full, no +)."""
    lines = []
    for a in assignments:
        number = re.sub(r'[\s\-\+]', '', str(a["number"]))
        lines.append(f"📟 {number}")
    return "\n".join(lines)

# ============================================================
# /start
# ============================================================

def _build_welcome_text(bot_name: str, full_name: str) -> str:
    safe_name = full_name or "Friend"
    return (
        f"⚡ <b>{bot_name.upper()}</b>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"🔐 Welcome, <b>{safe_name}</b>!\n\n"
        f"✅ Get instant virtual numbers\n"
        f"🔔 OTP auto-delivered to DM\n"
        f"🎉 Invite friends & earn bonus\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"⚡ Press Get Number to start!"
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    full_name = user.full_name or ""

    referred_by = None
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != user_id:
                referred_by = ref_id
        except ValueError:
            pass

    existing = await db.get_user(user_id)
    if not existing:
        await db.add_user(user_id, username, full_name, referred_by)
        if referred_by:
            await db.increment_referral_count(referred_by)
            if await db.is_referral_notify_on():
                try:
                    ref_amount = float(await db.get_setting("referral_amount") or "0.1")
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=f"🎉 <b>নতুন রেফার!</b>\n\n👤 <b>{full_name}</b> আপনার লিংক দিয়ে জয়েন করেছে।\n⏳ সে যতবার OTP রিসিভ করবে, ততবার আপনি {ref_amount:.2f}৳ বোনাস পাবেন!",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

    channels = await db.get_required_channels()
    if channels:
        if not await check_channel_membership(context.bot, user_id, channels):
            await update.message.reply_text(
                "📢 <b>Please join the required channels to use this bot!</b>\n\nAfter joining, tap <b>Verify</b> below.",
                parse_mode=ParseMode.HTML,
                reply_markup=channel_join_keyboard(channels)
            )
            return

    bot_info = await context.bot.get_me()
    await update.message.reply_text(
        _build_welcome_text(bot_info.first_name, full_name),
        parse_mode=ParseMode.HTML,
        reply_markup=await get_main_menu(user_id)
    )

# ============================================================
# VERIFY CHANNEL JOIN
# ============================================================

async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    channels = await db.get_required_channels()
    if await check_channel_membership(context.bot, user_id, channels):
        bot_info = await context.bot.get_me()
        full_name = query.from_user.full_name or ""
        await query.message.reply_text(
            _build_welcome_text(bot_info.first_name, full_name),
            parse_mode=ParseMode.HTML,
            reply_markup=await get_main_menu(user_id)
        )
        await query.message.delete()
    else:
        await query.answer("❌ You haven't joined all channels yet!", show_alert=True)

async def verify_proof_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Payment Proof Channel join verify করো"""
    query = update.callback_query
    user_id = query.from_user.id
    joined = await _check_payment_proof_membership(context.bot, user_id)
    if joined:
        await query.answer("✅ Verified! এখন ব্যবহার করতে পারবেন।", show_alert=True)
        await query.message.delete()
    else:
        await query.answer("❌ এখনো Join করেননি! Join করে আবার চেষ্টা করুন।", show_alert=True)

# ============================================================
# GET NUMBER
# ============================================================

async def handle_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = await db.get_categories_with_numbers()
    if not cats:
        await update.message.reply_text(
            "⚠️ <b>No service available right now.</b>\n\nPlease check back later.",
            parse_mode=ParseMode.HTML
        )
        return
    cat_list = [{"name": c["name"], "emoji": c["emoji"]} for c in cats]
    await update.message.reply_text(
        "⚙️ <b>Select a Service:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=services_keyboard(cat_list)
    )

# ============================================================
# MY LAST OTP (self-serve pull — push DM miss হলেও কাজে দেয়)
# ============================================================

async def handle_my_last_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = await db.get_last_otp_for_user(user_id)
    if not row:
        await update.message.reply_text(
            "😔 আপনার নামে এখনো কোনো OTP পাওয়া যায়নি।",
            reply_markup=await get_main_menu(user_id),
        )
        return
    status = "✅ ডেলিভার হয়েছে" if row["delivered"] else "🔁 এইমাত্র পাঠানো হলো"
    text = (
        f"📥 <b>আপনার সর্বশেষ OTP</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 <b>Number:</b> {row['number']}\n"
        f"{get_service_emoji(row['service'])} <b>Service:</b> {row['service']}\n"
        f"🔑 <b>OTP Code:</b> <code>{row['otp']}</code>\n"
        f"🕐 <b>সময়:</b> {row['created_at']}\n"
        f"{status}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=await get_main_menu(user_id))
    if not row["delivered"]:
        await db.mark_otp_delivered(row["id"])


# ============================================================
# BALANCE
# ============================================================

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = await db.get_user_balance(user_id)
    user_row = await db.get_user(user_id)
    referrals = user_row["referral_count"] if user_row else 0
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_amount = float(await db.get_setting("referral_amount") or "0.1")
    ref_amount_500 = ref_amount * 500

    def fmt(n):
        return f"{n:.2f}".rstrip("0").rstrip(".") if "." in f"{n:.2f}" else f"{n}"

    pending = await db.get_user_pending_rewards(user_id)
    hold_line = ""
    if pending:
        total_hold = sum(p["amount"] for p in pending)
        nearest = pending[0]["release_at"]  # ordered ASC already
        hold_line = (
            f"🔒 <b>হোল্ডে আছে:</b> {total_hold:.2f}৳\n"
            f"⏳ <b>সবচেয়ে কাছেরটা রিলিজ হবে:</b> {nearest} (UTC)\n\n"
        )

    text = (
        f"👥 <b>রেফার করুন ও ইনকাম করুন</b>\n\n"
        f"💰 <b>আপনার ব্যালেন্স:</b> {balance:.2f}৳\n"
        f"{hold_line}"
        f"👤 <b>মোট রেফার:</b> {referrals}\n\n"
        f"🔗 <b>আপনার রেফারেল লিংক:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📌 আপনি যাকে রেফার করবেন, সে যদি ১টি OTP রিসিভ করে, আপনি পাবেন {ref_amount:.2f}৳।\n"
        f"🎯 আর সে যদি ৫০০টি OTP রিসিভ করে, আপনি পাবেন {ref_amount_500:.2f}৳।\n\n"
        f"🔥 তাই বেশি ইনকাম করতে চাইলে বেশি বেশি রেফার করুন!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Share Link", url=f"https://t.me/share/url?url={ref_link}", style="primary")]
    ])
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# ============================================================
# WITHDRAW (Main Menu)
# ============================================================

async def _build_wallet_card_text(user_id: int) -> str:
    balance = await db.get_user_balance(user_id)
    total_withdrawn = await db.get_total_withdrawn(user_id)
    user_row = await db.get_user(user_id)
    referrals = user_row["referral_count"] if user_row else 0
    referral_earnings = await db.get_total_referral_earnings(user_id)
    min_withdraw = float(await db.get_setting("min_withdraw") or "0.5")
    wallet = await db.get_user_wallet(user_id)
    wallet_line = f"{wallet['method']}: <code>{wallet['address']}</code>" if wallet else "<i>Not set yet</i>"

    pending = await db.get_user_pending_rewards(user_id)
    hold_line = ""
    if pending:
        total_hold = sum(p["amount"] for p in pending)
        nearest = pending[0]["release_at"]
        hold_line = f"🔒 <b>Hold Balance:</b> {total_hold:.2f}৳ (পরের রিলিজ: {nearest} UTC)\n"

    return (
        f"💰 <b>Wallet</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>User ID:</b> {user_id}\n"
        f"💵 <b>Balance:</b> {balance:.2f}৳\n"
        f"{hold_line}"
        f"📤 <b>Total Withdrawn:</b> {total_withdrawn:.2f}৳\n"
        f"👥 <b>Referrals:</b> {referrals}\n"
        f"🎁 <b>Refer Reward:</b> {referral_earnings:.2f}৳\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Minimum Withdraw:</b> {min_withdraw:.2f}৳\n"
        f"🆓 <b>Fee:</b> Free 0%\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Wallet:</b> {wallet_line}"
    )

async def handle_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = await _build_wallet_card_text(user_id)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_card_keyboard()
    )

# ============================================================
# AVAILABLE COUNTRY
# ============================================================

async def handle_available_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = await db.get_status_summary()
    if not summary:
        await update.message.reply_text(
            "🌍 <b>Available Country</b>\n\n❌ No countries available currently.",
            parse_mode=ParseMode.HTML
        )
        return
    lines = []
    for row in summary:
        lines.append(f"{row['category_name']} | {row['country_flag']} {row['country_name']} | {row['available_numbers']}")
    await update.message.reply_text(
        "🌍 <b>Available Country</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML
    )

# ============================================================
# LIVE TRAFFIC
# ============================================================

def _build_leaderboard_text(rows: list, title: str = "Today") -> str:
    from datetime import datetime, timezone, timedelta
    bd_tz = timezone(timedelta(hours=6))
    now_bd = datetime.now(bd_tz)
    midnight = now_bd.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    hours_left = int((midnight - now_bd).seconds / 3600)

    lines = [
        f"🏆 <b>Daily Leaderboard — {title} Top 10</b>",
        f"⏳ {hours_left} ঘন্টা পর রিসেট\n",
        "<code>নাম          OTP   ৳ Reward</code>",
        "<code>─────────────────────────</code>",
    ]
    medals = ["🥇", "🥈", "🥉"]

    if not rows:
        lines.append("❌ কোনো OTP রিসিভ হয়নি।")
    else:
        for i, row in enumerate(rows[:10], 1):
            count  = row.get("daily_otp_count", 0)
            reward = float(row.get("daily_reward", 0) or 0)
            uid    = row["user_id"]
            name   = row.get("full_name") or row.get("username") or f"User{uid}"
            short_name = (name[:8] + "..") if len(name) > 8 else name
            medal = medals[i-1] if i <= 3 else f"{i}. "
            name_col   = short_name.ljust(10)
            otp_col    = str(count).rjust(4)
            reward_col = f"{reward:.2f}".rjust(7)
            lines.append(f"<code>{medal}{name_col}{otp_col}  {reward_col}৳</code>")

    return "\n".join(lines)


async def _get_yesterday_leaderboard(limit: int = 10) -> list:
    from datetime import datetime, timezone, timedelta
    import aiosqlite
    bd_tz = timezone(timedelta(hours=6))
    yesterday_bd = (datetime.now(bd_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT u.user_id, u.username, u.full_name,
               COALESCE((
                   SELECT SUM(bl.amount) FROM balance_logs bl
                   WHERE bl.user_id = u.user_id AND bl.source = 'otp_reward'
                   AND DATE(bl.created_at) = ?
               ), 0) AS daily_reward,
               COALESCE((
                   SELECT COUNT(*) FROM balance_logs bl
                   WHERE bl.user_id = u.user_id AND bl.source = 'otp_reward'
                   AND DATE(bl.created_at) = ?
               ), 0) AS daily_otp_count
            FROM users u
            WHERE daily_otp_count > 0
            ORDER BY daily_otp_count DESC LIMIT ?
        """, (yesterday_bd, yesterday_bd, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db.get_daily_leaderboard(limit=10)
    text = _build_leaderboard_text(rows)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_keyboard()
    )

async def leaderboard_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 Refreshed")
    rows = await db.get_daily_leaderboard(limit=10)
    text = _build_leaderboard_text(rows, title="Today")
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=leaderboard_keyboard("today"))
    except Exception:
        pass

async def leaderboard_today_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = await db.get_daily_leaderboard(limit=10)
    text = _build_leaderboard_text(rows, title="Today")
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=leaderboard_keyboard("today"))
    except Exception:
        pass

async def leaderboard_yesterday_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = await _get_yesterday_leaderboard(limit=10)
    text = _build_leaderboard_text(rows, title="Yesterday")
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=leaderboard_keyboard("yesterday"))
    except Exception:
        pass

async def leaderboard_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass

async def leaderboard_my_rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    rows = await db.get_daily_leaderboard(limit=1000)
    rank = None
    my_count = 0
    for i, row in enumerate(rows, 1):
        if row["user_id"] == user_id:
            rank = i
            my_count = row.get("daily_otp_count", 0)
            break
    if rank:
        await query.answer(f"📍 আপনার অবস্থান: #{rank} ({my_count} OTP)", show_alert=True)
    else:
        await query.answer("📍 আপনি আজ এখনো কোনো OTP রিসিভ করেননি।", show_alert=True)

# ============================================================
# STATUS
# ============================================================

async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_username = await db.get_setting("support_username")
    await update.message.reply_text(
        "☎️ <b>Contact support:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=support_keyboard(support_username)
    )

def _format_batch_line(b: dict) -> str:
    status = "🙈 <b>HIDDEN</b>" if b.get("is_hidden") else "🙉 Visible"
    return (
        f"<b>ID {b['id']}</b> | {b['country_flag']} {b['country_name']} | {status}\n"
        f"📂 {b['category_emoji']} {b['category_name']}\n"
        f"📅 {b['added_at'][:10]} | Total: {b['total_numbers']} | Avail: {b['available_numbers']}\n"
        f"👤 Per user: {b['numbers_per_user']} | 💵 Rate: {b['rate_per_otp']:.2f}৳"
    )

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = await db.get_status_summary()
    if not summary:
        await update.message.reply_text("📊 <b>Status</b>\n\n❌ No numbers available currently.", parse_mode=ParseMode.HTML)
        return
    lines = []
    for row in summary:
        lines.append(f"{row['category_name']} | {row['country_flag']} {row['country_name']} | {row['available_numbers']}")
    await update.message.reply_text("📊 <b>Status</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)

# ============================================================
# ADMIN PANEL
# ============================================================

async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_user_admin_or_owner(user_id):
        await update.message.reply_text("❌ Access denied.")
        return
    live_users = await db.count_live_users()
    withdraw_on = await is_withdraw_system_on()
    referral_notify_on = await db.is_referral_notify_on()
    await update.message.reply_text(
        f"🛠 <b>Admin Panel</b> [Live Users: {live_users}]",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_keyboard(withdraw_on=withdraw_on, referral_notify_on=referral_notify_on)
    )

# ============================================================
# WITHDRAW FLOW
# ============================================================

async def set_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disabled = await get_disabled_methods()
    await query.edit_message_text(
        "💳 <b>Set Payment Method</b>\n\nSelect your preferred payment method:",
        parse_mode=ParseMode.HTML,
        reply_markup=payment_method_keyboard(disabled)
    )

async def set_wallet_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("setwallet_", "")

    # Disabled method check
    disabled = await get_disabled_methods()
    if method in disabled:
        await query.answer(f"❌ {method} বর্তমানে বন্ধ আছে!", show_alert=True)
        return

    context.user_data["setwallet_method"] = method
    context.user_data["withdraw_state"] = STATE_SETWALLET_WAITING_ADDRESS
    await query.edit_message_text(
        f"💳 <b>Set Wallet — {method}</b>\n\n📨 Please send your <b>{method} account number / address:</b>",
        parse_mode=ParseMode.HTML
    )

async def do_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Withdraw system বন্ধ আছে কিনা check
    if not await is_withdraw_system_on():
        await query.answer("❌ Withdraw এখন বন্ধ আছে! পরে আবার চেষ্টা করুন।", show_alert=True)
        return

    wallet = await db.get_user_wallet(user_id)
    if not wallet:
        await query.message.reply_text(
            "⚠️ <b>Please set your wallet first before withdrawing.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_card_keyboard()
        )
        return
    context.user_data["withdraw_state"] = STATE_WITHDRAW_WAITING_AMOUNT
    min_w = float(await db.get_setting("min_withdraw") or "0.5")
    await query.message.reply_text(
        f"💵 <b>Enter the amount you want to withdraw:</b>\n\n"
        f"💳 <b>To:</b> {wallet['method']} — <code>{wallet['address']}</code>\n"
        f"📉 Minimum: <b>{min_w:.2f}৳</b>",
        parse_mode=ParseMode.HTML
    )

async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await query.message.reply_text("🏠 <b>Main Menu</b>", parse_mode=ParseMode.HTML, reply_markup=await get_main_menu(user_id))
    await query.message.delete()

async def handle_withdraw_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("withdraw_state")

    if state == STATE_SETWALLET_WAITING_ADDRESS:
        method = context.user_data.get("setwallet_method", "Unknown")
        address = update.message.text.strip()
        await db.set_user_wallet(user_id, method, address)
        context.user_data["withdraw_state"] = None
        await update.message.reply_text(
            f"✅ <b>Wallet Set Successfully!</b>\n\n💳 <b>Method:</b> {method}\n📨 <b>Address:</b> {address}\n\nYou can now withdraw anytime.",
            parse_mode=ParseMode.HTML
        )

    elif state == STATE_WITHDRAW_WAITING_AMOUNT:
        try:
            amount = float(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("❌ <b>Invalid amount. Please enter a number.</b>", parse_mode=ParseMode.HTML)
            return

        min_w = float(await db.get_setting("min_withdraw") or "0.5")
        balance = await db.get_user_balance(user_id)

        if amount < min_w:
            await update.message.reply_text(f"❌ <b>Amount too low!</b> Minimum is <b>{min_w:.2f}৳</b>", parse_mode=ParseMode.HTML)
            return
        if amount > balance:
            await update.message.reply_text(f"❌ <b>Insufficient balance!</b> Your balance: <b>{balance:.2f}৳</b>", parse_mode=ParseMode.HTML)
            return

        wallet = await db.get_user_wallet(user_id)
        method = wallet["method"] if wallet else "Unknown"
        address = wallet["address"] if wallet else ""
        user = update.effective_user

        await db.create_withdraw_request(user_id, user.username or "", user.full_name or "", method, address, amount)
        context.user_data["withdraw_state"] = None

        await update.message.reply_text(
            f"✅ <b>Withdraw Request Submitted!</b>\n\n💳 <b>Method:</b> {method}\n📨 <b>Address:</b> {address}\n💵 <b>Amount:</b> {amount:.2f}৳\n\n⏳ Please wait for admin approval.",
            parse_mode=ParseMode.HTML,
            reply_markup=await get_main_menu(user_id)
        )

# ============================================================
# SERVICE / COUNTRY / NUMBER CALLBACKS
# ============================================================

async def service_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("service_", "")
    context.user_data["selected_service"] = service_name
    countries = await db.get_countries_for_category(service_name)
    if not countries:
        await query.edit_message_text("⚠️ <b>No numbers available for this service right now.</b>", parse_mode=ParseMode.HTML)
        return
    await query.edit_message_text(
        f"💥 <b>Select country for {service_name}:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=countries_keyboard(countries, service_name)
    )

async def back_to_services_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cats = await db.get_categories_with_numbers()
    if not cats:
        await query.edit_message_text("⚠️ No service available right now.")
        return
    cat_list = [{"name": c["name"], "emoji": c["emoji"]} for c in cats]
    await query.edit_message_text("⚙️ <b>Select a Service:</b>", parse_mode=ParseMode.HTML, reply_markup=services_keyboard(cat_list))

async def country_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    parts = query.data.replace("country_", "").split("_", 1)
    batch_id = int(parts[0])
    category_name = parts[1] if len(parts) > 1 else ""
    context.user_data["selected_service"] = category_name
    context.user_data["selected_batch"] = batch_id

    # Get batch info
    batches = await db.get_all_batches()
    batch = next((b for b in batches if b["id"] == batch_id), None)
    if not batch:
        await query.edit_message_text("❌ Error fetching batch info.")
        return

    country_name = batch["country_name"]
    country_flag = batch["country_flag"]
    iso2 = get_country_iso2(country_name)
    numbers_per_user = batch.get("numbers_per_user", 1)

    # আগে কোনো number pending থাকলে সেটা grace period-এ save করে রাখো,
    # যাতে সেই number-এ দেরিতে আসা OTP-ও মিস না হয় — তারপর assignment release করো
    old_assignments = await db.get_user_assignments(user_id)
    old_numbers = [a["number"] for a in old_assignments if a.get("number")]
    if old_numbers:
        old = old_assignments[0]
        await db.save_released_numbers(
            user_id, old_numbers,
            rate_per_otp=old.get("rate_per_otp", 0),
            country_name=old.get("country_name", "Unknown"),
            country_flag=old.get("country_flag", "🌍"),
            category_name=old.get("category_name", ""),
        )
    await db.release_user_assignment(user_id)

    # Get N numbers from batch
    number_rows = await db.get_next_numbers(batch_id, numbers_per_user)
    if not number_rows:
        await query.edit_message_text("⚠️ <b>No numbers available for this country.</b>", parse_mode=ParseMode.HTML)
        return

    # Assign each number
    for nr in number_rows:
        await db.assign_number_to_user(user_id, nr["id"], batch_id, category_name, country_name, country_flag)

    # Fetch all assignments with country_code
    assignments = await db.get_user_assignments(user_id)

    otp_link = await db.get_setting("otp_group_link") or "https://t.me/otp_group"
    kb = await numbers_assigned_keyboard(assignments, otp_link, show_cc=context.user_data.get("show_cc", True))

    count = len(assignments)

    await query.edit_message_text(
        f"🌎 <b>Country:</b> {country_flag} {country_name} ({iso2})\n\n"
        f"⌛ <b>Waiting for OTP</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

async def change_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    assignments = await db.get_user_assignments(user_id)
    if not assignments:
        await query.answer("❌ No active assignment found.", show_alert=True)
        return

    first = assignments[0]
    batch_id = first["batch_id"]
    country_name = first["country_name"]
    country_flag = first["country_flag"]
    iso2 = get_country_iso2(country_name)
    category_name = first["category_name"]

    # Get how many were originally assigned
    batches = await db.get_all_batches()
    batch = next((b for b in batches if b["id"] == batch_id), None)
    numbers_per_user = batch.get("numbers_per_user", 1) if batch else 1

    # Release old assignments — grace period-এর জন্য numbers save করো (rate সহ, যাতে reward miss না হয়)
    old_numbers = [a["number"] for a in assignments if a.get("number")]
    if old_numbers:
        old_rate = batch.get("rate_per_otp", 0) if batch else 0
        await db.save_released_numbers(
            user_id, old_numbers,
            rate_per_otp=old_rate,
            country_name=country_name,
            country_flag=country_flag,
            category_name=category_name,
        )
    await db.release_user_assignment(user_id)

    # Assign new numbers
    number_rows = await db.get_next_numbers(batch_id, numbers_per_user)
    if not number_rows:
        await query.edit_message_text("⚠️ <b>No more numbers available for this country.</b>", parse_mode=ParseMode.HTML)
        return

    for nr in number_rows:
        await db.assign_number_to_user(user_id, nr["id"], batch_id, category_name, country_name, country_flag)

    assignments = await db.get_user_assignments(user_id)
    otp_link = await db.get_setting("otp_group_link") or "https://t.me/otp_group"
    kb = await numbers_assigned_keyboard(assignments, otp_link, show_cc=context.user_data.get("show_cc", True))

    count = len(assignments)

    await query.edit_message_text(
        f"🌎 <b>Country:</b> {country_flag} {country_name} ({iso2})\n\n"
        f"⌛ <b>Waiting for OTP</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

async def change_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    assignments = await db.get_user_assignments(user_id)
    service = assignments[0]["category_name"] if assignments else context.user_data.get("selected_service")

    # আগের numbers grace period-এ save করে রাখো, দেরিতে আসা OTP মিস আটকাতে
    old_numbers = [a["number"] for a in assignments if a.get("number")]
    if old_numbers:
        old = assignments[0]
        await db.save_released_numbers(
            user_id, old_numbers,
            rate_per_otp=old.get("rate_per_otp", 0),
            country_name=old.get("country_name", "Unknown"),
            country_flag=old.get("country_flag", "🌍"),
            category_name=old.get("category_name", ""),
        )
    await db.release_user_assignment(user_id)

    if service:
        countries = await db.get_countries_for_category(service)
        await query.edit_message_text(
            f"💥 <b>Select country for {service}:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=countries_keyboard(countries, service)
        )
    else:
        await back_to_services_callback(update, context)

async def copy_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    safe = query.data[len("copy_number_"):]
    number = safe.replace("PLUS", "+")
    await query.answer(f"📋 {number}", show_alert=False)
    try:
        await query.message.reply_text(f"<code>{number}</code>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ============================================================
# BROADCAST
# ============================================================

async def _send_one(bot, user, message):
    """একজন user-কে message পাঠাও"""
    try:
        uid = user["user_id"]
        if hasattr(message, 'photo') and message.photo:
            await bot.send_photo(chat_id=uid, photo=message.photo[-1].file_id,
                                 caption=message.caption or "", parse_mode=ParseMode.HTML)
        elif hasattr(message, 'video') and message.video:
            await bot.send_video(chat_id=uid, video=message.video.file_id,
                                 caption=message.caption or "", parse_mode=ParseMode.HTML)
        elif hasattr(message, 'animation') and message.animation:
            await bot.send_animation(chat_id=uid, animation=message.animation.file_id,
                                     caption=message.caption or "", parse_mode=ParseMode.HTML)
        elif hasattr(message, 'text') and message.text:
            await bot.send_message(chat_id=uid, text=message.text, parse_mode=ParseMode.HTML)
        else:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat_id,
                                   message_id=message.message_id)
        return True
    except Exception:
        return False

async def _broadcast_worker(bot: Bot, message, status_chat_id: int, status_msg_id: int):
    """Background-এ parallel broadcast করে — bot hang হবে না"""
    users = await db.get_all_users()
    total   = len(users)
    success = 0
    failed  = 0
    CHUNK   = 25    # একসাথে কতজনকে parallel-এ পাঠাবে
    DELAY   = 1.0   # প্রতিটা chunk-এর পর বিরতি (Telegram: 30 msg/sec limit)

    for i in range(0, total, CHUNK):
        chunk = users[i:i + CHUNK]
        # Parallel send
        results = await asyncio.gather(*[_send_one(bot, u, message) for u in chunk],
                                       return_exceptions=True)
        for r in results:
            if r is True:
                success += 1
            else:
                failed += 1

        # Rate limit — ১ সেকেন্ড অপেক্ষা
        await asyncio.sleep(DELAY)

        # প্রতি ১০০ জন পর status update
        if (i + CHUNK) % 100 == 0 or i + CHUNK >= total:
            try:
                pct = int((i + CHUNK) / total * 100)
                await bot.edit_message_text(
                    chat_id=status_chat_id,
                    message_id=status_msg_id,
                    text=f"📢 <b>Broadcasting...</b> {pct}%\n\n"
                         f"👥 Total: {total}\n"
                         f"✅ Sent: {success}\n"
                         f"❌ Failed: {failed}\n"
                         f"⏳ Remaining: {max(0, total - i - CHUNK)}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    # Final
    try:
        await bot.edit_message_text(
            chat_id=status_chat_id,
            message_id=status_msg_id,
            text=f"✅ <b>Broadcast Complete!</b>\n\n"
                 f"👥 Total: {total}\n"
                 f"✅ Success: {success}\n"
                 f"❌ Failed: {failed}",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


async def _background_broadcast(bot: Bot, message):
    """Stock broadcast-এর জন্য background task — status message ছাড়া"""
    users = await db.get_all_users()
    CHUNK = 25
    for i in range(0, len(users), CHUNK):
        chunk = users[i:i+CHUNK]
        await asyncio.gather(*[
            _send_one(bot, u, message) for u in chunk
        ], return_exceptions=True)
        await asyncio.sleep(1.0)

async def do_broadcast(bot: Bot, message, query=None):
    """Broadcast trigger — background task শুরু করে, bot hang হবে না"""
    users = await db.get_all_users()
    total = len(users)

    # Status message পাঠাও
    if query:
        status_msg = await query.edit_message_text(
            f"📢 <b>Broadcast শুরু হচ্ছে...</b>\n\n"
            f"👥 Total Users: {total}\n"
            f"⏳ Background-এ চলছে — bot স্বাভাবিক থাকবে।",
            parse_mode=ParseMode.HTML
        )
        # Background task — non-blocking
        asyncio.create_task(
            _broadcast_worker(bot, message, status_msg.chat.id, status_msg.message_id)
        )

# ============================================================
# ADD NUMBERS — STEP HANDLERS
# ============================================================

async def _add_numbers_step1(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    numbers = parse_numbers_from_text(text)
    if not numbers:
        await update.message.reply_text("❌ No valid numbers found. Please send again.")
        return

    context.user_data["add_num_numbers"] = numbers
    country_code, country_name, country_flag = detect_country(numbers[0])
    context.user_data["add_num_country_code"] = country_code
    context.user_data["add_num_country_name"] = country_name
    context.user_data["add_num_country_flag"] = country_flag
    context.user_data["add_num_step"] = "waiting_category"

    categories = await db.get_all_categories()
    cat_list = [{"name": c["name"], "emoji": c["emoji"]} for c in categories]

    await update.message.reply_text(
        f"✅ Detected <b>{len(numbers)}</b> numbers.\n"
        f"Detected country: {country_flag} <b>{country_name}</b> (+{country_code})\n\n"
        f"<b>Step 2:</b> Select a category for these numbers:",
        parse_mode=ParseMode.HTML,
        reply_markup=add_numbers_service_keyboard(cat_list)
    )

async def _add_numbers_step3(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        per_user = int(text)
    except ValueError:
        await update.message.reply_text("❌ Please send a valid integer. Example: 1")
        return
    context.user_data["add_num_per_user"] = per_user
    context.user_data["add_num_step"] = "waiting_rate"
    await update.message.reply_text(
        "📊 <b>Step 4:</b> Send rate per successful OTP (৳).\n"
        "Example: 0.50\n\n"
        "<i>(If you set 0, OTPs will not give any monetary reward.)</i>",
        parse_mode=ParseMode.HTML
    )

async def _add_numbers_step4(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        rate = float(re.sub(r'[^\d.]', '', text))
    except ValueError:
        await update.message.reply_text("❌ Please send a valid number (e.g. 0.50).")
        return

    numbers      = context.user_data.get("add_num_numbers", [])
    category_name = context.user_data.get("add_num_category", "")
    country_code  = context.user_data.get("add_num_country_code", "")
    country_name  = context.user_data.get("add_num_country_name", "Unknown")
    country_flag  = context.user_data.get("add_num_country_flag", "🌍")
    per_user      = context.user_data.get("add_num_per_user", 1)

    cat = await db.get_category_by_name(category_name)
    if not cat:
        await update.message.reply_text("❌ Category not found. Please start again.")
        context.user_data.clear()
        return

    await db.add_number_batch(
        country_code, country_name, country_flag,
        cat["id"], numbers, per_user, rate
    )

    for key in ["admin_flow", "add_num_step", "add_num_numbers", "add_num_category",
                "add_num_country_code", "add_num_country_name", "add_num_country_flag", "add_num_per_user"]:
        context.user_data.pop(key, None)

    admin_summary = (
        f"✅ <b>Numbers Added Successfully!</b>\n\n"
        f"{country_flag} <b>{country_name}</b> | {category_name}\n"
        f"📦 Total: <b>{len(numbers)}</b>\n"
        f"👤 Per user: <b>{per_user}</b>\n"
        f"💵 Rate: <b>{rate:.2f}৳</b>\n\n"
        f"Do you want to broadcast this new stock to all users?"
    )

    # broadcast message — নতুন ডিজাইন (ওই বটের মতো)
    cat_obj = await db.get_category_by_name(category_name)
    cat_emoji = cat_obj["emoji"] if cat_obj and cat_obj.get("emoji") else "📱"
    bot_info = await context.bot.get_me()
    bot_username = f"@{bot_info.username}"
    broadcast_text = (
        f"🚀 <b>NEW NUMBERS ADDED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{cat_emoji} <b>Platform:</b> {category_name}\n"
        f"{country_flag} <b>Country:</b> {country_name}\n"
        f"📊 <b>Quantity:</b> {len(numbers)} Numbers\n"
        f"💰 <b>Rate Per OTP:</b> {rate:.2f}৳\n"
        f"🤑 <b>Bot Link:</b> {bot_username}\n\n"
        f"🎁 <b>Get your number now from the bot menu!</b>"
    )

    context.user_data["broadcast_message_text"] = broadcast_text
    await update.message.reply_text(admin_summary, parse_mode=ParseMode.HTML, reply_markup=broadcast_confirm_keyboard())

# ============================================================
# GENERAL TEXT INPUT HANDLER
# ============================================================

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    admin_flow = context.user_data.get("admin_flow")

    withdraw_state = context.user_data.get("withdraw_state")
    if withdraw_state in (STATE_SETWALLET_WAITING_ADDRESS, STATE_WITHDRAW_WAITING_AMOUNT):
        await handle_withdraw_input(update, context)
        return

    # Balance add/deduct amount input
    bal_state = context.user_data.get("state")
    if bal_state in ("bal_add_amount", "bal_deduct_amount", "admin_direct_add_balance", "admin_direct_remove_balance"):
        if not await is_user_admin_or_owner(user_id):
            return

        # Direct add/remove — USER_ID AMOUNT format
        if bal_state in ("admin_direct_add_balance", "admin_direct_remove_balance"):
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ সঠিক format এ লিখুন:\n<code>USER_ID AMOUNT</code>\nExample: <code>123456789 50</code>", parse_mode=ParseMode.HTML)
                return
            try:
                target_uid = int(parts[0])
                amount = float(parts[1])
                if amount <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ সঠিক User ID ও পরিমাণ লিখুন।")
                return

            context.user_data.pop("state", None)
            try:
                chat = await context.bot.get_chat(target_uid)
                uname = f"@{chat.username}" if chat.username else chat.full_name or f"UID:{target_uid}"
            except Exception:
                uname = f"UID:{target_uid}"

            if bal_state == "admin_direct_add_balance":
                await db.update_user_balance(target_uid, amount, source="admin_add", note="Admin কর্তৃক যোগ")
                new_bal = await db.get_user_balance(target_uid)
                await update.message.reply_text(
                    f"✅ <b>{uname}</b> এর balance এ <b>+{amount:.2f}৳</b> যোগ হয়েছে।\n"
                    f"নতুন Balance: <b>{new_bal:.2f}৳</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=admin_panel_keyboard()
                )
            else:
                cur_bal = await db.get_user_balance(target_uid)
                if amount > cur_bal:
                    await update.message.reply_text(
                        f"❌ পর্যাপ্ত balance নেই।\nCurrent Balance: <b>{cur_bal:.2f}৳</b>",
                        parse_mode=ParseMode.HTML
                    )
                    return
                await db.update_user_balance(target_uid, -amount, source="admin_deduct", note="Admin কর্তৃক কর্তন")
                new_bal = await db.get_user_balance(target_uid)
                await update.message.reply_text(
                    f"✅ <b>{uname}</b> এর balance থেকে <b>-{amount:.2f}৳</b> কাটা হয়েছে।\n"
                    f"নতুন Balance: <b>{new_bal:.2f}৳</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=admin_panel_keyboard()
                )
            return
        if not await is_user_admin_or_owner(user_id):
            return
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ সঠিক পরিমাণ লিখুন। Example: 10 or 5.50")
            return

        action = context.user_data.get("bal_action")
        target_uid = context.user_data.get("bal_target_uid")
        context.user_data.pop("state", None)
        context.user_data.pop("bal_action", None)
        context.user_data.pop("bal_target_uid", None)

        try:
            chat = await context.bot.get_chat(target_uid)
            uname = f"@{chat.username}" if chat.username else chat.full_name or f"UID:{target_uid}"
        except Exception:
            uname = f"UID:{target_uid}"

        if action == "add":
            await db.update_user_balance(target_uid, amount, source="admin_add", note=f"Admin কর্তৃক যোগ")
            new_bal = await db.get_user_balance(target_uid)
            await update.message.reply_text(
                f"✅ <b>{uname}</b> এর balance এ <b>+{amount:.2f}৳</b> যোগ হয়েছে।\n"
                f"নতুন Balance: <b>{new_bal:.2f}৳</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_panel_keyboard()
            )
        else:
            cur_bal = await db.get_user_balance(target_uid)
            if amount > cur_bal:
                await update.message.reply_text(
                    f"❌ পর্যাপ্ত balance নেই। Current: <b>{cur_bal:.2f}৳</b>",
                    parse_mode=ParseMode.HTML
                )
                return
            await db.update_user_balance(target_uid, -amount, source="admin_deduct", note=f"Admin কর্তৃক কর্তন")
            new_bal = await db.get_user_balance(target_uid)
            await update.message.reply_text(
                f"✅ <b>{uname}</b> এর balance থেকে <b>-{amount:.2f}৳</b> কাটা হয়েছে।\n"
                f"নতুন Balance: <b>{new_bal:.2f}৳</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_panel_keyboard()
            )
        return

    if not await is_user_admin_or_owner(user_id):
        return

    if admin_flow == "add_numbers":
        step = context.user_data.get("add_num_step")
        if step == "waiting_numbers":
            await _add_numbers_step1(update, context, text)
            return
        elif step == "waiting_per_user":
            await _add_numbers_step3(update, context, text)
            return
        elif step == "waiting_rate":
            await _add_numbers_step4(update, context, text)
            return

    if admin_flow == "add_category":
        name = text.upper()
        result = await db.add_category(name)
        context.user_data.pop("admin_flow", None)
        if result:
            await update.message.reply_text(f"✅ <b>Category '{name}' added!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        else:
            await update.message.reply_text("❌ Category already exists or error occurred.")
        return

    if admin_flow == "setting":
        setting_key = context.user_data.get("setting_key")
        await db.set_setting(setting_key, text)
        context.user_data.pop("admin_flow", None)
        context.user_data.pop("setting_key", None)
        await update.message.reply_text("✅ <b>Setting updated!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "panelhold_days":
        panel_name = context.user_data.get("panelhold_target")
        context.user_data.pop("admin_flow", None)
        context.user_data.pop("panelhold_target", None)
        if not text.strip().isdigit() or int(text.strip()) <= 0:
            await update.message.reply_text("❌ সঠিক সংখ্যা পাঠাও (যেমন: 7)।", parse_mode=ParseMode.HTML)
            return
        days = int(text.strip())
        await db.set_panel_hold_days(panel_name, days)
        panels = await db.get_all_panel_hold_settings()
        await update.message.reply_text(
            f"✅ <b>'{panel_name}' — Hold Days {days} দিন সেট করা হয়েছে!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=panel_hold_menu_keyboard(panels)
        )
        return

    if admin_flow == "search_user":
        context.user_data.pop("admin_flow", None)
        try:
            target_uid = int(text.strip())
        except ValueError:
            await update.message.reply_text(
                "❌ সঠিক <b>User ID</b> দিন (শুধু সংখ্যা)।\n\n"
                "উদাহরণ: <code>123456789</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 আবার খুঁজুন", callback_data="admin_search_user", style="primary"),
                ]])
            )
            return

        user = await db.get_user(target_uid)
        if not user:
            await update.message.reply_text(
                f"❌ <b>User ID {target_uid}</b> পাওয়া যায়নি।",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 আবার খুঁজুন", callback_data="admin_search_user", style="primary"),
                    InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary"),
                ]])
            )
            return

        bal = await db.get_user_balance(target_uid)
        uname = f"@{user['username']}" if user.get("username") else user.get("full_name") or f"UID:{target_uid}"
        otp_count = user.get("otp_count", 0)
        is_banned = bool(user.get("is_banned", 0))
        ban_btn = InlineKeyboardButton("✅ Unban", callback_data=f"unban_user_{target_uid}", style="success") if is_banned else InlineKeyboardButton("🚫 Ban", callback_data=f"ban_user_{target_uid}", style="danger")
        ban_status = "🚫 <b>BANNED</b>" if is_banned else "✅ Active"

        msg = (
            f"🔍 <b>User Found!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {uname}\n"
            f"🆔 <b>User ID:</b> <code>{target_uid}</code>\n"
            f"💰 <b>Balance:</b> {bal:.2f}৳\n"
            f"🔑 <b>Total OTP:</b> {otp_count}\n"
            f"📋 <b>Status:</b> {ban_status}"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add Balance", callback_data=f"bal_add_{target_uid}", style="success"),
                InlineKeyboardButton("➖ Deduct", callback_data=f"bal_deduct_{target_uid}", style="danger"),
            ],
            [InlineKeyboardButton("🗑 Reset to Zero", callback_data=f"confirm_reset_{target_uid}", style="danger")],
            [ban_btn],
            [InlineKeyboardButton("🔍 আবার খুঁজুন", callback_data="admin_search_user", style="primary")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary")],
        ])
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if admin_flow == "add_admin":
        try:
            new_admin_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a numeric ID.")
            return
        await db.add_admin(new_admin_id)
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text(f"✅ <b>User <code>{new_admin_id}</code> added as admin!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "remove_admin":
        try:
            rm_admin_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
        await db.remove_admin(rm_admin_id)
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text(f"✅ <b>User <code>{rm_admin_id}</code> removed from admin.</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "add_channel":
        channel_id = None
        try:
            username = text.strip().rstrip('/').split('/')[-1]
            chat = await context.bot.get_chat(f"@{username}")
            channel_id = str(chat.id)
        except Exception:
            pass
        await db.add_required_channel(text, channel_id)
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text(
            f"✅ <b>Channel added:</b> {text}\n{'✅ ID: ' + channel_id if channel_id else '⚠️ Bot must be admin in channel!'}",
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard()
        )
        return

    if admin_flow == "broadcast":
        context.user_data["broadcast_message"] = update.message
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("📢 <b>Ready to broadcast!</b>\n\nSend to all users?", parse_mode=ParseMode.HTML, reply_markup=broadcast_confirm_keyboard())
        return

    if admin_flow == "add_api":
        step = context.user_data.get("api_step")
        if step == "name":
            context.user_data["api_name"] = text
            # type আগে থেকে set থাকলে (CRAPI/Login button থেকে) সরাসরি URL-এ যাও
            if context.user_data.get("api_type"):
                context.user_data["api_step"] = "url"
                await update.message.reply_text(
                    "🌐 <b>Step 2:</b> Send the <b>API URL</b>:\n<i>(e.g. http://147.135.212.197/crapi/lamix/viewstats)</i>",
                    parse_mode=ParseMode.HTML
                )
            else:
                context.user_data["api_step"] = "type"
                await update.message.reply_text(
                    "🔗 <b>Add API</b>\n\nStep 2: Select the <b>API type</b>:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=api_type_keyboard()
                )
        elif step == "url":
            context.user_data["api_url"] = text.strip().rstrip("/")
            api_type = context.user_data.get("api_type", "other")
            if api_type == "login":
                # Login panel: URL → Username → Password (no API key)
                context.user_data["api_step"] = "login_username"
                await update.message.reply_text("👤 <b>Step 3:</b> Send the panel <b>Username</b>:", parse_mode=ParseMode.HTML)
            else:
                context.user_data["api_step"] = "key"
                await update.message.reply_text("🔑 Step 4: Send the <b>API Key</b>:", parse_mode=ParseMode.HTML)
        elif step == "login_username":
            context.user_data["api_login_username"] = text.strip()
            context.user_data["api_step"] = "login_password"
            await update.message.reply_text("🔑 <b>Step 4:</b> Send the panel <b>Password</b>:", parse_mode=ParseMode.HTML)
        elif step == "login_password":
            api_name     = context.user_data.get("api_name")
            api_url      = context.user_data.get("api_url")
            api_username = context.user_data.get("api_login_username", "")
            api_password = text.strip()
            result = await db.add_api(api_name, api_url, "", "login",
                                      username=api_username, password=api_password)
            for k in ["admin_flow", "api_step", "api_name", "api_url", "api_type",
                      "api_login_username"]:
                context.user_data.pop(k, None)
            if result:
                await update.message.reply_text(
                    f"✅ <b>Login Panel '{api_name}' added!</b>\n\n"
                    f"🌐 URL: <code>{api_url}</code>\n"
                    f"👤 Username: <code>{api_username}</code>\n"
                    f"🔐 Type: Login Panel",
                    parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard()
                )
            else:
                await update.message.reply_text("❌ API name already exists.", reply_markup=admin_panel_keyboard())
        elif step == "key":
            api_name = context.user_data.get("api_name")
            api_url  = context.user_data.get("api_url")
            api_type = context.user_data.get("api_type", "other")
            api_key  = text.strip()
            if api_type != "login":
                is_healthy = await check_api_health(api_url, api_key)
            else:
                is_healthy = True
            result = await db.add_api(api_name, api_url, api_key, api_type)
            for k in ["admin_flow", "api_step", "api_name", "api_url", "api_type"]:
                context.user_data.pop(k, None)
            status = "✅ API is working!" if is_healthy else "⚠️ API added but health check failed."
            if result:
                await update.message.reply_text(f"✅ <b>API '{api_name}' added!</b>\n{status}", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            else:
                await update.message.reply_text("❌ API name already exists.", reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "add_evs_scraper":
        step = context.user_data.get("scraper_step")
        if step == "name":
            context.user_data["scraper_name"] = text
            context.user_data["scraper_step"] = "url"
            await update.message.reply_text(
                "🌐 <b>Step 2:</b> Send the <b>EVS panel URL</b>:\n<i>(e.g. http://57.129.107.62)</i>",
                parse_mode=ParseMode.HTML
            )
        elif step == "url":
            raw_url = text.strip().rstrip("/")
            for suffix in ["/ints/login", "/ints/signin", "/ints/agent", "/ints"]:
                if raw_url.endswith(suffix):
                    raw_url = raw_url[:-len(suffix)]
                    break
            context.user_data["scraper_url"] = raw_url.rstrip("/")
            context.user_data["scraper_step"] = "username"
            await update.message.reply_text("👤 <b>Step 3:</b> Send the <b>username</b>:", parse_mode=ParseMode.HTML)
        elif step == "username":
            context.user_data["scraper_username"] = text
            context.user_data["scraper_step"] = "password"
            await update.message.reply_text("🔑 <b>Step 4:</b> Send the <b>password</b>:", parse_mode=ParseMode.HTML)
        elif step == "password":
            s_name = context.user_data.get("scraper_name", "EVS Panel")
            s_url  = context.user_data.get("scraper_url", "")
            s_user = context.user_data.get("scraper_username", "")
            result = await db.add_scraper(s_name, s_url, s_user, text, scraper_type="evs")
            for k in ["admin_flow", "scraper_step", "scraper_name", "scraper_url", "scraper_username"]:
                context.user_data.pop(k, None)
            if result:
                await update.message.reply_text(
                    f"✅ <b>EVS Panel '{s_name}' added!</b>\n\n🌐 URL: <code>{s_url}</code>\n👤 Username: <code>{s_user}</code>",
                    parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard()
                )
            else:
                await update.message.reply_text("❌ Panel name already exists.", reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "add_client_scraper":
        step = context.user_data.get("scraper_step")
        if step == "name":
            context.user_data["scraper_name"] = text
            context.user_data["scraper_step"] = "url"
            await update.message.reply_text("🌐 <b>Step 2:</b> Send the <b>panel URL</b>:", parse_mode=ParseMode.HTML)
        elif step == "url":
            raw_url = text.strip().rstrip("/")
            for suffix in ["/ints/login", "/ints/signin", "/ints/client", "/ints"]:
                if raw_url.endswith(suffix):
                    raw_url = raw_url[:-len(suffix)]
                    break
            context.user_data["scraper_url"] = raw_url.rstrip("/")
            context.user_data["scraper_step"] = "username"
            await update.message.reply_text("👤 <b>Step 3:</b> Send the <b>username</b>:", parse_mode=ParseMode.HTML)
        elif step == "username":
            context.user_data["scraper_username"] = text
            context.user_data["scraper_step"] = "password"
            await update.message.reply_text("🔑 <b>Step 4:</b> Send the <b>password</b>:", parse_mode=ParseMode.HTML)
        elif step == "password":
            s_name = context.user_data.get("scraper_name", "Panel")
            s_url  = context.user_data.get("scraper_url", "")
            s_user = context.user_data.get("scraper_username", "")
            result = await db.add_scraper(s_name, s_url, s_user, text, scraper_type="client")
            for k in ["admin_flow", "scraper_step", "scraper_name", "scraper_url", "scraper_username"]:
                context.user_data.pop(k, None)
            if result:
                await update.message.reply_text(f"✅ <b>Client Panel '{s_name}' added!</b>\n\n🌐 URL: <code>{s_url}</code>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            else:
                await update.message.reply_text("❌ Panel name already exists.", reply_markup=admin_panel_keyboard())
        return

    if admin_flow == "add_scraper":
        step = context.user_data.get("scraper_step")
        if step == "name":
            context.user_data["scraper_name"] = text
            context.user_data["scraper_step"] = "url"
            await update.message.reply_text("🌐 <b>Step 2:</b> Send the <b>panel URL</b>:", parse_mode=ParseMode.HTML)
        elif step == "url":
            raw_url = text.strip().rstrip("/")
            for suffix in ["/ints/login", "/ints/signin", "/ints/agent", "/ints"]:
                if raw_url.endswith(suffix):
                    raw_url = raw_url[:-len(suffix)]
                    break
            context.user_data["scraper_url"] = raw_url.rstrip("/")
            context.user_data["scraper_step"] = "username"
            await update.message.reply_text("👤 <b>Step 3:</b> Send the <b>username</b>:", parse_mode=ParseMode.HTML)
        elif step == "username":
            context.user_data["scraper_username"] = text
            context.user_data["scraper_step"] = "password"
            await update.message.reply_text("🔑 <b>Step 4:</b> Send the <b>password</b>:", parse_mode=ParseMode.HTML)
        elif step == "password":
            s_name = context.user_data.get("scraper_name", "Panel")
            s_url  = context.user_data.get("scraper_url", "")
            s_user = context.user_data.get("scraper_username", "")
            result = await db.add_scraper(s_name, s_url, s_user, text)
            for k in ["admin_flow", "scraper_step", "scraper_name", "scraper_url", "scraper_username"]:
                context.user_data.pop(k, None)
            if result:
                await update.message.reply_text(f"✅ <b>Panel '{s_name}' added!</b>\n\n🌐 URL: <code>{s_url}</code>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            else:
                await update.message.reply_text("❌ Panel name already exists.", reply_markup=admin_panel_keyboard())
        return

# ============================================================
# MENU BUTTON ROUTER
# ============================================================

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # Banned user check
    if await db.is_user_banned(user_id):
        await update.message.reply_text("🚫 আপনাকে এই বট থেকে ban করা হয়েছে।")
        return

    admin_flow    = context.user_data.get("admin_flow")
    withdraw_state = context.user_data.get("withdraw_state")
    if admin_flow or withdraw_state:
        await handle_text_input(update, context)
        return

    text_upper = text.upper()

    # Leaderboard সবার জন্য — channel check এর আগেই handle করছি
    if "LEADERBOARD" in text_upper:
        await handle_leaderboard(update, context)
        return

    # আমার সর্বশেষ OTP — এটাও সবার জন্য সবসময় available রাখা হচ্ছে
    if "OTP" in text_upper and ("সর্বশেষ" in text or "LAST" in text_upper):
        await handle_my_last_otp(update, context)
        return

    if not await is_user_admin_or_owner(user_id):
        channels = await db.get_required_channels()
        if channels and not await check_channel_membership(context.bot, user_id, channels):
            await update.message.reply_text(
                "🔒 <b>You must join our channel(s) to use this bot!</b>\n\nPlease join below, then tap <b>Verify</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=channel_join_keyboard(channels)
            )
            return

    if "GET NUMBER" in text_upper:
        await handle_get_number(update, context)
    elif "AVAILABLE COUNTRY" in text_upper:
        await handle_available_country(update, context)
    elif "BALANCE" in text_upper:
        if not await _check_payment_proof_membership(context.bot, user_id):
            await _send_proof_channel_join_prompt(update)
            return
        await handle_balance(update, context)
    elif "WITHDRAW" in text_upper:
        if not await _check_payment_proof_membership(context.bot, user_id):
            await _send_proof_channel_join_prompt(update)
            return
        await handle_withdraw_menu(update, context)
    elif "SUPPORT" in text_upper:
        await handle_support(update, context)
    elif "ADMIN PANEL" in text_upper:
        await handle_admin_panel(update, context)

# ============================================================
# DOCUMENT UPLOAD (numbers via .txt / .csv)
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_user_admin_or_owner(user_id):
        return

    admin_flow = context.user_data.get("admin_flow")
    add_num_step = context.user_data.get("add_num_step")
    if admin_flow != "add_numbers" or add_num_step != "waiting_numbers":
        return

    doc = update.message.document
    if not doc.file_name.endswith((".txt", ".csv")):
        await update.message.reply_text("❌ Please send a .txt or .csv file.")
        return

    file = await context.bot.get_file(doc.file_id)
    content = await file.download_as_bytearray()
    text = content.decode("utf-8", errors="ignore")
    await _add_numbers_step1(update, context, text)

# ============================================================
# PHOTO/VIDEO FOR BROADCAST
# ============================================================

async def handle_media_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_user_admin_or_owner(user_id):
        return
    if context.user_data.get("admin_flow") != "broadcast":
        return
    context.user_data["broadcast_message"] = update.message
    context.user_data.pop("admin_flow", None)
    await update.message.reply_text("📢 <b>Media ready to broadcast!</b>\n\nSend to all users?", parse_mode=ParseMode.HTML, reply_markup=broadcast_confirm_keyboard())

# ============================================================
# ADMIN CALLBACK HANDLER
# ============================================================

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await is_user_admin_or_owner(user_id):
        await query.answer("❌ Access denied.", show_alert=True)
        return

    data = query.data

    if data == "back_to_admin_panel":
        await query.answer()
        live_users = await db.count_live_users()
        await query.edit_message_text(
            f"🛠 <b>Admin Panel</b> [Live Users: {live_users}]",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )

    elif data == "admin_add_numbers":
        await query.answer()
        categories = await db.get_all_categories()
        if not categories:
            await query.edit_message_text("❌ No categories found. Please add a category first.", reply_markup=InlineKeyBoardBack())
            return
        context.user_data["admin_flow"] = "add_numbers"
        context.user_data["add_num_step"] = "waiting_numbers"
        for key in ["add_num_numbers", "add_num_category", "add_num_country_code",
                    "add_num_country_name", "add_num_country_flag", "add_num_per_user"]:
            context.user_data.pop(key, None)
        await query.edit_message_text(
            "➕ <b>Add Numbers</b>\n\n"
            "<b>Step 1:</b> Send all phone numbers.\n"
            "• Type them (one per line), OR\n"
            "• Upload a <b>.txt</b> or <b>.csv</b> file\n\n"
            "Example:\n+8801XXXXXXXXX\n8801YYYYYYYYY",
            parse_mode=ParseMode.HTML
        )

    elif data.startswith("addnum_cat_"):
        await query.answer()
        category_name = data.replace("addnum_cat_", "")
        context.user_data["add_num_category"] = category_name
        context.user_data["admin_flow"] = "add_numbers"
        context.user_data["add_num_step"] = "waiting_per_user"
        numbers_count = len(context.user_data.get("add_num_numbers", []))
        country_flag  = context.user_data.get("add_num_country_flag", "🌍")
        country_name  = context.user_data.get("add_num_country_name", "Unknown")
        await query.edit_message_text(
            f"✅ <b>{numbers_count} numbers</b> | {country_flag} {country_name}\n"
            f"📂 Category: <b>{category_name}</b>\n\n"
            f"<b>Step 3:</b> How many numbers per user?\n"
            f"Send an integer. Example: <code>4</code>",
            parse_mode=ParseMode.HTML
        )

    elif data == "admin_manage_numbers":
        await query.answer()
        batches = await db.get_all_batches()
        if not batches:
            await query.edit_message_text("📁 <b>Manage Numbers</b>\n\nNo number batches found.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkupBack())
            return
        lines = [_format_batch_line(b) for b in batches]
        await query.edit_message_text(
            "📁 <b>Manage Numbers</b>\n\n" + "\n\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=manage_numbers_keyboard(batches)
        )

    elif data.startswith("del_batch_"):
        batch_id = int(data.replace("del_batch_", ""))
        await db.delete_batch(batch_id)
        await query.answer(f"✅ Batch ID {batch_id} deleted.", show_alert=True)
        batches = await db.get_all_batches()
        if not batches:
            await query.edit_message_text("📁 <b>Manage Numbers</b>\n\nNo number batches found.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkupBack())
            return
        lines = [_format_batch_line(b) for b in batches]
        await query.edit_message_text("📁 <b>Manage Numbers</b>\n\n" + "\n\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=manage_numbers_keyboard(batches))

    elif data.startswith("togglehide_"):
        batch_id = int(data.replace("togglehide_", ""))
        now_hidden = await db.toggle_batch_hidden(batch_id)
        await query.answer(f"✅ Batch ID {batch_id} এখন {'Hidden 🙈' if now_hidden else 'Visible 🙉'}", show_alert=True)
        batches = await db.get_all_batches()
        if not batches:
            await query.edit_message_text("📁 <b>Manage Numbers</b>\n\nNo number batches found.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkupBack())
            return
        lines = [_format_batch_line(b) for b in batches]
        await query.edit_message_text("📁 <b>Manage Numbers</b>\n\n" + "\n\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=manage_numbers_keyboard(batches))

    elif data == "admin_manage_categories":
        await query.answer()
        categories = await db.get_all_categories()
        cat_list = [{"name": c["name"], "emoji": c["emoji"]} for c in categories]
        lines = [f"• {c['emoji']} <b>{c['name']}</b> (ID: {c['id']})" for c in categories]
        await query.edit_message_text(
            "📂 <b>Category Management</b>\n\n" + ("\n".join(lines) if lines else "No categories yet."),
            parse_mode=ParseMode.HTML,
            reply_markup=category_management_keyboard(cat_list)
        )

    elif data == "add_category":
        await query.answer()
        context.user_data["admin_flow"] = "add_category"
        await query.edit_message_text("➕ <b>Add Category</b>\n\nSend the name (e.g. TWITTER):", parse_mode=ParseMode.HTML)

    elif data.startswith("del_category_"):
        name = data.replace("del_category_", "")
        await db.delete_category(name)
        await query.answer(f"✅ Category {name} deleted.", show_alert=True)
        categories = await db.get_all_categories()
        cat_list = [{"name": c["name"], "emoji": c["emoji"]} for c in categories]
        lines = [f"• {c['emoji']} <b>{c['name']}</b> (ID: {c['id']})" for c in categories]
        await query.edit_message_text(
            "📂 <b>Category Management</b>\n\n" + ("\n".join(lines) if lines else "No categories yet."),
            parse_mode=ParseMode.HTML,
            reply_markup=category_management_keyboard(cat_list)
        )

    elif data == "admin_withdraw_requests":
        await query.answer()
        requests = await db.get_pending_withdraw_requests()
        if not requests:
            await query.edit_message_text("💸 <b>Withdraw Requests</b>\n\n✅ No pending requests.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkupBack())
            return
        for req in requests:
            await query.message.reply_text(
                f"💸 <b>Withdraw Request #{req['id']}</b>\n\n"
                f"👤 <b>Name:</b> {req['full_name']}\n"
                f"🔗 <b>Username:</b> @{req['username']}\n"
                f"💳 <b>Method:</b> {req['method']}\n"
                f"📨 <b>Address:</b> {req['address']}\n"
                f"💵 <b>Amount:</b> {req['amount']:.2f}৳\n"
                f"📅 <b>Date:</b> {req['created_at'][:16]}",
                parse_mode=ParseMode.HTML,
                reply_markup=withdraw_action_keyboard(req["id"])
            )

    elif data.startswith("withdraw_complete_"):
        req_id = int(data.replace("withdraw_complete_", ""))
        req = await db.get_withdraw_request(req_id)
        await db.update_withdraw_status(req_id, "completed")
        await query.edit_message_text(query.message.text + "\n\n✅ <b>COMPLETED</b>", parse_mode=ParseMode.HTML)
        if req:
            try:
                await context.bot.send_message(chat_id=req["user_id"], text="✅ <b>আপনার উইথড্রো সফল হয়েছে!</b>\n\nআপনার টাকা পাঠানো হয়েছে। ধন্যবাদ! 🎉", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            # ── Main channel এ Payment Completed post ──
            try:
                from datetime import datetime
                import pytz
                bd_tz = pytz.timezone("Asia/Dhaka")
                now_str = datetime.now(bd_tz).strftime("%Y-%m-%d %I:%M %p")
                full_name = req.get("full_name") or str(req["user_id"])
                method = req.get("method", "N/A")
                amount = req.get("amount", 0)
                bot_info = await context.bot.get_me()
                bot_link = f"https://t.me/{bot_info.username}"
                channel_text = (
                    f"<b>#{req_id} OTP Work Payment Successful</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 User Name: <b>{full_name}</b>\n"
                    f"💰 Amount: <b>{amount:.2f}৳</b>\n"
                    f"📦 Withdraw: <b>{method}</b>\n"
                    f"🕐 Date: <b>{now_str}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"➡️ Invite & Earn\n"
                    f"{bot_link}"
                )
                channel_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Check Your Wallet", url=bot_link, style="success")]
                ])
                await context.bot.send_message(
                    chat_id=-1003584582533,
                    text=channel_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=channel_kb
                )
            except Exception as e:
                logger.error(f"Channel post failed: {e}")

    elif data.startswith("withdraw_reject_"):
        req_id = int(data.replace("withdraw_reject_", ""))
        req = await db.get_withdraw_request(req_id)
        await db.update_withdraw_status(req_id, "rejected")
        await query.edit_message_text(query.message.text + "\n\n❌ <b>REJECTED</b>", parse_mode=ParseMode.HTML)
        if req:
            try:
                await context.bot.send_message(chat_id=req["user_id"], text="❌ <b>আপনার উইথড্রো বাতিল করা হয়েছে।</b>\n\nদয়া করে সাপোর্টে যোগাযোগ করুন।", parse_mode=ParseMode.HTML)
            except Exception:
                pass

    elif data == "admin_broadcast":
        await query.answer()
        context.user_data["admin_flow"] = "broadcast"
        await query.edit_message_text("📢 <b>Broadcast</b>\n\nSend the message (text, photo, video) to broadcast:", parse_mode=ParseMode.HTML)

    elif data in ("confirm_broadcast", "skip_broadcast"):
        if data == "confirm_broadcast":
            msg = context.user_data.get("broadcast_message")
            if not msg:
                txt = context.user_data.get("broadcast_message_text")
                if txt:
                    bot_info = await context.bot.get_me()
                    bot_link = f"https://t.me/{bot_info.username}"
                    broadcast_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📞 Get Number Now", url=bot_link, style="success")]
                    ])

                    async def _send_stock_broadcast(bot, text, keyboard):
                        users = await db.get_all_users()
                        CHUNK = 25
                        for i in range(0, len(users), CHUNK):
                            chunk = users[i:i+CHUNK]
                            await asyncio.gather(*[
                                _try_send(bot, u["user_id"], text, keyboard)
                                for u in chunk
                            ], return_exceptions=True)
                            await asyncio.sleep(1.0)

                    async def _try_send(bot, uid, text, keyboard):
                        try:
                            await bot.send_message(chat_id=uid, text=text,
                                                   parse_mode=ParseMode.HTML, reply_markup=keyboard)
                        except Exception:
                            pass

                    asyncio.create_task(_send_stock_broadcast(context.bot, txt, broadcast_kb))
            else:
                asyncio.create_task(_background_broadcast(context.bot, msg))
        context.user_data.pop("broadcast_message", None)
        context.user_data.pop("broadcast_message_text", None)
        live_users = await db.count_live_users()
        try:
            await query.edit_message_text(f"🛠 <b>Admin Panel</b> [Live Users: {live_users}]", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        except Exception:
            pass

    elif data == "admin_list":
        await query.answer()
        admins = await db.get_all_admins()
        if not admins:
            text = "👤 <b>Admin List</b>\n\nThere are no admins [only owner]"
        else:
            lines = []
            for adm in admins:
                try:
                    chat = await context.bot.get_chat(adm["user_id"])
                    name = chat.full_name or str(adm["user_id"])
                    uname = f"@{chat.username}" if chat.username else ""
                    lines.append(f"• {name} {uname} (<code>{adm['user_id']}</code>)")
                except Exception:
                    lines.append(f"• <code>{adm['user_id']}</code>")
            text = "👤 <b>Admin List</b>\n\n" + "\n".join(lines)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkupBack())

    elif data == "admin_add_balance":
        await query.answer()
        context.user_data["state"] = "admin_direct_add_balance"
        await query.edit_message_text(
            "➕ <b>Add Balance</b>\n\n"
            "ইউজার ID এবং পরিমাণ লিখুন:\n"
            "<code>USER_ID AMOUNT</code>\n\n"
            "Example: <code>123456789 50</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_to_admin_panel", style="danger")
            ]])
        )

    elif data == "admin_remove_balance":
        await query.answer()
        context.user_data["state"] = "admin_direct_remove_balance"
        await query.edit_message_text(
            "➖ <b>Remove Balance</b>\n\n"
            "ইউজার ID এবং পরিমাণ লিখুন:\n"
            "<code>USER_ID AMOUNT</code>\n\n"
            "Example: <code>123456789 50</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_to_admin_panel", style="danger")
            ]])
        )

    elif data == "admin_user_balances":
        await query.answer()
        users = await db.get_all_users_with_balance()
        if not users:
            await query.edit_message_text(
                "💰 <b>User Balances</b>\n\nকোনো ইউজারের balance নেই।",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkupBack()
            )
            return

        total_users = len(users)
        total_balance = sum(u["balance"] for u in users)
        total_otp = sum(u.get("otp_count", 0) for u in users)
        top_users = sorted(users, key=lambda x: x["balance"], reverse=True)[:5]

        lines = [
            "💰 <b>User Balances</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"👥 <b>মোট ইউজার:</b> {total_users} জন",
            f"💵 <b>মোট Balance:</b> {total_balance:.2f}৳",
            f"🔑 <b>মোট OTP:</b> {total_otp}",
            "",
            "🏆 <b>Top 5 Balance:</b>",
        ]
        for i, u in enumerate(top_users, 1):
            uname = f"@{u['username']}" if u.get("username") else u.get("full_name") or f"UID:{u['user_id']}"
            lines.append(f"{i}. {uname} — {u['balance']:.2f}৳")

        buttons = [
            [InlineKeyboardButton("🔍 ইউজার খুঁজুন (User ID)", callback_data="admin_search_user", style="primary")],
            [InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="primary")],
        ]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("reset_balance_"):
        await query.answer()
        target_uid = int(data.split("_")[-1])
        # balance log দেখাই আগে
        logs = await db.get_user_balance_logs(target_uid, limit=10)
        try:
            chat = await context.bot.get_chat(target_uid)
            uname = f"@{chat.username}" if chat.username else chat.full_name or f"UID:{target_uid}"
        except Exception:
            uname = f"UID:{target_uid}"
        bal = await db.get_user_balance(target_uid)

        source_labels = {
            "otp_reward": "🔑 OTP Reward",
            "referral": "👥 Referral",
            "manual": "✏️ Manual",
            "admin_reset": "🗑 Admin Reset",
            "admin_add": "➕ Admin Add",
            "admin_deduct": "➖ Admin Deduct",
        }
        log_lines = [f"💰 <b>{uname}</b>", f"Current Balance: <b>{bal:.2f}৳</b>", "", "📋 <b>ইতিহাস (শেষ ১০টি):</b>"]
        for log in logs:
            src = source_labels.get(log["source"], log["source"])
            sign = "+" if log["amount"] >= 0 else ""
            note = f" ({log['note']})" if log.get("note") else ""
            log_lines.append(f"{src}: {sign}{log['amount']:.2f}{note:.2f}৳")

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add Balance", callback_data=f"bal_add_{target_uid}", style="success"),
                InlineKeyboardButton("➖ Deduct Balance", callback_data=f"bal_deduct_{target_uid}", style="danger"),
            ],
            [InlineKeyboardButton("🗑 Reset to Zero", callback_data=f"confirm_reset_{target_uid}", style="danger")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary")],
        ])
        await query.edit_message_text("\n".join(log_lines), parse_mode=ParseMode.HTML, reply_markup=kb)

    elif data.startswith("bal_add_") or data.startswith("bal_deduct_"):
        await query.answer()
        action = "add" if data.startswith("bal_add_") else "deduct"
        target_uid = int(data.split("_")[-1])
        action_label = "যোগ করুন" if action == "add" else "কাটুন"
        context.user_data["bal_action"] = action
        context.user_data["bal_target_uid"] = target_uid
        context.user_data["state"] = f"bal_{action}_amount"
        try:
            chat = await context.bot.get_chat(target_uid)
            uname = f"@{chat.username}" if chat.username else chat.full_name or f"UID:{target_uid}"
        except Exception:
            uname = f"UID:{target_uid}"
        bal = await db.get_user_balance(target_uid)
        await query.edit_message_text(
            f"💰 <b>{uname}</b>\n"
            f"Current Balance: <b>{bal:.2f}৳</b>\n\n"
            f"কত টাকা {'যোগ' if action == 'add' else 'কাটবেন'}? পরিমাণ লিখুন:\n"
            f"<i>Example: 10 or 5.50</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"reset_balance_{target_uid}", style="danger")
            ]])
        )

    elif data.startswith("confirm_reset_"):
        await query.answer()
        target_uid = int(data.split("_")[-1])
        await db.reset_user_balance(target_uid)
        try:
            chat = await context.bot.get_chat(target_uid)
            uname = f"@{chat.username}" if chat.username else chat.full_name or f"UID:{target_uid}"
        except Exception:
            uname = f"UID:{target_uid}"
        await query.edit_message_text(
            f"✅ <b>{uname}</b> এর balance রিসেট করা হয়েছে।",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back to Balances", callback_data="admin_user_balances", style="primary")
            ]])
        )

    elif data == "scraping_evs_panel":
        await query.answer()
        scrapers = await db.get_scrapers_by_type("evs")
        await query.edit_message_text(
            "🔷 <b>EVS Panel</b>\n\nManage your EVS scraping panels:",
            parse_mode=ParseMode.HTML,
            reply_markup=evs_panel_keyboard(scrapers)
        )

    elif data == "evs_add_panel":
        await query.answer()
        context.user_data["admin_flow"] = "add_evs_scraper"
        context.user_data["scraper_step"] = "name"
        await query.edit_message_text(
            "➕ <b>Add EVS Panel</b>\n\n<b>Step 1:</b> Send a <b>name</b>:\n<i>(e.g. EVS Panel)</i>",
            parse_mode=ParseMode.HTML
        )

    elif data.startswith("evs_del_"):
        name = data[len("evs_del_"):]
        await db.delete_scraper(name)
        await query.answer(f"✅ '{name}' deleted.", show_alert=True)
        scrapers = await db.get_scrapers_by_type("evs")
        await query.edit_message_text(
            "🔷 <b>EVS Panel</b>\n\nManage your EVS scraping panels:",
            parse_mode=ParseMode.HTML,
            reply_markup=evs_panel_keyboard(scrapers)
        )

    elif data == "otp_reward_hold_menu":
        await query.answer()
        panels = await db.get_all_panel_hold_settings()
        await query.edit_message_text(
            "🔒 <b>OTP Reward Hold</b>\n\n"
            "যে প্যানেলের reward hold করতে চাও, সেটায় চাপো (ON/OFF)।\n"
            "⏱ বাটনে চেপে hold-এর দিন সংখ্যা পরিবর্তন করতে পারবে।",
            parse_mode=ParseMode.HTML,
            reply_markup=panel_hold_menu_keyboard(panels)
        )

    elif data.startswith("panelhold_toggle_"):
        panel_name = data[len("panelhold_toggle_"):]
        current = await db.get_panel_hold_setting(panel_name)
        new_state = not (current and current["hold_enabled"])
        await db.set_panel_hold_enabled(panel_name, new_state)
        msg = f"✅ '{panel_name}' hold চালু করা হয়েছে!" if new_state else f"❌ '{panel_name}' hold বন্ধ করা হয়েছে!"
        await query.answer(msg, show_alert=True)
        panels = await db.get_all_panel_hold_settings()
        await query.edit_message_text(
            "🔒 <b>OTP Reward Hold</b>\n\n"
            "যে প্যানেলের reward hold করতে চাও, সেটায় চাপো (ON/OFF)।\n"
            "⏱ বাটনে চেপে hold-এর দিন সংখ্যা পরিবর্তন করতে পারবে।",
            parse_mode=ParseMode.HTML,
            reply_markup=panel_hold_menu_keyboard(panels)
        )

    elif data.startswith("panelhold_days_"):
        panel_name = data[len("panelhold_days_"):]
        await query.answer()
        context.user_data["admin_flow"] = "panelhold_days"
        context.user_data["panelhold_target"] = panel_name
        await query.edit_message_text(
            f"⏱ <b>'{panel_name}' — Hold Days পরিবর্তন</b>\n\n"
            f"কত দিন hold রাখতে চাও, সংখ্যা পাঠাও (যেমন: 7):",
            parse_mode=ParseMode.HTML
        )

    elif data == "withdraw_method_toggle_menu":
        await query.answer()
        disabled = await get_disabled_methods()
        await query.edit_message_text(
            "💳 <b>Withdraw Method ON/OFF</b>\n\nযে method বন্ধ করতে চাও সেটায় চাপো:",
            parse_mode=ParseMode.HTML,
            reply_markup=withdraw_method_toggle_keyboard(disabled)
        )

    elif data.startswith("toggle_method_"):
        method = data.replace("toggle_method_", "")
        disabled = await get_disabled_methods()
        if method in disabled:
            disabled.remove(method)
            msg = f"✅ {method} চালু করা হয়েছে!"
        else:
            disabled.append(method)
            msg = f"❌ {method} বন্ধ করা হয়েছে!"
        await db.set_setting("disabled_withdraw_methods", ",".join(disabled))
        await query.answer(msg, show_alert=True)
        await query.edit_message_text(
            "💳 <b>Withdraw Method ON/OFF</b>\n\nযে method বন্ধ করতে চাও সেটায় চাপো:",
            parse_mode=ParseMode.HTML,
            reply_markup=withdraw_method_toggle_keyboard(disabled)
        )

    elif data.startswith("ban_user_"):
        target_uid = int(data.replace("ban_user_", ""))
        await db.ban_user(target_uid)
        await query.answer("🚫 User ban করা হয়েছে!", show_alert=True)
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text="🚫 <b>আপনাকে এই বট থেকে ban করা হয়েছে।</b>\nযোগাযোগ করুন: @support",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        user = await db.get_user(target_uid)
        bal = await db.get_user_balance(target_uid)
        uname = f"@{user['username']}" if user and user.get("username") else f"UID:{target_uid}"
        await query.edit_message_text(
            f"🔍 <b>User Found!</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {uname}\n🆔 <b>User ID:</b> <code>{target_uid}</code>\n"
            f"💰 <b>Balance:</b> {bal:.2f}৳\n📋 <b>Status:</b> 🚫 <b>BANNED</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Unban", callback_data=f"unban_user_{target_uid}", style="success")],
                [InlineKeyboardButton("🔍 আবার খুঁজুন", callback_data="admin_search_user", style="primary")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary")],
            ])
        )

    elif data.startswith("unban_user_"):
        target_uid = int(data.replace("unban_user_", ""))
        await db.unban_user(target_uid)
        await query.answer("✅ User unban করা হয়েছে!", show_alert=True)
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text="✅ <b>আপনার ban তুলে নেওয়া হয়েছে।</b> আবার বট ব্যবহার করতে পারবেন।",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        user = await db.get_user(target_uid)
        bal = await db.get_user_balance(target_uid)
        uname = f"@{user['username']}" if user and user.get("username") else f"UID:{target_uid}"
        await query.edit_message_text(
            f"🔍 <b>User Found!</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {uname}\n🆔 <b>User ID:</b> <code>{target_uid}</code>\n"
            f"💰 <b>Balance:</b> {bal:.2f}৳\n📋 <b>Status:</b> ✅ Active",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Add Balance", callback_data=f"bal_add_{target_uid}", style="success"),
                    InlineKeyboardButton("➖ Deduct", callback_data=f"bal_deduct_{target_uid}", style="danger"),
                ],
                [InlineKeyboardButton("🗑 Reset to Zero", callback_data=f"confirm_reset_{target_uid}", style="danger")],
                [InlineKeyboardButton("🚫 Ban", callback_data=f"ban_user_{target_uid}", style="danger")],
                [InlineKeyboardButton("🔍 আবার খুঁজুন", callback_data="admin_search_user", style="primary")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary")],
            ])
        )

    elif data == "admin_search_user":
        await query.answer()
        context.user_data["admin_flow"] = "search_user"
        await query.edit_message_text(
            "🔍 <b>ইউজার খুঁজুন</b>\n\n"
            "ইউজারের <b>User ID</b> পাঠান:\n"
            "<i>(Telegram numeric ID, যেমন: 123456789)</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data="admin_user_balances", style="primary")
            ]])
        )

    elif data == "withdraw_system_toggle":
        await query.answer()
        current = await is_withdraw_system_on()
        new_val = "0" if current else "1"
        await db.set_setting("withdraw_system_enabled", new_val)
        withdraw_on = new_val == "1"
        status = "চালু ✅" if withdraw_on else "বন্ধ ❌"
        await query.answer(f"Withdraw {status}", show_alert=True)
        await query.edit_message_text(
            "🛠 <b>Admin Panel</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard(withdraw_on=withdraw_on)
        )

    elif data == "referral_notify_toggle":
        await query.answer()
        current = await db.is_referral_notify_on()
        new_val = "0" if current else "1"
        await db.set_setting("referral_notify_enabled", new_val)
        referral_notify_on = new_val == "1"
        status = "চালু ✅" if referral_notify_on else "বন্ধ ❌"
        await query.answer(f"Refer Notify {status}", show_alert=True)
        withdraw_on = await is_withdraw_system_on()
        await query.edit_message_text(
            "🛠 <b>Admin Panel</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard(withdraw_on=withdraw_on, referral_notify_on=referral_notify_on)
        )

    elif data == "admin_settings":
        await query.answer()
        support    = await db.get_setting("support_username") or "N/A"
        ref_amount = await db.get_setting("referral_amount") or "N/A"
        min_w      = await db.get_setting("min_withdraw") or "N/A"
        otp_link   = await db.get_setting("otp_group_link") or "N/A"
        main_ch    = await db.get_setting("main_channel_link") or "N/A"
        proof_link = await db.get_setting("payment_proof_channel_link") or PAYMENT_PROOF_CHANNEL_LINK
        proof_id   = await db.get_setting("payment_proof_channel_id") or str(PAYMENT_PROOF_CHANNEL_ID)
        await query.edit_message_text(
            f"⚙️ <b>Bot Settings</b>\n\n"
            f"• Support Username: {support}\n"
            f"• Referral Amount (৳): {ref_amount}\n"
            f"• Min Withdraw (৳): {min_w}\n"
            f"• OTP Group Link: {otp_link}\n"
            f"• Main Channel Link: {main_ch}\n"
            f"• Payment Proof Channel Link: {proof_link}\n"
            f"• Payment Proof Channel ID: {proof_id}\n\n"
            f"Tap a button to modify:",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_keyboard()
        )

    elif data.startswith("setting_"):
        setting_key = data.replace("setting_", "")
        key_labels = {
            "support_username":             "Support Username",
            "referral_amount":              "Referral Amount (৳)",
            "min_withdraw":                 "Min Withdraw (৳)",
            "otp_group_link":               "OTP Group Link",
            "main_channel_link":            "Main Channel Link",
            "payment_proof_channel_link":   "Payment Proof Channel Link 💰",
            "payment_proof_channel_id":     "Payment Proof Channel ID (numeric, e.g. -100...) 🆔",
            "otp_grace_minutes":            "OTP Grace Period (minutes) ⏱",
        }
        label = key_labels.get(setting_key, setting_key)
        context.user_data["admin_flow"] = "setting"
        context.user_data["setting_key"] = setting_key
        await query.edit_message_text(f"✏️ <b>Edit {label}</b>\n\nSend the new value:", parse_mode=ParseMode.HTML)

    elif data == "admin_req_channels":
        await query.answer()
        channels = await db.get_required_channels()
        text = "📣 <b>Required Channels</b>\n\n" + ("\n".join([f"• {c['channel_link']}" for c in channels]) if channels else "No required channels configured.")
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=req_channels_keyboard(channels))

    elif data == "add_channel":
        await query.answer()
        context.user_data["admin_flow"] = "add_channel"
        await query.edit_message_text("📣 <b>Add Required Channel</b>\n\nSend the channel invite link:", parse_mode=ParseMode.HTML)

    elif data.startswith("del_channel_"):
        ch_id = int(data.replace("del_channel_", ""))
        await db.delete_required_channel(ch_id)
        await query.answer("✅ Channel removed.", show_alert=True)
        channels = await db.get_required_channels()
        text = "📣 <b>Required Channels</b>\n\n" + ("\n".join([f"• {c['channel_link']}" for c in channels]) if channels else "No channels configured.")
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=req_channels_keyboard(channels))

    elif data == "admin_add_admin":
        await query.answer()
        context.user_data["admin_flow"] = "add_admin"
        await query.edit_message_text("👮 <b>Add Admin</b>\n\nSend the Telegram <b>User ID</b>:", parse_mode=ParseMode.HTML)

    elif data == "admin_remove_admin":
        await query.answer()
        context.user_data["admin_flow"] = "remove_admin"
        await query.edit_message_text("🚫 <b>Remove Admin</b>\n\nSend the Telegram <b>User ID</b> to remove:", parse_mode=ParseMode.HTML)

    elif data == "admin_manage_api":
        await query.answer()
        await query.edit_message_text("🔗 <b>Manage API</b>\n\nChoose a system:", parse_mode=ParseMode.HTML, reply_markup=api_management_keyboard([]))

    elif data == "api_system_menu":
        await query.answer()
        apis = await db.get_all_apis()
        text = "🔗 <b>API System</b>\n\n" + ("\n".join([f"✅ <b>{a['name']}</b>" for a in apis]) if apis else "No APIs configured.")
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=api_system_keyboard(apis))

    elif data == "add_api":
        await query.answer()
        context.user_data["admin_flow"] = "add_api"
        context.user_data["api_step"] = "name"
        await query.edit_message_text("🔗 <b>Add API</b>\n\nStep 1: Type a <b>name</b> for this API:", parse_mode=ParseMode.HTML)

    elif data.startswith("del_api_"):
        name = data.replace("del_api_", "")
        await db.delete_api(name)
        await query.answer(f"✅ API '{name}' deleted.", show_alert=True)
        apis = await db.get_all_apis()
        text = "🔗 <b>API System</b>\n\n" + ("\n".join([f"✅ <b>{a['name']}</b>" for a in apis]) if apis else "No APIs configured.")
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=api_system_keyboard(apis))

    elif data.startswith("api_type_"):
        await query.answer()
        api_type = data.replace("api_type_", "")
        context.user_data["api_type"] = api_type
        context.user_data["api_step"] = "url"
        label = {
            "number_panel": "Number Panel 📱",
            "crapi":        "CRAPI Panel 🟢",
            "login":        "Login Panel 🔐",
            "other":        "Other Panel 🌐",
        }.get(api_type, api_type)
        step3_note = ""
        if api_type == "login":
            step3_note = "\n\n<i>Login panel: URL → Username → Password (no API key needed)</i>"
        await query.edit_message_text(
            f"🔗 <b>Add API — {label}</b>\n\nStep 3: Send the <b>API URL</b>:{step3_note}",
            parse_mode=ParseMode.HTML
        )

    elif data == "crapi_system_menu":
        await query.answer()
        apis = await db.get_all_apis()
        crapi_apis = [a for a in apis if a.get("api_type") in ("crapi", "login")]
        await query.edit_message_text(
            "🟢 <b>CRAPI / Login Panel</b>\n\nএখানে CRAPI ও Login type panels manage করো:",
            parse_mode=ParseMode.HTML,
            reply_markup=crapi_panel_keyboard(crapi_apis)
        )

    elif data == "add_crapi_panel":
        await query.answer()
        context.user_data["admin_flow"] = "add_api"
        context.user_data["api_type"]   = "crapi"
        context.user_data["api_step"]   = "name"
        await query.edit_message_text(
            "🟢 <b>Add CRAPI Panel</b>\n\n<b>Step 1:</b> Send a <b>name</b> for this panel:\n<i>(e.g. LAMIX, NUMBER PANEL)</i>",
            parse_mode=ParseMode.HTML
        )

    elif data == "add_login_panel":
        await query.answer()
        context.user_data["admin_flow"] = "add_api"
        context.user_data["api_type"]   = "login"
        context.user_data["api_step"]   = "name"
        await query.edit_message_text(
            "🔐 <b>Add Login Panel</b>\n\n<b>Step 1:</b> Send a <b>name</b> for this panel:\n<i>(e.g. HADI, MBC SMS)</i>",
            parse_mode=ParseMode.HTML
        )

    elif data.startswith("del_crapi_"):
        name = data[len("del_crapi_"):]
        await db.delete_api(name)
        await query.answer(f"✅ '{name}' deleted.", show_alert=True)
        apis = await db.get_all_apis()
        crapi_apis = [a for a in apis if a.get("api_type") in ("crapi", "login")]
        await query.edit_message_text(
            "🟢 <b>CRAPI / Login Panel</b>\n\nএখানে CRAPI ও Login type panels manage করো:",
            parse_mode=ParseMode.HTML,
            reply_markup=crapi_panel_keyboard(crapi_apis)
        )

    elif data == "scraping_system_menu":
        await query.answer()
        await query.edit_message_text("🕷 <b>Scraping System</b>\n\nChoose a panel:", parse_mode=ParseMode.HTML, reply_markup=scraping_system_keyboard())

    elif data == "scraping_agent_panel":
        await query.answer()
        scrapers = await db.get_all_scrapers()
        await query.edit_message_text("🤖 <b>Agent Panel</b>\n\nManage your scraping panels:", parse_mode=ParseMode.HTML, reply_markup=agent_panel_keyboard(scrapers))

    elif data == "agent_add_panel":
        await query.answer()
        context.user_data["admin_flow"] = "add_scraper"
        context.user_data["scraper_step"] = "name"
        await query.edit_message_text("➕ <b>Add Panel</b>\n\n<b>Step 1:</b> Send a <b>name</b> for this panel:", parse_mode=ParseMode.HTML)

    elif data.startswith("agent_del_"):
        name = data[len("agent_del_"):]
        await db.delete_scraper(name)
        await query.answer(f"✅ '{name}' deleted.", show_alert=True)
        scrapers = await db.get_all_scrapers()
        await query.edit_message_text("🤖 <b>Agent Panel</b>\n\nManage your scraping panels:", parse_mode=ParseMode.HTML, reply_markup=agent_panel_keyboard(scrapers))

    elif data == "scraping_client_panel":
        await query.answer()
        scrapers = await db.get_scrapers_by_type("client")
        await query.edit_message_text("👤 <b>Client Panel</b>\n\nManage your client scraping panels:", parse_mode=ParseMode.HTML, reply_markup=client_panel_keyboard(scrapers))

    elif data == "client_add_panel":
        await query.answer()
        context.user_data["admin_flow"] = "add_client_scraper"
        context.user_data["scraper_step"] = "name"
        await query.edit_message_text("➕ <b>Add Client Panel</b>\n\n<b>Step 1:</b> Send a <b>name</b> for this panel:", parse_mode=ParseMode.HTML)

    elif data.startswith("client_del_"):
        name = data[len("client_del_"):]
        await db.delete_scraper(name)
        await query.answer(f"✅ '{name}' deleted.", show_alert=True)
        scrapers = await db.get_scrapers_by_type("client")
        await query.edit_message_text("👤 <b>Client Panel</b>\n\nManage your client scraping panels:", parse_mode=ParseMode.HTML, reply_markup=client_panel_keyboard(scrapers))

# ============================================================
# LEADERBOARD COMMAND
# ============================================================

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # শুধু Owner/Admin এক্সেস
    if not await is_user_admin_or_owner(user_id):
        return

    rows = await db.get_daily_leaderboard(limit=1000)

    if not rows:
        await update.message.reply_text("📊 আজকে কোনো OTP রিসিভ হয়নি।")
        return

    lines = ["🏆 <b>Daily OTP Leaderboard</b>", "━━━━━━━━━━━━━━━━━━", ""]
    medals = ["🥇", "🥈", "🥉"]

    for i, row in enumerate(rows, 1):
        count = row["daily_otp_count"]
        if not count:
            break
        uid = row["user_id"]
        username = row.get("username") or ""
        full_name = row.get("full_name") or ""

        if username:
            display = f"@{username}"
        elif full_name:
            display = full_name
        else:
            display = f"UID:{uid}"

        medal = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{medal} {display} — <b>{count} OTP</b>")

    lines.append("")
    from datetime import datetime, timezone, timedelta
    bd_tz = timezone(timedelta(hours=6))
    now_bd = datetime.now(bd_tz)
    midnight = now_bd.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    hours_left = int((midnight - now_bd).seconds / 3600)

    lines.append("")
    lines.append(f"🔄 {hours_left} ঘন্টা পর রিসেট হবে")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling update: {context.error}", exc_info=True)

# ============================================================
# OTP REWARD HOLD — RELEASE LOOP
# ============================================================

async def start_reward_release_loop(bot, interval: int = 300):
    """প্রতি ৫ মিনিট পরপর চেক করে কোন hold-এ থাকা reward এর সময় শেষ হয়েছে কিনা, হলে balance-এ move করে"""
    while True:
        try:
            released = await db.release_matured_rewards()
            for r in released:
                try:
                    await bot.send_message(
                        chat_id=r["user_id"],
                        text=(
                            f"🔓 <b>Hold Reward Released!</b>\n"
                            f"💵 <b>Amount:</b> {r['amount']:.2f}৳\n"
                            f"📡 <b>Panel:</b> {r['panel_name']}\n\n"
                            f"এটি এখন আপনার main balance-এ যোগ হয়েছে।"
                        ),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"[RewardRelease] Failed to notify user {r['user_id']}: {e}")
        except Exception as e:
            logger.error(f"[RewardRelease] Loop error: {e}")
        await asyncio.sleep(interval)

# ============================================================
# POST INIT
# ============================================================

async def post_init(application: Application):
    await db.init_db()
    logger.info("✅ Bot started successfully!")
    from telegram import MenuButtonCommands, BotCommand
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 বট চালু করুন"),
        BotCommand("getnumber", "📞 নাম্বার সংগ্রহ করুন"),
        BotCommand("country", "🌍 Available Country দেখুন"),
        BotCommand("support", "☎️ সাপোর্টের সাথে যোগাযোগ করুন"),
        BotCommand("balance", "💰 ব্যালেন্স ও রেফার লিংক দেখুন"),
        BotCommand("withdraw", "💵 উইথড্র করুন"),
        BotCommand("top", "🏆 আজকের লিডারবোর্ড দেখুন"),
    ])
    otp_group_id = os.getenv("OTP_GROUP_ID", "") or OTP_GROUP_ID
    if otp_group_id:
        asyncio.create_task(start_api_polling(application.bot, otp_group_id))
        logger.info(f"🔄 API polling started for group: {otp_group_id}")
        asyncio.create_task(start_scraper_polling(application.bot, otp_group_id))
        logger.info(f"🕷 Scraper polling started for group: {otp_group_id}")
    asyncio.create_task(start_reward_release_loop(application.bot))
    logger.info("🔓 OTP reward hold-release loop started")

# ============================================================
# MAIN
# ============================================================

def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("getnumber", handle_get_number))
    application.add_handler(CommandHandler("country", handle_available_country))
    application.add_handler(CommandHandler("support", handle_support))
    application.add_handler(CommandHandler("balance", handle_balance))
    application.add_handler(CommandHandler("withdraw", handle_withdraw_menu))
    application.add_handler(CommandHandler("top", handle_leaderboard))
    application.add_handler(CommandHandler("myotp", handle_my_last_otp))

    import re as _re
    application.add_handler(MessageHandler(
        filters.Regex(_re.compile(r"(GET NUMBER|AVAILABLE COUNTRY|SUPPORT|BALANCE|WITHDRAW|LEADERBOARD|ADMIN PANEL|সর্বশেষ OTP)", _re.IGNORECASE)),
        handle_menu_buttons
    ))

    application.add_handler(CallbackQueryHandler(verify_join_callback,          pattern="^verify_join$"))
    application.add_handler(CallbackQueryHandler(verify_proof_channel_callback, pattern="^verify_proof_channel$"))
    application.add_handler(CallbackQueryHandler(leaderboard_refresh_callback,   pattern="^leaderboard_refresh$"))
    application.add_handler(CallbackQueryHandler(leaderboard_today_callback,     pattern="^leaderboard_today$"))
    application.add_handler(CallbackQueryHandler(leaderboard_yesterday_callback, pattern="^leaderboard_yesterday$"))
    application.add_handler(CallbackQueryHandler(leaderboard_close_callback,     pattern="^leaderboard_close$"))
    application.add_handler(CallbackQueryHandler(leaderboard_my_rank_callback,   pattern="^leaderboard_my_rank$"))
    application.add_handler(CallbackQueryHandler(service_selected_callback, pattern="^service_"))
    application.add_handler(CallbackQueryHandler(back_to_services_callback, pattern="^back_to_services$"))
    application.add_handler(CallbackQueryHandler(country_selected_callback, pattern="^country_"))
    application.add_handler(CallbackQueryHandler(change_number_callback,    pattern="^change_number$"))
    application.add_handler(CallbackQueryHandler(change_country_callback,   pattern="^change_country$"))
    application.add_handler(CallbackQueryHandler(copy_number_callback,      pattern="^copy_number_"))
    application.add_handler(CallbackQueryHandler(set_wallet_callback,        pattern="^set_wallet$"))
    application.add_handler(CallbackQueryHandler(do_withdraw_callback,       pattern="^do_withdraw$"))
    application.add_handler(CallbackQueryHandler(set_wallet_method_callback, pattern="^setwallet_"))
    application.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))
    application.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_main_menu$"))
    application.add_handler(CallbackQueryHandler(
        admin_callback_handler,
        pattern="^(admin_|back_to_admin|add_|del_|setting_|withdraw_complete|withdraw_reject|confirm_broadcast|skip_broadcast|addnum_cat_|api_system_menu|api_type_|crapi_system_menu|add_crapi_panel|add_login_panel|del_crapi_|scraping_system_menu|scraping_agent_panel|scraping_client_panel|scraping_evs_panel|evs_add_panel|evs_del_|agent_|client_|withdraw_method_toggle_menu|toggle_method_|admin_search_user|ban_user_|unban_user_|withdraw_system_toggle|referral_notify_toggle|bot_power|otp_reward_hold_menu|panelhold_|togglehide_)"
    ))

    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media_broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    application.add_error_handler(error_handler)

    logger.info("🚀 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
