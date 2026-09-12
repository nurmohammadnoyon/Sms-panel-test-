import aiohttp
import asyncio
import logging
import re
import time
import requests
from database import (
    get_all_apis, get_assignment_by_number, get_all_assignments_map,
    reward_user_for_otp, save_otp_to_number, get_setting, get_user_balance,
    get_grace_period_user, get_panel_hold_setting,
    log_otp_event, mark_otp_delivered, mark_otp_permanently_failed, increment_otp_attempt,
)

logger = logging.getLogger(__name__)

async def _deliver_otp_dm(bot, user_id: int, number: str, otp: str, service: str,
                           sms_text: str, text: str, reply_markup, source: str = ""):
    """
    OTP DM ইউজারকে delivery-guarantee সহ পাঠায়:
    - প্রথমে otp_log-এ লগ হয়, তারপর ৩ বার তাৎক্ষণিক retry।
    - সব কটা fail করলেও log-টা থেকে যায় — scraper.py-এর global redelivery sweep
      প্রতি ২০ সেকেন্ডে (২৪ ঘণ্টা পর্যন্ত) আবার পাঠানোর চেষ্টা করতে থাকে,
      ফলে সাময়িক নেটওয়ার্ক/টেলিগ্রাম সমস্যায় কোনো OTP আর হারিয়ে যায় না —
      গ্রুপে এলেও বটে না-আসার সমস্যাটা এখানেই সমাধান হয়।
    - ইউজার বট ব্লক/deactivated করলে সাথে সাথে permanently_failed মার্ক হয়ে
      retry বন্ধ হয়ে যায় (অন্য ইউজারদের delivery আটকে থাকে না)।
    """
    log_id = await log_otp_event(number, otp, service, sms_text, user_id=user_id)
    last_err = None
    for attempt in range(3):
        try:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML", reply_markup=reply_markup)
            await mark_otp_delivered(log_id)
            return
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str or "chat not found" in err_str:
                await mark_otp_permanently_failed(log_id)
                logger.warning(f"[{source}] User {user_id} unreachable — OTP log #{log_id} permanently marked: {e}")
                return
            await increment_otp_attempt(log_id)
            await asyncio.sleep(1.5)
    logger.error(f"[{source}] Failed to DM user {user_id} after retries: {last_err} (log #{log_id} queued for redelivery sweep)")

async def _reward_line_and_balance(user_id: int, rate: float, panel_name: str, bot, before_reward_fn):
    """
    Reward দেয়/hold করে, এবং DM মেসেজে দেখানোর জন্য সঠিক লাইন + balance রিটার্ন করে।
    before_reward_fn: reward_user_for_otp(user_id, rate, bot=bot, panel_name=panel_name) কল করার async callable
    """
    hold = await get_panel_hold_setting(panel_name) if panel_name else None
    is_hold = bool(hold and hold["hold_enabled"])
    await before_reward_fn()
    bal = await get_user_balance(user_id)
    if is_hold:
        days = hold["hold_days"]
        reward_line = f"🔒 <b>HOLD</b> +{rate:.2f}৳ ({days} দিন পর ব্যালেন্সে যোগ হবে)"
    else:
        reward_line = f"🚨 <b>ADDED</b> +{rate:.2f}৳"
    return reward_line, bal

def _find_in_amap(amap: dict, clean_number: str):
    """assignments map-এ number খোঁজো — exact, endswith, suffix match"""
    cn = clean_number.lstrip("+")
    # 1. Exact match
    for key in [cn, "+" + cn]:
        if key in amap:
            return amap[key]
    # 2. endswith — panel country code সহ দিলেও মিলবে
    for num_key, val in amap.items():
        nk = num_key.lstrip("+")
        if nk.endswith(cn) or cn.endswith(nk):
            return val
    # 3. last 8-9 digit suffix match (যদি country code উভয় দিকে থাকে)
    for suffix_len in [9, 8, 7]:
        if len(cn) >= suffix_len:
            suffix = cn[-suffix_len:]
            for num_key, val in amap.items():
                if num_key.lstrip("+").endswith(suffix):
                    return val
    return None

async def _find_assignment(clean_number: str):
    """সব format-এ assignment খোঁজো — DB + cache + grace period"""
    cn = clean_number.lstrip("+")

    # 1. Active assignment খোঁজো
    a = await get_assignment_by_number(cn)
    if a:
        return a

    # 2. Cache force-refresh করে map-এ খোঁজো
    global _amap_cache, _amap_cache_time
    _amap_cache_time = 0
    amap = await _get_amap()
    result = _find_in_amap(amap, cn)
    if result:
        return result

    # 3. Grace period — number change করা user-এর কাছে পাঠাও (rate-সহ, reward miss হবে না)
    try:
        grace_min = int(await get_setting("otp_grace_minutes") or "0")
        if grace_min > 0:
            grace_user = await get_grace_period_user(cn, grace_min)
            if grace_user:
                return {
                    "user_id": grace_user["user_id"],
                    "rate_per_otp": grace_user.get("rate_per_otp") or 0,
                    "country_name": grace_user.get("country_name") or "Unknown",
                    "country_flag": grace_user.get("country_flag") or "🌍",
                    "number": cn,
                }
    except Exception:
        pass

    return None
from datetime import datetime

# ─── Login Panel Session Cache (for crapi/login type panels) ────────────────
_login_sessions: dict = {}       # {base_url: requests.Session}
_login_fail_times: dict = {}     # {base_url: timestamp}

