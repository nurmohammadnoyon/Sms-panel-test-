import re
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from config import SERVICE_EMOJIS

# ============================================================
# HELPERS
# ============================================================

def _strip_country_code(number: str, country_code: str) -> str:
    """Return local number without + and without country code prefix."""
    clean = re.sub(r'[\s\-\+]', '', str(number))
    if country_code:
        cc = re.sub(r'\D', '', str(country_code))
        if clean.startswith(cc):
            return clean[len(cc):]
    return clean

# ============================================================
# MAIN MENU KEYBOARD (Reply Keyboard)
# ============================================================

def main_menu_keyboard(is_admin_user: bool = False):
    keyboard = [
        [KeyboardButton("📲 Get Number", style="primary"), KeyboardButton("🌍 Available Country", style="success")],
        [KeyboardButton("☎️ Support", style="success"), KeyboardButton("💰 Balance", style="primary")],
        [KeyboardButton("💵 Withdraw", style="primary"), KeyboardButton("🏆 Leaderboard", style="success")],
    ]
    if is_admin_user:
        keyboard.append([KeyboardButton("🛠 Admin Panel", style="success")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============================================================
# USER FLOW KEYBOARDS
# ============================================================

def services_keyboard(categories: list):
    buttons = []
    for cat in categories:
        emoji = cat["emoji"] if isinstance(cat, dict) else cat[2]
        name = cat["name"] if isinstance(cat, dict) else cat[1]
        buttons.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"service_{name}", style="success")])
    return InlineKeyboardMarkup(buttons)

def countries_keyboard(countries: list, category_name: str):
    buttons = []
    colors = ["primary", "success", "danger"]
    for i, c in enumerate(countries):
        flag = c["country_flag"]
        country = c["country_name"]
        count = c["available_numbers"]
        batch_id = c["batch_id"]
        code = c.get("country_code", "")
        rate = c.get("rate_per_otp", 0.0)
        code_str = f" (+{code})" if code else ""
        buttons.append([InlineKeyboardButton(
            f"{flag} {country}{code_str} - {count} | {rate:.2f}৳/OTP",
            callback_data=f"country_{batch_id}_{category_name}",
            style=colors[i % len(colors)]
        )])
    buttons.append([InlineKeyboardButton("⬅️ Back To Services", callback_data="back_to_services", style="danger")])
    return InlineKeyboardMarkup(buttons)

async def numbers_assigned_keyboard(assignments: list, otp_link: str, show_cc: bool = True):
    """
    Build keyboard for multiple assigned numbers.
    Display always shows the full number with country code.
    Tapping the button copies only the local number (country code stripped).
    """
    buttons = []
    for i, a in enumerate(assignments):
        number = a["number"]
        country_code = a.get("country_code", "")
        flag = a.get("country_flag", "")
        clean = re.sub(r'[\s\-\+]', '', str(number))
        full_with_plus = f"+{clean}"

        cc = re.sub(r'\D', '', str(country_code)) if country_code else ""
        local_number = clean[len(cc):] if cc and clean.startswith(cc) else clean

        # Display সবসময় country code সহ, কিন্তু কপি হবে country code ছাড়া local number
        display = full_with_plus
        copy_num = local_number
        label = f"{flag} {display}" if flag else display

        try:
            btn = InlineKeyboardButton(
                label,
                copy_text=CopyTextButton(copy_num),
                style="success"
            )
        except Exception:
            btn = InlineKeyboardButton(
                label,
                callback_data=f"copy_number_{copy_num}",
                style="success"
            )
        buttons.append([btn])

    buttons.append([InlineKeyboardButton("🔄 Change Number", callback_data="change_number", style="danger")])
    buttons.append([InlineKeyboardButton("🌍 Change Country", callback_data="change_country", style="success")])
    buttons.append([InlineKeyboardButton("🔑 Get OTP", url=otp_link, style="success")])
    return InlineKeyboardMarkup(buttons)