def _get_login_session(panel: dict):
    """Username+Password দিয়ে login করে session নেওয়া (math captcha auto-solve)"""
    base_url = panel.get("api_url", "").rstrip("/")
    username = panel.get("username", "")
    password = panel.get("password", "")

    if not username or not password:
        return None

    if base_url in _login_sessions:
        return _login_sessions[base_url]

    if base_url in _login_fail_times:
        if time.time() - _login_fail_times[base_url] < 300:
            return None
        else:
            del _login_fail_times[base_url]

    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})

        login_url = base_url + "/login"
        r = session.get(login_url, timeout=10)

        # Math captcha solve
        captcha_match = re.search(r'What is (\d+)\s*([+\-])\s*(\d+)', r.text)
        captcha_ans = ""
        if captcha_match:
            a, op, b = int(captcha_match.group(1)), captcha_match.group(2), int(captcha_match.group(3))
            captcha_ans = str(a + b if op == "+" else a - b)

        csrf_match = re.search(r'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', r.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""

        field_combos = [
            {"username": username, "password": password, "captcha": captcha_ans, "submit": "LOGIN"},
            {"username": username, "password": password, "answer": captcha_ans, "submit": "LOGIN"},
            {"email": username, "password": password, "captcha": captcha_ans, "submit": "LOGIN"},
            {"user": username, "pass": password, "captcha": captcha_ans, "submit": "LOGIN"},
            {"username": username, "password": password, "math_answer": captcha_ans},
            {"username": username, "password": password, "security": captcha_ans},
        ]
        if csrf_token:
            for combo in field_combos:
                combo["_token"] = csrf_token

        for payload in field_combos:
            try:
                r2 = session.post(login_url, data=payload, timeout=10, allow_redirects=True)
                if ("logout" in r2.text.lower() or "dashboard" in r2.text.lower()
                        or "SMSCDRReports" in r2.text
                        or (r2.url and "login" not in r2.url.lower())):
                    _login_sessions[base_url] = session
                    logger.info(f"[Login Panel] {base_url} — Login SUCCESS")
                    return session
            except Exception:
                continue

        _login_fail_times[base_url] = time.time()
        logger.warning(f"[Login Panel] {base_url} — Login FAILED (retry in 5min)")
        return None
    except Exception as e:
        _login_fail_times[base_url] = time.time()
        logger.error(f"[Login Panel] {base_url} — Error: {e}")
        return None


def _fetch_login_panel_sms(panel: dict, number: str = None) -> list:
    """Login panel (SMSCDRReports) থেকে SMS fetch করা"""
    base_url = panel.get("api_url", "").rstrip("/")
    session = _get_login_session(panel)
    if not session:
        _login_sessions.pop(base_url, None)
        return []

    try:
        sms_url = base_url + "/agent/SMSCDRReports"
        params = {"draw": 1, "start": 0, "length": 50}
        if number:
            params["search[value]"] = number

        r = session.get(sms_url, params=params,
                        headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10)

        # Rate limit detect করো — session clear করে ৩ মিনিট অপেক্ষা করো
        if r.status_code != 200 or "accessed this site too many times" in r.text.lower():
            logger.warning(f"[Login Panel] {base_url} — Rate limited, clearing session (retry in 3min)")
            _login_sessions.pop(base_url, None)
            _login_fail_times[base_url] = time.time() - 120  # 3 min cooldown (300-120=180s remaining)
            return []

        records = []
        try:
            data_j = r.json()
            if "data" in data_j:
                raw = data_j["data"]
                for row in raw:
                    if isinstance(row, list) and len(row) >= 4:
                        rec = {
                            "number": str(row[2]).strip() if len(row) > 2 else "",
                            "sms":    str(row[5]).strip() if len(row) > 5 else "",
                            "app_name": str(row[4]).strip() if len(row) > 4 else "",
                            "dt":     str(row[0]).strip() if len(row) > 0 else "",
                        }
                        if rec["number"] and rec["sms"]:
                            records.append(rec)
                    elif isinstance(row, dict):
                        records.append(row)
                return records
        except Exception:
            pass

        # Fallback: HTML table parse
        r2 = session.get(sms_url, timeout=10)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r2.text, re.DOTALL)
        for row in rows:
            cols = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cols = [re.sub(r'<[^>]+>', '', c).strip() for c in cols]
            if len(cols) >= 6:
                phone_col = cols[2].replace("+", "").replace(" ", "")
                sms_col   = cols[5] if len(cols) > 5 else ""
                cli_col   = cols[4] if len(cols) > 4 else ""
                dt_col    = cols[0] if len(cols) > 0 else ""
                if phone_col.isdigit() and len(phone_col) >= 8 and sms_col:
                    if number and phone_col != number.replace("+", ""):
                        continue
                    records.append({"number": phone_col, "sms": sms_col,
                                    "app_name": cli_col, "dt": dt_col})
        return records
    except Exception:
        _login_sessions.pop(base_url, None)
        return []

def detect_service(message: str) -> str:
    ml = message.lower()
    services = {
        "WHATSAPP": ["whatsapp", "واتساب"],
        "FACEBOOK": ["facebook", "fb", "meta"],
        "INSTAGRAM": ["instagram", "insta"],
        "TELEGRAM": ["telegram"],
        "TWITTER": ["twitter", "x.com"],
        "TIKTOK": ["tiktok"],
        "SNAPCHAT": ["snapchat"],
        "GOOGLE": ["google", "gmail"],
        "UBER": ["uber"],
        "DISCORD": ["discord"],
        "LINKEDIN": ["linkedin"],
        "NETFLIX": ["netflix"],
        "AMAZON": ["amazon"],
        "PAYPAL": ["paypal"],
        "MICROSOFT": ["microsoft", "outlook", "hotmail"],
        "APPLE": ["apple", "icloud"],
        "BINANCE": ["binance"],
        "VIBER": ["viber"],
        "SIGNAL": ["signal"],
        "YOUTUBE": ["youtube"],
    }
    for svc, keywords in services.items():
        for kw in keywords:
            if kw in ml:
                return svc
    return "SMS"

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton

_sent_otps = {}
_last_seen_dt = {}

# ── Assignment cache — প্রতি ৩০ সেকেন্ডে refresh হবে ─────────────────────
_amap_cache: dict = {}
_amap_cache_time: float = 0
_AMAP_TTL = 30  # seconds

async def _get_amap() -> dict:
    """Cached assignment map — বারবার DB call না করে cache থেকে নেবে"""
    global _amap_cache, _amap_cache_time
    now = time.time()
    if now - _amap_cache_time > _AMAP_TTL:
        try:
            _amap_cache = await get_all_assignments_map()
            _amap_cache_time = now
        except Exception:
            pass
    return _amap_cache

# ── Pending OTP retry — assignment না পেলে ৬০ সেকেন্ড retry করবে ──────────
# {key: {"api_name", "clean_number", "otp", "sms_text", "first_seen", "retries"}}
_pending_otps: dict = {}
_PENDING_MAX_AGE = 120   # seconds
_PENDING_MAX_RETRY = 12  # বেশি retry

def extract_otp(message: str) -> str:
    # Pattern 1: dash বা space দিয়ে joined — যেমন "689 702" বা "689-702"
    m = re.search(r'(?<!\d)(\d{3,4})[\s\-](\d{3,4})(?!\d)', message)
    if m:
        return m.group(1) + m.group(2)
    # Pattern 2: # দিয়ে শুরু space-separated — যেমন "# 689 702"
    m = re.search(r'#\s*(\d{3,4})\s+(\d{3,4})(?!\d)', message)
    if m:
        return m.group(1) + m.group(2)
    # Pattern 3: continuous digits 4-8
    m = re.search(r'(?<![\d])(\d{4,8})(?![\d])', message)
    if m:
        return m.group(1)
    return "N/A"

COUNTRY_CODES = {
    "880":  ("Bangladesh", "🇧🇩"),
    "91":   ("India", "🇮🇳"),
    "92":   ("Pakistan", "🇵🇰"),
    "94":   ("Sri Lanka", "🇱🇰"),
    "95":   ("Myanmar", "🇲🇲"),
    "960":  ("Maldives", "🇲🇻"),
    "961":  ("Lebanon", "🇱🇧"),
    "962":  ("Jordan", "🇯🇴"),
    "963":  ("Syria", "🇸🇾"),
    "964":  ("Iraq", "🇮🇶"),
    "965":  ("Kuwait", "🇰🇼"),
    "966":  ("Saudi Arabia", "🇸🇦"),
    "967":  ("Yemen", "🇾🇪"),
    "968":  ("Oman", "🇴🇲"),
    "970":  ("Palestine", "🇵🇸"),
    "971":  ("UAE", "🇦🇪"),
    "972":  ("Israel", "🇮🇱"),
    "973":  ("Bahrain", "🇧🇭"),
    "974":  ("Qatar", "🇶🇦"),
    "975":  ("Bhutan", "🇧🇹"),
    "976":  ("Mongolia", "🇲🇳"),
    "977":  ("Nepal", "🇳🇵"),
    "98":   ("Iran", "🇮🇷"),
    "992":  ("Tajikistan", "🇹🇯"),
    "993":  ("Turkmenistan", "🇹🇲"),
    "994":  ("Azerbaijan", "🇦🇿"),
    "995":  ("Georgia", "🇬🇪"),
    "996":  ("Kyrgyzstan", "🇰🇬"),
    "998":  ("Uzbekistan", "🇺🇿"),
    "60":   ("Malaysia", "🇲🇾"),
    "62":   ("Indonesia", "🇮🇩"),
    "63":   ("Philippines", "🇵🇭"),
    "65":   ("Singapore", "🇸🇬"),
    "66":   ("Thailand", "🇹🇭"),
    "670":  ("Timor-Leste", "🇹🇱"),
    "673":  ("Brunei", "🇧🇳"),
    "675":  ("Papua New Guinea", "🇵🇬"),
    "679":  ("Fiji", "🇫🇯"),
    "81":   ("Japan", "🇯🇵"),
    "82":   ("South Korea", "🇰🇷"),
    "84":   ("Vietnam", "🇻🇳"),
    "855":  ("Cambodia", "🇰🇭"),
    "856":  ("Laos", "🇱🇦"),
    "86":   ("China", "🇨🇳"),
    "886":  ("Taiwan", "🇹🇼"),
    "93":   ("Afghanistan", "🇦🇫"),
    "7":    ("Russia", "🇷🇺"),
    "77":   ("Kazakhstan", "🇰🇿"),
    "30":   ("Greece", "🇬🇷"),
    "31":   ("Netherlands", "🇳🇱"),
    "32":   ("Belgium", "🇧🇪"),
    "33":   ("France", "🇫🇷"),
    "34":   ("Spain", "🇪🇸"),
    "350":  ("Gibraltar", "🇬🇮"),
    "351":  ("Portugal", "🇵🇹"),
    "352":  ("Luxembourg", "🇱🇺"),
    "353":  ("Ireland", "🇮🇪"),
    "354":  ("Iceland", "🇮🇸"),
    "355":  ("Albania", "🇦🇱"),
    "356":  ("Malta", "🇲🇹"),
    "357":  ("Cyprus", "🇨🇾"),
    "358":  ("Finland", "🇫🇮"),
    "359":  ("Bulgaria", "🇧🇬"),
    "36":   ("Hungary", "🇭🇺"),
    "370":  ("Lithuania", "🇱🇹"),
    "371":  ("Latvia", "🇱🇻"),
    "372":  ("Estonia", "🇪🇪"),
    "373":  ("Moldova", "🇲🇩"),
    "374":  ("Armenia", "🇦🇲"),
    "375":  ("Belarus", "🇧🇾"),
    "380":  ("Ukraine", "🇺🇦"),
    "381":  ("Serbia", "🇷🇸"),
    "382":  ("Montenegro", "🇲🇪"),
    "385":  ("Croatia", "🇭🇷"),
    "386":  ("Slovenia", "🇸🇮"),
    "387":  ("Bosnia", "🇧🇦"),
    "389":  ("North Macedonia", "🇲🇰"),
    "39":   ("Italy", "🇮🇹"),
    "40":   ("Romania", "🇷🇴"),
    "41":   ("Switzerland", "🇨🇭"),
    "420":  ("Czech Republic", "🇨🇿"),
    "421":  ("Slovakia", "🇸🇰"),
    "43":   ("Austria", "🇦🇹"),
    "44":   ("UK", "🇬🇧"),
    "45":   ("Denmark", "🇩🇰"),
    "46":   ("Sweden", "🇸🇪"),
    "47":   ("Norway", "🇳🇴"),
    "48":   ("Poland", "🇵🇱"),
    "49":   ("Germany", "🇩🇪"),
    "90":   ("Turkey", "🇹🇷"),
    "20":   ("Egypt", "🇪🇬"),
    "212":  ("Morocco", "🇲🇦"),
    "213":  ("Algeria", "🇩🇿"),
    "216":  ("Tunisia", "🇹🇳"),
    "218":  ("Libya", "🇱🇾"),
    "220":  ("Gambia", "🇬🇲"),
    "221":  ("Senegal", "🇸🇳"),
    "222":  ("Mauritania", "🇲🇷"),
    "223":  ("Mali", "🇲🇱"),
    "224":  ("Guinea", "🇬🇳"),
    "225":  ("Ivory Coast", "🇨🇮"),
    "226":  ("Burkina Faso", "🇧🇫"),
    "227":  ("Niger", "🇳🇪"),
    "228":  ("Togo", "🇹🇬"),
    "229":  ("Benin", "🇧🇯"),
    "230":  ("Mauritius", "🇲🇺"),
    "231":  ("Liberia", "🇱🇷"),
    "232":  ("Sierra Leone", "🇸🇱"),
    "233":  ("Ghana", "🇬🇭"),
    "234":  ("Nigeria", "🇳🇬"),
    "235":  ("Chad", "🇹🇩"),
    "237":  ("Cameroon", "🇨🇲"),
    "238":  ("Cape Verde", "🇨🇻"),
    "241":  ("Gabon", "🇬🇦"),
    "243":  ("Congo DR", "🇨🇩"),
    "244":  ("Angola", "🇦🇴"),
    "249":  ("Sudan", "🇸🇩"),
    "250":  ("Rwanda", "🇷🇼"),
    "251":  ("Ethiopia", "🇪🇹"),
    "252":  ("Somalia", "🇸🇴"),
    "254":  ("Kenya", "🇰🇪"),
    "255":  ("Tanzania", "🇹🇿"),
    "256":  ("Uganda", "🇺🇬"),
    "260":  ("Zambia", "🇿🇲"),
    "263":  ("Zimbabwe", "🇿🇼"),
    "27":   ("South Africa", "🇿🇦"),
    "1":    ("USA/Canada", "🇺🇸"),
    "52":   ("Mexico", "🇲🇽"),
    "55":   ("Brazil", "🇧🇷"),
    "57":   ("Colombia", "🇨🇴"),
    "58":   ("Venezuela", "🇻🇪"),
    "54":   ("Argentina", "🇦🇷"),
    "56":   ("Chile", "🇨🇱"),
    "51":   ("Peru", "🇵🇪"),
    "61":   ("Australia", "🇦🇺"),
    "64":   ("New Zealand", "🇳🇿"),
}