# Keep old single-number version for backwards compat
async def number_assigned_keyboard_with_link(number: str, flag: str, otp_link: str, country_code: str = ""):
    clean = re.sub(r'[\s\-\+]', '', str(number))
    full_with_plus = f"+{clean}"
    # Label: country code বাদ দিয়ে local number
    cc = re.sub(r'\D', '', str(country_code)) if country_code else ""
    local_number = clean[len(cc):] if cc and clean.startswith(cc) else clean
    label = f"{flag} {local_number}" if flag else local_number
    try:
        btn = InlineKeyboardButton(label, copy_text=CopyTextButton(local_number), style="success")
    except Exception:
        btn = InlineKeyboardButton(label, callback_data=f"copy_number_{local_number}", style="success")
    buttons = [
        [btn],
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number", style="danger")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="change_country", style="success")],
        [InlineKeyboardButton("🔑 Get OTP", url=otp_link, style="success")],
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# BALANCE KEYBOARDS
# ============================================================

def wallet_card_keyboard():
    buttons = [
        [
            InlineKeyboardButton("💳 Set Wallet", callback_data="set_wallet", style="success"),
            InlineKeyboardButton("📤 Withdraw", callback_data="do_withdraw", style="success"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

WITHDRAW_METHODS = [
    ("💠 Binance UID", "BinanceUID"),
    ("🟢 BEP20",       "BEP20"),
    ("🔺 TRX",         "TRX"),
    ("💗 bKash",       "bKash"),
    ("🟠 Nagad",       "Nagad"),
]

def payment_method_keyboard(disabled: list = None):
    """User-facing payment method keyboard — disabled method গুলো দেখাবে না"""
    disabled = disabled or []
    buttons = []
    row = []
    for label, key in WITHDRAW_METHODS:
        if key in disabled:
            continue
        row.append(InlineKeyboardButton(label, callback_data=f"setwallet_{key}", style="success"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def withdraw_method_toggle_keyboard(disabled: list = None):
    """Admin — প্রতিটা method ON/OFF toggle করার keyboard"""
    disabled = disabled or []
    buttons = []
    for label, key in WITHDRAW_METHODS:
        is_on = key not in disabled
        status = "✅ ON" if is_on else "❌ OFF"
        color  = "success" if is_on else "danger"
        buttons.append([InlineKeyboardButton(
            f"{label} — {status}",
            callback_data=f"toggle_method_{key}",
            style=color
        )])
    buttons.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# OTP REWARD HOLD KEYBOARD
# ============================================================

def panel_hold_menu_keyboard(panels: list):
    """প্রতিটা প্যানেলের জন্য Hold ON/OFF টগল + Days এডিট বাটন"""
    buttons = []
    for p in panels:
        name = p["panel_name"]
        enabled = bool(p["hold_enabled"])
        days = p["hold_days"]
        status = f"✅ ON ({days}d)" if enabled else "❌ OFF"
        color = "success" if enabled else "danger"
        buttons.append([
            InlineKeyboardButton(f"{name} — {status}", callback_data=f"panelhold_toggle_{name}", style=color),
            InlineKeyboardButton("⏱ Days", callback_data=f"panelhold_days_{name}", style="primary"),
        ])
    if not panels:
        buttons.append([InlineKeyboardButton("কোনো প্যানেল পাওয়া যায়নি", callback_data="noop", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# LEADERBOARD KEYBOARD
# ============================================================

def leaderboard_keyboard(active: str = "today"):
    today_style     = "primary" if active != "yesterday" else "primary"
    yesterday_style = "success" if active == "yesterday" else "success"
    buttons = [
        [
            InlineKeyboardButton("📅 Today",      callback_data="leaderboard_today",     style="primary"),
            InlineKeyboardButton("📆 Yesterday",  callback_data="leaderboard_yesterday", style="success"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh",   callback_data="leaderboard_refresh",   style="primary"),
            InlineKeyboardButton("❌ Close",      callback_data="leaderboard_close",     style="danger"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# SUPPORT KEYBOARD
# ============================================================

def support_keyboard(support_username: str = ""):
    uname = (support_username or "Md_Alamin_islam9").lstrip("@")
    buttons = [
        [InlineKeyboardButton("☎️ Contact Support", url=f"https://t.me/{uname}", style="success")],
        [InlineKeyboardButton("☎️ Contact Developer", url="https://t.me/d4kxo", style="success")],
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# ADMIN PANEL KEYBOARD
# ============================================================

def admin_panel_keyboard(withdraw_on: bool = True, referral_notify_on: bool = True):
    wd_label = "🟢 Withdraw ON" if withdraw_on else "🔴 Withdraw OFF"
    wd_style = "success" if withdraw_on else "danger"
    rn_label = "🟢 Refer Notify ON" if referral_notify_on else "🔴 Refer Notify OFF"
    rn_style = "success" if referral_notify_on else "danger"
    buttons = [
        [
            InlineKeyboardButton("➕ Add Numbers", callback_data="admin_add_numbers", style="success"),
            InlineKeyboardButton("📁 Manage Numbers", callback_data="admin_manage_numbers", style="success"),
        ],
        [
            InlineKeyboardButton("📂 Manage Categories", callback_data="admin_manage_categories", style="success"),
            InlineKeyboardButton("💸 Withdraw Requests", callback_data="admin_withdraw_requests", style="success"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style="danger"),
            InlineKeyboardButton("👤 Admin List", callback_data="admin_list", style="success"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings", style="success"),
            InlineKeyboardButton("📣 Req. Channels", callback_data="admin_req_channels", style="success"),
        ],
        [
            InlineKeyboardButton("👮 Add Admin", callback_data="admin_add_admin", style="success"),
            InlineKeyboardButton("🚫 Remove Admin", callback_data="admin_remove_admin", style="danger"),
        ],
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance", style="success"),
            InlineKeyboardButton("➖ Remove Balance", callback_data="admin_remove_balance", style="danger"),
        ],
        [
            InlineKeyboardButton("💰 User Balances", callback_data="admin_user_balances", style="success"),
            InlineKeyboardButton("🔗 Manage API", callback_data="admin_manage_api", style="success"),
        ],
        [
            InlineKeyboardButton("💳 Withdraw Method ON/OFF", callback_data="withdraw_method_toggle_menu", style="success"),
            InlineKeyboardButton("🤖 Bot Control", callback_data="bot_power_menu", style="danger"),
        ],
        [
            InlineKeyboardButton(wd_label, callback_data="withdraw_system_toggle", style=wd_style),
        ],
        [
            InlineKeyboardButton(rn_label, callback_data="referral_notify_toggle", style=rn_style),
        ],
        [
            InlineKeyboardButton("🔒 OTP Reward Hold", callback_data="otp_reward_hold_menu", style="primary"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_main_menu", style="success"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# SETTINGS KEYBOARD
# ============================================================

def settings_keyboard():
    buttons = [
        [InlineKeyboardButton("✏️ Edit Support Username", callback_data="setting_support_username", style="success")],
        [InlineKeyboardButton("✏️ Edit Referral Amount (৳)", callback_data="setting_referral_amount", style="success")],
        [InlineKeyboardButton("✏️ Edit Min Withdraw (৳)", callback_data="setting_min_withdraw", style="success")],
        [InlineKeyboardButton("✏️ Edit OTP Group Link 🔗", callback_data="setting_otp_group_link", style="success")],
        [InlineKeyboardButton("✏️ Edit Main Channel Link 📢", callback_data="setting_main_channel_link", style="success")],
        [InlineKeyboardButton("💰 Edit Payment Proof Channel Link", callback_data="setting_payment_proof_channel_link", style="success")],
        [InlineKeyboardButton("🆔 Edit Payment Proof Channel ID", callback_data="setting_payment_proof_channel_id", style="success")],
        [InlineKeyboardButton("⏱ OTP Grace Period (minutes)", callback_data="setting_otp_grace_minutes", style="primary")],
        [InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="danger")],
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# CATEGORY MANAGEMENT KEYBOARD
# ============================================================

def category_management_keyboard(categories: list):
    buttons = [[InlineKeyboardButton("➕ Add Category", callback_data="add_category", style="success")]]
    for cat in categories:
        name = cat["name"] if isinstance(cat, dict) else cat[1]
        buttons.append([InlineKeyboardButton(f"🗑 Delete {name}", callback_data=f"del_category_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# MANAGE NUMBERS KEYBOARD
# ============================================================

def manage_numbers_keyboard(batches: list):
    buttons = []
    for batch in batches:
        bid = batch["id"]
        is_hidden = batch.get("is_hidden")
        hide_label = "🙈 Unhide" if is_hidden else "🙉 Hide"
        buttons.append([
            InlineKeyboardButton(f"🗑 Delete ID {bid}", callback_data=f"del_batch_{bid}", style="danger"),
            InlineKeyboardButton(hide_label, callback_data=f"togglehide_{bid}", style="primary" if is_hidden else "success"),
        ])
    buttons.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# WITHDRAW REQUEST KEYBOARD (Admin)
# ============================================================

def withdraw_action_keyboard(request_id: int):
    buttons = [
        [
            InlineKeyboardButton("✅ Complete", callback_data=f"withdraw_complete_{request_id}", style="success"),
            InlineKeyboardButton("❌ Reject", callback_data=f"withdraw_reject_{request_id}", style="danger"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# REQUIRED CHANNELS KEYBOARD
# ============================================================

def req_channels_keyboard(channels: list):
    buttons = [[InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel", style="success")]]
    for ch in channels:
        cid = ch["id"]
        link = ch["channel_link"]
        buttons.append([InlineKeyboardButton(f"🗑 Delete: {link[:30]}", callback_data=f"del_channel_{cid}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# API MANAGEMENT KEYBOARD
# ============================================================

def api_management_keyboard(apis: list):
    buttons = [
        [
            InlineKeyboardButton("🔗 API System", callback_data="api_system_menu", style="success"),
            InlineKeyboardButton("🕷 Scraping System", callback_data="scraping_system_menu", style="success"),
        ],
        [InlineKeyboardButton("⬅️ Back to Panel", callback_data="back_to_admin_panel", style="danger")],
    ]
    return InlineKeyboardMarkup(buttons)

def crapi_panel_keyboard(apis: list = None):
    """CRAPI ও Login type API গুলো দেখাবে"""
    apis = apis or []
    buttons = [
        [InlineKeyboardButton("➕ Add CRAPI Panel", callback_data="add_crapi_panel", style="success")],
        [InlineKeyboardButton("➕ Add Login Panel", callback_data="add_login_panel", style="success")],
    ]
    for api in apis:
        name     = api["name"]
        api_type = api.get("api_type", "crapi")
        icon     = "🟢" if api_type == "crapi" else "🔐"
        buttons.append([InlineKeyboardButton(f"{icon} {name} — ❌ Delete", callback_data=f"del_crapi_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_manage_api", style="success")])
    return InlineKeyboardMarkup(buttons)

def api_system_keyboard(apis: list):
    buttons = []
    for api in apis:
        name = api["name"]
        api_type = api.get("api_type", "other")
        type_label = {
            "number_panel": "📱",
            "crapi":        "🟢",
            "login":        "🔐",
            "other":        "🌐",
        }.get(api_type, "🌐")
        buttons.append([InlineKeyboardButton(f"✅ {type_label} {name}", callback_data=f"del_api_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("➕ Add API", callback_data="add_api", style="success")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_manage_api", style="success")])
    return InlineKeyboardMarkup(buttons)

def api_type_keyboard():
    buttons = [
        [InlineKeyboardButton("📱 Number Panel",  callback_data="api_type_number_panel", style="success")],
        [InlineKeyboardButton("🟢 CRAPI Panel",   callback_data="api_type_crapi",        style="success")],
        [InlineKeyboardButton("🔐 Login Panel",   callback_data="api_type_login",        style="success")],
        [InlineKeyboardButton("🌐 Other Panel",   callback_data="api_type_other",        style="success")],
    ]
    return InlineKeyboardMarkup(buttons)

def scraping_system_keyboard():
    buttons = [
        [InlineKeyboardButton("🔷 EVS Panel", callback_data="scraping_evs_panel", style="success")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_manage_api", style="danger")],
    ]
    return InlineKeyboardMarkup(buttons)

def evs_panel_keyboard(scrapers: list = None):
    scrapers = scrapers or []
    buttons = [
        [InlineKeyboardButton("➕ Add EVS Panel", callback_data="evs_add_panel", style="success")],
    ]
    for s in scrapers:
        name = s["name"] if isinstance(s, dict) else s
        buttons.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"evs_del_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="scraping_system_menu", style="success")])
    return InlineKeyboardMarkup(buttons)

def agent_panel_keyboard(scrapers: list = None):
    scrapers = scrapers or []
    buttons = [
        [InlineKeyboardButton("➕ Add Panel", callback_data="agent_add_panel", style="success")],
    ]
    for s in scrapers:
        name = s["name"] if isinstance(s, dict) else s
        buttons.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"agent_del_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="scraping_system_menu", style="success")])
    return InlineKeyboardMarkup(buttons)

def client_panel_keyboard(scrapers: list = None):
    scrapers = scrapers or []
    buttons = [
        [InlineKeyboardButton("➕ Add Panel", callback_data="client_add_panel", style="success")],
    ]
    for s in scrapers:
        name = s["name"] if isinstance(s, dict) else s
        buttons.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"client_del_{name}", style="danger")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="scraping_system_menu", style="success")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# ADD NUMBERS STEP KEYBOARDS
# ============================================================

def add_numbers_service_keyboard(categories: list):
    colors = ["primary", "success", "danger"]
    buttons = []
    for i, cat in enumerate(categories):
        emoji = cat["emoji"] if isinstance(cat, dict) else cat[2]
        name = cat["name"] if isinstance(cat, dict) else cat[1]
        buttons.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"addnum_cat_{name}", style=colors[i % len(colors)])])
    return InlineKeyboardMarkup(buttons)

def broadcast_confirm_keyboard():
    buttons = [
        [
            InlineKeyboardButton("📢 Broadcast to Users", callback_data="confirm_broadcast", style="success"),
            InlineKeyboardButton("❌ Skip", callback_data="skip_broadcast", style="danger"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# CHANNEL JOIN VERIFICATION KEYBOARD
# ============================================================

def channel_join_keyboard(channels: list):
    buttons = []
    for ch in channels:
        link = ch["channel_link"]
        buttons.append([InlineKeyboardButton("📢 Join Channel", url=link, style="success")])
    buttons.append([InlineKeyboardButton("✅ I've Joined — Verify", callback_data="verify_join", style="success")])
    return InlineKeyboardMarkup(buttons)