SERVICE_EMOJI = {
    "WHATSAPP": "📱", "FACEBOOK": "📘", "INSTAGRAM": "📸", "TELEGRAM": "✈️",
    "TWITTER": "🐦", "TIKTOK": "🎵", "SNAPCHAT": "👻", "GOOGLE": "🔵",
    "UBER": "🚗", "DISCORD": "🎮", "LINKEDIN": "💼", "NETFLIX": "🎬",
    "AMAZON": "🛒", "PAYPAL": "💳", "MICROSOFT": "🪟", "APPLE": "🍎",
    "BINANCE": "🟡", "VIBER": "💜", "SIGNAL": "🔒", "YOUTUBE": "▶️",
    "SMS": "✉️",
}

def get_language_from_message(message: str) -> str:
    """Detect the language of the OTP message text itself (not the country)."""
    if not message:
        return "English"
    text = message.strip()

    # Script-based detection (non-Latin alphabets are unambiguous)
    if re.search(r'[\u0600-\u06FF]', text):
        return "Arabic"
    if re.search(r'[\u0400-\u04FF]', text):
        return "Russian"
    if re.search(r'[\u4E00-\u9FFF]', text):
        return "Chinese"
    if re.search(r'[\u3040-\u30FF]', text):
        return "Japanese"
    if re.search(r'[\uAC00-\uD7A3]', text):
        return "Korean"
    if re.search(r'[\u0900-\u097F]', text):
        return "Hindi"
    if re.search(r'[\u0980-\u09FF]', text):
        return "Bengali"
    if re.search(r'[\u0E00-\u0E7F]', text):
        return "Thai"
    if re.search(r'[\u0590-\u05FF]', text):
        return "Hebrew"
    if re.search(r'[\u0370-\u03FF]', text):
        return "Greek"

    # Latin-script keyword detection (common OTP wording per language)
    ml = text.lower()
    keyword_langs = [
        ("French",     ["votre code", "code de vérification", "est votre code", "ne le partagez"]),
        ("Spanish",    ["su código", "código de verificación", "es tu código", "no lo compartas"]),
        ("Portuguese", ["seu código", "código de verificação", "não compartilhe"]),
        ("German",     ["ihr code", "verifizierungscode", "ihr bestätigungscode"]),
        ("Italian",    ["il tuo codice", "codice di verifica"]),
        ("Indonesian", ["kode verifikasi", "kode anda", "jangan bagikan"]),
        ("Malay",      ["kod pengesahan", "kod anda"]),
        ("Vietnamese", ["mã xác minh", "mã của bạn"]),
        ("Turkish",    ["doğrulama kodu", "kodunuz"]),
        ("Filipino",   ["ang iyong code", "verification code mo"]),
    ]
    for lang, keywords in keyword_langs:
        for kw in keywords:
            if kw in ml:
                return lang

    return "English"

def get_service_emoji(service: str) -> str:
    return SERVICE_EMOJI.get(service.upper(), "📲")

def detect_country_from_number(number: str):
    clean = re.sub(r'[\s\-\+]', '', number)
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
        if clean.startswith(code):
            name, flag = COUNTRY_CODES[code]
            return name, flag
    return "Unknown", "🌍"

def _local_number(clean: str, country_code: str = "") -> str:
    """Country code বাদ দিয়ে local number দেয়। clean = digits only (no +)"""
    if country_code:
        cc = re.sub(r'\D', '', str(country_code))
        if clean.startswith(cc):
            return clean[len(cc):]
    # COUNTRY_CODES dict থেকেও চেষ্টা করি
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
        if clean.startswith(code):
            return clean[len(code):]
    return clean

async def _process_crapi_records(bot, api_name: str, records: list, otp_group_id: str):
    """CRAPI / Login panel রেকর্ড প্রসেস করে OTP পাঠায়।"""
    for record in records:
        sms_text = (record.get("sms") or record.get("message") or
                    record.get("body") or record.get("text") or
                    record.get("SMS") or "")
        phone = str(record.get("number") or record.get("Number") or
                    record.get("num") or record.get("NUM") or "")
        if not sms_text or not phone:
            continue

        clean_number = re.sub(r'[^\d]', '', phone)
        if not clean_number:
            continue

        # OTP extract — space/dash joined আগে চেক করো
        otp_match = re.search(r'(?<!\d)(\d{3,4})[\s\-](\d{3,4})(?!\d)', sms_text)
        if otp_match:
            otp = otp_match.group(1) + otp_match.group(2)
        else:
            otp_match = re.search(r'#\s*(\d{3,4})\s+(\d{3,4})(?!\d)', sms_text)
            if otp_match:
                otp = otp_match.group(1) + otp_match.group(2)
            else:
                otp_match = re.search(r'(?<!\d)(\d{4,8})(?!\d)', sms_text)
                if not otp_match:
                    continue
                otp = otp_match.group(1).strip()

        # Duplicate check
        key = f"{api_name}:{clean_number}:{otp}"
        if key in _sent_otps:
            continue
        _sent_otps[key] = True

        # DB save + user lookup
        await save_otp_to_number(clean_number, otp)
        assignment = await _find_assignment(clean_number)

        if assignment and assignment.get("country_name") and assignment["country_name"] != "Unknown":
            country_flag = assignment["country_flag"]
            country_name = assignment["country_name"]
        else:
            country_name, country_flag = detect_country_from_number(clean_number)

        app_name_field = (record.get("app_name") or record.get("service") or
                          record.get("client") or record.get("CLI") or "")
        detected = detect_service(sms_text)
        if detected and detected not in ("SMS", "GENERAL", "Unknown"):
            service = detected
        elif app_name_field:
            service = app_name_field.upper()
        else:
            service = detect_service(sms_text)

        masked = ("+" + clean_number[:4] + "❖AH™❖" + clean_number[-4:] if len(clean_number) > 8 else clean_number)

        try:
            support_username = await get_setting("support_username") or "@support"
            _cl = await get_setting("main_channel_link") or await get_setting("otp_group_link") or ""
            channel_link = _cl if _cl.startswith("https://t.me/") else "https://t.me/AH_EARNING_METHOD"
        except Exception:
            support_username = "@support"
            channel_link = "https://t.me/AH_EARNING_METHOD"

        try:
            bot_info = await bot.get_me()
            bot_link = f"https://t.me/{bot_info.username}"
        except Exception:
            bot_link = "https://t.me/bot"

        service_emoji = get_service_emoji(service)
        language = get_language_from_message(sms_text)

        group_msg = (
            f"{country_flag} #{country_name.replace(' ', '')} {service_emoji} #{service}\n"
            f"{masked} #{language}"
        )

        try:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                copy_text=CopyTextButton(otp)
            )
        except Exception:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                callback_data=f"copy_text_{otp}"
            )

        keyboard = InlineKeyboardMarkup([
            [otp_btn],
            [
                InlineKeyboardButton("📲 Get Number", url=bot_link, style="danger"),
                InlineKeyboardButton("📢 Main Channel", url=channel_link, style="danger"),
            ],
        ])

        try:
            if otp_group_id:
                gid = int(otp_group_id) if str(otp_group_id).lstrip('-').isdigit() else otp_group_id
                await bot.send_message(chat_id=gid, text=group_msg,
                                       parse_mode="HTML", reply_markup=keyboard)
                logger.info(f"[{api_name}] ✅ CRAPI OTP sent: {otp} for {masked}")
        except Exception as e:
            logger.error(f"[{api_name}] Failed to send to OTP group: {e}")

        if assignment:
            user_id = assignment["user_id"]
            rate = assignment["rate_per_otp"]
            if rate > 0:
                reward_line, bal = await _reward_line_and_balance(
                    user_id, rate, api_name, bot,
                    lambda: reward_user_for_otp(user_id, rate, bot=bot, panel_name=api_name)
                )
            else:
                from database import increment_otp_count
                await increment_otp_count(user_id)
                reward_line = "🎁 <b>Reward:</b> N/A"
                bal = await get_user_balance(user_id)
            user_msg = (
                f"🎉 <b>NEW OTP RECEIVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 {country_name} {country_flag} [{service}] {service_emoji}\n"
                f"💎 [+{clean_number}] 🎉\n"
                f"{reward_line}\n"
                f"🧔 <b>BALANCE</b> {bal:.2f}৳"
            )
            try:
                dm_btn = InlineKeyboardButton(
                    f"{otp}", copy_text=CopyTextButton(otp)
                )
            except Exception:
                dm_btn = InlineKeyboardButton(
                    f"{otp}", callback_data=f"copy_text_{otp}"
                )
            await _deliver_otp_dm(
                bot, user_id, clean_number, otp, service, sms_text, user_msg,
                InlineKeyboardMarkup([[dm_btn]]), source=api_name
            )
        else:
            # কোনো assignment (active/grace) পাওয়া যায়নি — otp_log-এ log করে রাখো,
            # shared redelivery sweep প্রতি ২০ সেকেন্ডে আবার assignment খুঁজে DM পাঠাবে
            await log_otp_event(clean_number, otp, service, sms_text, user_id=None)
    items = []

    if api_type == "number_panel":
        raw = data
        if isinstance(raw, dict):
            raw = raw.get("data", raw)
        if not isinstance(raw, list):
            raw = [raw]
        if raw and isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list):
            raw = raw[0]
        for entry in raw:
            if isinstance(entry, list) and len(entry) >= 3:
                items.append({
                    "cli":     str(entry[0]) if len(entry) > 0 else "Unknown",
                    "num":     str(entry[1]) if len(entry) > 1 else "",
                    "message": str(entry[2]) if len(entry) > 2 else "",
                    "dt":      str(entry[3]) if len(entry) > 3 else "",
                })
            elif isinstance(entry, dict):
                items.append(entry)
    else:
        raw = data
        if isinstance(raw, dict):
            raw = raw.get("data", [raw])
        if not isinstance(raw, list):
            raw = [raw]
        items = [dict(i) if isinstance(i, dict) else {} for i in raw]

    items = sorted(items, key=lambda x: x.get("dt", ""))
    new_max_dt = _last_seen_dt.get(api_name, "")

    for item in items:
        dt      = item.get("dt", "")
        number  = str(item.get("number") or item.get("num", ""))
        message = item.get("message", "")
        app     = item.get("app") or item.get("cli", "Unknown")

        if not number or not message:
            continue

        if dt and dt <= _last_seen_dt.get(api_name, ""):
            continue

        otp = extract_otp(message)
        clean_number = re.sub(r'[\s\-\+]', '', number)

        key = f"{api_name}:{clean_number}:{otp}"
        if key in _sent_otps:
            if dt > new_max_dt:
                new_max_dt = dt
            continue
        _sent_otps[key] = True

        await save_otp_to_number(clean_number, otp)

        assignment = await _find_assignment(clean_number)

        if assignment and assignment.get("country_name") and assignment["country_name"] != "Unknown":
            country_flag = assignment["country_flag"]
            country_name = assignment["country_name"]
        else:
            country_name, country_flag = detect_country_from_number(clean_number)

        detected = detect_service(message) if message else None
        if detected and detected not in ("SMS", "GENERAL", "Unknown"):
            service = detected
        elif app and app not in ("Unknown", ""):
            service = app.upper()
        else:
            service = detect_service(message)

        masked = ("+" + clean_number[:4] + "❖AH™❖" + clean_number[-4:] if len(clean_number) > 8 else clean_number)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            support_username = await get_setting("support_username") or "@support"
            _cl = await get_setting("main_channel_link") or await get_setting("otp_group_link") or ""
            channel_link = _cl if _cl.startswith("https://t.me/") else "https://t.me/AH_EARNING_METHOD"
        except Exception:
            support_username = "@support"
            channel_link = "https://t.me/otpgroup"

        support_clean = support_username.replace("@", "")

        try:
            bot_info = await bot.get_me()
            bot_link = f"https://t.me/{bot_info.username}"
        except Exception:
            bot_link = "https://t.me/bot"

        service_emoji = get_service_emoji(service)
        language = get_language_from_message(message)

        group_msg = (
            f"{country_flag} #{country_name.replace(' ', '')} {service_emoji} #{service}\n"
            f"{masked} #{language}"
        )

        try:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                copy_text=CopyTextButton(otp),
                style="success"
            )
        except Exception:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                callback_data=f"copy_text_{otp}",
                style="success"
            )

        keyboard = InlineKeyboardMarkup([
            [otp_btn],
            [
                InlineKeyboardButton("📲 Get Number", url=bot_link, style="danger"),
                InlineKeyboardButton("📢 Main Channel", url=channel_link, style="danger"),
            ],
        ])

        try:
            if otp_group_id:
                gid = int(otp_group_id) if str(otp_group_id).lstrip('-').isdigit() else otp_group_id
                await bot.send_message(chat_id=gid, text=group_msg, parse_mode="HTML", reply_markup=keyboard)
                logger.info(f"✅ OTP sent: {otp} for {masked}")
        except Exception as e:
            logger.error(f"Failed to send to OTP group: {e}")

        if assignment:
            user_id = assignment["user_id"]
            rate = assignment["rate_per_otp"]
            service_emoji_dm = get_service_emoji(service)
            if rate > 0:
                reward_line, bal = await _reward_line_and_balance(
                    user_id, rate, api_name, bot,
                    lambda: reward_user_for_otp(user_id, rate, bot=bot, panel_name=api_name)
                )
            else:
                from database import increment_otp_count
                await increment_otp_count(user_id)
                reward_line = "🎁 <b>Reward:</b> N/A"
                bal = await get_user_balance(user_id)
            user_msg = (
                f"🎉 <b>NEW OTP RECEIVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 {country_name} {country_flag} [{service}] {service_emoji_dm}\n"
                f"💎 [+{clean_number}] 🎉\n"
                f"{reward_line}\n"
                f"🧔 <b>BALANCE</b> {bal:.2f}৳"
            )
            try:
                dm_otp_btn = InlineKeyboardButton(
                    f"{otp}",
                    copy_text=CopyTextButton(otp),
                    style="success"
                )
            except Exception:
                dm_otp_btn = InlineKeyboardButton(
                    f"{otp}",
                    callback_data=f"copy_text_{otp}",
                    style="success"
                )
            dm_keyboard = InlineKeyboardMarkup([[dm_otp_btn]])
            await _deliver_otp_dm(
                bot, user_id, clean_number, otp, service, message, user_msg,
                dm_keyboard, source=api_name
            )
        else:
            # কোনো assignment পাওয়া যায়নি — redelivery sweep-এর জন্য লগ করে রাখো
            await log_otp_event(clean_number, otp, service, message, user_id=None)

        if dt > new_max_dt:
            new_max_dt = dt

    if new_max_dt:
        _last_seen_dt[api_name] = new_max_dt

async def process_api_response(bot, api_name: str, api_type: str, data, otp_group_id: str):
    items = []

    if api_type == "number_panel":
        raw = data
        if isinstance(raw, dict):
            raw = raw.get("data", raw)
        if not isinstance(raw, list):
            raw = [raw]
        if raw and isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list):
            raw = raw[0]
        for entry in raw:
            if isinstance(entry, list) and len(entry) >= 3:
                items.append({
                    "cli":     str(entry[0]) if len(entry) > 0 else "Unknown",
                    "num":     str(entry[1]) if len(entry) > 1 else "",
                    "message": str(entry[2]) if len(entry) > 2 else "",
                    "dt":      str(entry[3]) if len(entry) > 3 else "",
                })
            elif isinstance(entry, dict):
                items.append(entry)
    else:
        raw = data
        if isinstance(raw, dict):
            raw = raw.get("data", [raw])
        if not isinstance(raw, list):
            raw = [raw]
        items = [dict(i) if isinstance(i, dict) else {} for i in raw]

    items = sorted(items, key=lambda x: x.get("dt", ""))
    new_max_dt = _last_seen_dt.get(api_name, "")

    for item in items:
        dt      = item.get("dt", "")
        number  = str(item.get("number") or item.get("num", ""))
        message = item.get("message", "")
        app     = item.get("app") or item.get("cli", "Unknown")

        if not number or not message:
            continue

        if dt and dt <= _last_seen_dt.get(api_name, ""):
            continue

        otp = extract_otp(message)
        clean_number = re.sub(r'[\s\-\+]', '', number)

        key = f"{api_name}:{clean_number}:{otp}"
        if key in _sent_otps:
            if dt > new_max_dt:
                new_max_dt = dt
            continue
        _sent_otps[key] = True

        await save_otp_to_number(clean_number, otp)

        assignment = await _find_assignment(clean_number)

        if assignment and assignment.get("country_name") and assignment["country_name"] != "Unknown":
            country_flag = assignment["country_flag"]
            country_name = assignment["country_name"]
        else:
            country_name, country_flag = detect_country_from_number(clean_number)

        detected = detect_service(message) if message else None
        if detected and detected not in ("SMS", "GENERAL", "Unknown"):
            service = detected
        elif app and app not in ("Unknown", ""):
            service = app.upper()
        else:
            service = detect_service(message)

        masked = ("+" + clean_number[:4] + "❖AH™❖" + clean_number[-4:] if len(clean_number) > 8 else clean_number)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            support_username = await get_setting("support_username") or "@support"
            _cl = await get_setting("main_channel_link") or await get_setting("otp_group_link") or ""
            channel_link = _cl if _cl.startswith("https://t.me/") else "https://t.me/AH_EARNING_METHOD"
        except Exception:
            support_username = "@support"
            channel_link = "https://t.me/otpgroup"

        support_clean = support_username.replace("@", "")

        try:
            bot_info = await bot.get_me()
            bot_link = f"https://t.me/{bot_info.username}"
        except Exception:
            bot_link = "https://t.me/bot"

        service_emoji = get_service_emoji(service)
        language = get_language_from_message(message)

        group_msg = (
            f"{country_flag} #{country_name.replace(' ', '')} {service_emoji} #{service}\n"
            f"{masked} #{language}"
        )

        try:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                copy_text=CopyTextButton(otp),
                style="success"
            )
        except Exception:
            otp_btn = InlineKeyboardButton(
                f"OTP {otp}",
                callback_data=f"copy_text_{otp}",
                style="success"
            )

        keyboard = InlineKeyboardMarkup([
            [otp_btn],
            [
                InlineKeyboardButton("📲 Get Number", url=bot_link, style="danger"),
                InlineKeyboardButton("📢 Main Channel", url=channel_link, style="danger"),
            ],
        ])

        try:
            if otp_group_id:
                gid = int(otp_group_id) if str(otp_group_id).lstrip('-').isdigit() else otp_group_id
                await bot.send_message(chat_id=gid, text=group_msg, parse_mode="HTML", reply_markup=keyboard)
                logger.info(f"✅ OTP sent: {otp} for {masked}")
        except Exception as e:
            logger.error(f"Failed to send to OTP group: {e}")

        if assignment:
            user_id = assignment["user_id"]
            rate = assignment["rate_per_otp"]
            service_emoji_dm = get_service_emoji(service)
            if rate > 0:
                reward_line, bal = await _reward_line_and_balance(
                    user_id, rate, api_name, bot,
                    lambda: reward_user_for_otp(user_id, rate, bot=bot, panel_name=api_name)
                )
            else:
                from database import increment_otp_count
                await increment_otp_count(user_id)
                reward_line = "🎁 <b>Reward:</b> N/A"
                bal = await get_user_balance(user_id)
            user_msg = (
                f"🎉 <b>NEW OTP RECEIVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 {country_name} {country_flag} [{service}] {service_emoji_dm}\n"
                f"💎 [+{clean_number}] 🎉\n"
                f"{reward_line}\n"
                f"🧔 <b>BALANCE</b> {bal:.2f}৳"
            )
            try:
                dm_otp_btn = InlineKeyboardButton(
                    f"{otp}",
                    copy_text=CopyTextButton(otp),
                    style="success"
                )
            except Exception:
                dm_otp_btn = InlineKeyboardButton(
                    f"{otp}",
                    callback_data=f"copy_text_{otp}",
                    style="success"
                )
            dm_keyboard = InlineKeyboardMarkup([[dm_otp_btn]])
            await _deliver_otp_dm(
                bot, user_id, clean_number, otp, service, message, user_msg,
                dm_keyboard, source=api_name
            )
        else:
            # কোনো assignment পাওয়া যায়নি — redelivery sweep-এর জন্য লগ করে রাখো
            await log_otp_event(clean_number, otp, service, message, user_id=None)

        if dt > new_max_dt:
            new_max_dt = dt

    if new_max_dt:
        _last_seen_dt[api_name] = new_max_dt


async def retry_pending_otps(bot, otp_group_id: str):
    """Pending OTP গুলো retry করো — assignment পেলে DM পাঠাও"""
    if not _pending_otps:
        return
    now = time.time()
    to_delete = []
    # Cache refresh করো
    await _get_amap()

    for pkey, info in list(_pending_otps.items()):
        # বেশি পুরানো হলে বাদ দাও
        if now - info["first_seen"] > _PENDING_MAX_AGE:
            to_delete.append(pkey)
            logger.warning(f"[Pending] ⏰ Expired: {info['clean_number']} OTP {info['otp']}")
            continue
        if info["retries"] >= _PENDING_MAX_RETRY:
            to_delete.append(pkey)
            continue

        assignment = await _find_assignment(info["clean_number"])
        info["retries"] += 1

        if assignment:
            to_delete.append(pkey)
            logger.info(f"[Pending] ✅ Found assignment for {info['clean_number']} on retry #{info['retries']}")
            # DM পাঠাও
            try:
                user_id = assignment["user_id"]
                rate    = assignment.get("rate_per_otp", 0)
                country_flag = assignment.get("country_flag", "🌍")
                country_name = assignment.get("country_name", "Unknown")
                otp     = info["otp"]
                sms_text = info["sms_text"]
                service = detect_service(sms_text)
                service_emoji = get_service_emoji(service)
                clean_number = info["clean_number"]
                panel_name = info.get("api_name")
                if rate > 0:
                    reward_line, bal = await _reward_line_and_balance(
                        user_id, rate, panel_name, bot,
                        lambda: reward_user_for_otp(user_id, rate, bot=bot, panel_name=panel_name)
                    )
                else:
                    from database import increment_otp_count
                    await increment_otp_count(user_id)
                    reward_line = "🎁 <b>Reward:</b> N/A"
                    bal = await get_user_balance(user_id)
                user_msg = (
                    f"🎉 <b>NEW OTP RECEIVED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💎 {country_name} {country_flag} [{service}] {service_emoji}\n"
                    f"💎 [+{clean_number}] 🎉\n"
                    f"{reward_line}\n"
                    f"🧔 <b>BALANCE</b> {bal:.2f}৳"
                )
                try:
                    dm_btn = InlineKeyboardButton(
                        f"{otp}", copy_text=CopyTextButton(otp), style="success"
                    )
                except Exception:
                    dm_btn = InlineKeyboardButton(
                        f"{otp}", callback_data=f"copy_text_{otp}", style="success"
                    )
                await bot.send_message(
                    chat_id=user_id, text=user_msg,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[dm_btn]])
                )
            except Exception as e:
                logger.error(f"[Pending] DM send error: {e}")

    for k in to_delete:
        _pending_otps.pop(k, None)

async def start_api_polling(bot, otp_group_id: str, interval: int = 2):
    logger.info(f"🔄 API polling started (every {interval}s) for group: {otp_group_id}")
    _last_login_poll: dict = {}  # {api_name: timestamp} — login panel throttle
    while True:
        try:
            apis = await get_all_apis()
            if apis:
                async with aiohttp.ClientSession() as session:
                    for api in apis:
                        api = dict(api)
                        api_type = api.get("api_type", "other")
                        api_name = api["name"]

                        # Login/Hadi panel: poll every 15s instead of 2s to avoid rate limit
                        if api_type in ("login", "hadi"):
                            last = _last_login_poll.get(api_name, 0)
                            if time.time() - last < 15:
                                continue
                            _last_login_poll[api_name] = time.time()

                        try:
                            if api_type == "crapi":
                                url = api['api_url'].rstrip("/")
                                params = {"token": api['api_key'], "records": 20}
                                async with session.get(url, params=params,
                                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                    if resp.status != 200:
                                        logger.warning(f"[{api_name}] HTTP {resp.status}")
                                        continue
                                    try:
                                        raw = await resp.json(content_type=None)
                                    except Exception:
                                        txt = await resp.text()
                                        logger.warning(f"[{api_name}] JSON parse error: {txt[:200]}")
                                        continue
                                    records = []
                                    if isinstance(raw, list):
                                        records = raw
                                    elif isinstance(raw, dict):
                                        for key in ("data", "records", "sms"):
                                            if raw.get(key):
                                                records = raw[key]
                                                break
                                    await _process_crapi_records(bot, api_name, records, otp_group_id)

                            elif api_type in ("login", "hadi"):
                                records = await asyncio.to_thread(_fetch_login_panel_sms, api)
                                await _process_crapi_records(bot, api_name, records, otp_group_id)

                            else:
                                url = f"{api['api_url']}?token={api['api_key']}"
                                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                    if resp.status != 200:
                                        logger.warning(f"[{api_name}] HTTP {resp.status}")
                                        continue
                                    text = await resp.text()
                                    if not text or not text.strip():
                                        logger.warning(f"[{api_name}] Empty response")
                                        continue
                                    try:
                                        data = await resp.json(content_type=None)
                                    except (ValueError, aiohttp.ContentTypeError) as json_err:
                                        logger.error(f"[{api_name}] JSON parsing failed: {json_err}. Response: {text[:200]}")
                                        continue
                                    await process_api_response(bot, api_name, api_type, data, otp_group_id)

                        except Exception as e:
                            logger.error(f"API polling error [{api_name}]: {e}")

        except Exception as e:
            logger.error(f"API polling loop error: {e}")

        # Pending OTP retry
        try:
            await retry_pending_otps(bot, otp_group_id)
        except Exception as e:
            logger.error(f"Pending retry error: {e}")

        await asyncio.sleep(interval)

async def check_api_health(api_url: str, api_key: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{api_url}?token={api_key}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                return resp.status == 200
    except Exception:
        return False
