"""
====================================================
  SCRAPER.PY — Web Scraping OTP System
  Reads credentials from DB (scrapers table),
  logs into panel, fetches OTPs, forwards to bot
====================================================
"""

import time
import asyncio
import aiohttp
import requests
import json
import re
import logging
from datetime import datetime, date, timedelta
from urllib.parse import quote_plus
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from api_handler import get_service_emoji, get_language_from_message

from database import (
    get_all_scrapers,
    get_assignment_by_number,
    get_grace_period_user,
    reward_user_for_otp,
    save_otp_to_number,
    get_setting,
    get_panel_hold_setting,
    get_user_balance,
    log_otp_event,
    mark_otp_delivered,
    set_otp_log_user,
    increment_otp_attempt,
    get_undelivered_otps,
    mark_otp_permanently_failed,
)

try:
    from config import OWNER_ID
except Exception:
    OWNER_ID = None

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────
AJAX_PATH_AGENT  = "/ints/client/res/data_smscdr.php"
AJAX_PATH_CLIENT = "/ints/client/res/data_smscdr.php"
REFRESH_INTERVAL = 2
TIMEOUT          = 50
MAX_RETRIES      = 3
RETRY_DELAY      = 5

IDX_DATE   = 0
IDX_NUMBER = 2
IDX_SMS    = 4

# ─── Per-scraper state ────────────────────────────────────────
_scraper_sessions: dict  = {}   # name → requests.Session
_scraper_logged_in: dict = {}   # name → bool
_sent_keys: dict         = {}   # name → set of sent unique keys

COUNTRY_CODES = {
    "1": ("USA/Canada", "🇺🇸"),
    "7": ("Russia", "🇷🇺"),
    "20": ("Egypt", "🇪🇬"),
    "27": ("South Africa", "🇿🇦"),
    "30": ("Greece", "🇬🇷"),
    "31": ("Netherlands", "🇳🇱"),
    "32": ("Belgium", "🇧🇪"),
    "33": ("France", "🇫🇷"),
    "34": ("Spain", "🇪🇸"),
    "36": ("Hungary", "🇭🇺"),
    "39": ("Italy", "🇮🇹"),
    "40": ("Romania", "🇷🇴"),
    "41": ("Switzerland", "🇨🇭"),
    "43": ("Austria", "🇦🇹"),
    "44": ("UK", "🇬🇧"),
    "45": ("Denmark", "🇩🇰"),
    "46": ("Sweden", "🇸🇪"),
    "47": ("Norway", "🇳🇴"),
    "48": ("Poland", "🇵🇱"),
    "49": ("Germany", "🇩🇪"),
    "51": ("Peru", "🇵🇪"),
    "52": ("Mexico", "🇲🇽"),
    "53": ("Cuba", "🇨🇺"),
    "54": ("Argentina", "🇦🇷"),
    "55": ("Brazil", "🇧🇷"),
    "56": ("Chile", "🇨🇱"),
    "57": ("Colombia", "🇨🇴"),
    "58": ("Venezuela", "🇻🇪"),
    "60": ("Malaysia", "🇲🇾"),
    "61": ("Australia", "🇦🇺"),
    "62": ("Indonesia", "🇮🇩"),
    "63": ("Philippines", "🇵🇭"),
    "64": ("New Zealand", "🇳🇿"),
    "65": ("Singapore", "🇸🇬"),
    "66": ("Thailand", "🇹🇭"),
    "81": ("Japan", "🇯🇵"),
    "82": ("South Korea", "🇰🇷"),
    "84": ("Vietnam", "🇻🇳"),
    "86": ("China", "🇨🇳"),
    "90": ("Turkey", "🇹🇷"),
    "91": ("India", "🇮🇳"),
    "92": ("Pakistan", "🇵🇰"),
    "93": ("Afghanistan", "🇦🇫"),
    "94": ("Sri Lanka", "🇱🇰"),
    "95": ("Myanmar", "🇲🇲"),
    "98": ("Iran", "🇮🇷"),
    "211": ("South Sudan", "🇸🇸"),
    "212": ("Morocco", "🇲🇦"),
    "213": ("Algeria", "🇩🇿"),
    "216": ("Tunisia", "🇹🇳"),
    "218": ("Libya", "🇱🇾"),
    "220": ("Gambia", "🇬🇲"),
    "221": ("Senegal", "🇸🇳"),
    "222": ("Mauritania", "🇲🇷"),
    "223": ("Mali", "🇲🇱"),
    "224": ("Guinea", "🇬🇳"),
    "225": ("Ivory Coast", "🇨🇮"),
    "226": ("Burkina Faso", "🇧🇫"),
    "227": ("Niger", "🇳🇪"),
    "228": ("Togo", "🇹🇬"),
    "229": ("Benin", "🇧🇯"),
    "230": ("Mauritius", "🇲🇺"),
    "231": ("Liberia", "🇱🇷"),
    "232": ("Sierra Leone", "🇸🇱"),
    "233": ("Ghana", "🇬🇭"),
    "234": ("Nigeria", "🇳🇬"),
    "235": ("Chad", "🇹🇩"),
    "237": ("Cameroon", "🇨🇲"),
    "238": ("Cape Verde", "🇨🇻"),
    "240": ("Eq. Guinea", "🇬🇶"),
    "241": ("Gabon", "🇬🇦"),
    "242": ("Congo", "🇨🇬"),
    "243": ("Congo DR", "🇨🇩"),
    "244": ("Angola", "🇦🇴"),
    "245": ("Guinea-Bissau", "🇬🇼"),
    "248": ("Seychelles", "🇸🇨"),
    "249": ("Sudan", "🇸🇩"),
    "250": ("Rwanda", "🇷🇼"),
    "251": ("Ethiopia", "🇪🇹"),
    "252": ("Somalia", "🇸🇴"),
    "253": ("Djibouti", "🇩🇯"),
    "254": ("Kenya", "🇰🇪"),
    "255": ("Tanzania", "🇹🇿"),
    "256": ("Uganda", "🇺🇬"),
    "257": ("Burundi", "🇧🇮"),
    "258": ("Mozambique", "🇲🇿"),
    "260": ("Zambia", "🇿🇲"),
    "261": ("Madagascar", "🇲🇬"),
    "263": ("Zimbabwe", "🇿🇼"),
    "264": ("Namibia", "🇳🇦"),
    "265": ("Malawi", "🇲🇼"),
    "266": ("Lesotho", "🇱🇸"),
    "267": ("Botswana", "🇧🇼"),
    "268": ("Eswatini", "🇸🇿"),
    "350": ("Gibraltar", "🇬🇮"),
    "351": ("Portugal", "🇵🇹"),
    "352": ("Luxembourg", "🇱🇺"),
    "353": ("Ireland", "🇮🇪"),
    "354": ("Iceland", "🇮🇸"),
    "355": ("Albania", "🇦🇱"),
    "356": ("Malta", "🇲🇹"),
    "357": ("Cyprus", "🇨🇾"),
    "358": ("Finland", "🇫🇮"),
    "359": ("Bulgaria", "🇧🇬"),
    "370": ("Lithuania", "🇱🇹"),
    "371": ("Latvia", "🇱🇻"),
    "372": ("Estonia", "🇪🇪"),
    "373": ("Moldova", "🇲🇩"),
    "374": ("Armenia", "🇦🇲"),
    "375": ("Belarus", "🇧🇾"),
    "380": ("Ukraine", "🇺🇦"),
    "381": ("Serbia", "🇷🇸"),
    "385": ("Croatia", "🇭🇷"),
    "386": ("Slovenia", "🇸🇮"),
    "387": ("Bosnia", "🇧🇦"),
    "420": ("Czech Republic", "🇨🇿"),
    "421": ("Slovakia", "🇸🇰"),
    "502": ("Guatemala", "🇬🇹"),
    "503": ("El Salvador", "🇸🇻"),
    "504": ("Honduras", "🇭🇳"),
    "505": ("Nicaragua", "🇳🇮"),
    "506": ("Costa Rica", "🇨🇷"),
    "507": ("Panama", "🇵🇦"),
    "509": ("Haiti", "🇭🇹"),
    "591": ("Bolivia", "🇧🇴"),
    "592": ("Guyana", "🇬🇾"),
    "593": ("Ecuador", "🇪🇨"),
    "595": ("Paraguay", "🇵🇾"),
    "597": ("Suriname", "🇸🇷"),
    "598": ("Uruguay", "🇺🇾"),
    "880": ("Bangladesh", "🇧🇩"),
    "886": ("Taiwan", "🇹🇼"),
    "960": ("Maldives", "🇲🇻"),
    "961": ("Lebanon", "🇱🇧"),
    "962": ("Jordan", "🇯🇴"),
    "963": ("Syria", "🇸🇾"),
    "964": ("Iraq", "🇮🇶"),
    "965": ("Kuwait", "🇰🇼"),
    "966": ("Saudi Arabia", "🇸🇦"),
    "967": ("Yemen", "🇾🇪"),
    "968": ("Oman", "🇴🇲"),
    "970": ("Palestine", "🇵🇸"),
    "971": ("UAE", "🇦🇪"),
    "972": ("Israel", "🇮🇱"),
    "973": ("Bahrain", "🇧🇭"),
    "974": ("Qatar", "🇶🇦"),
    "975": ("Bhutan", "🇧🇹"),
    "976": ("Mongolia", "🇲🇳"),
    "977": ("Nepal", "🇳🇵"),
    "992": ("Tajikistan", "🇹🇯"),
    "993": ("Turkmenistan", "🇹🇲"),
    "994": ("Azerbaijan", "🇦🇿"),
    "995": ("Georgia", "🇬🇪"),
    "996": ("Kyrgyzstan", "🇰🇬"),
    "998": ("Uzbekistan", "🇺🇿"),
}

# ─── Helpers ──────────────────────────────────────────────────

def _get_country(number: str):
    clean = re.sub(r"[\s\-\+]", "", number)
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
        if clean.startswith(code):
            name, flag = COUNTRY_CODES[code]
            return name, flag
    return "Unknown", "🌍"


def _mask_number(number: str) -> str:
    n = re.sub(r"[\s\-]", "", number)
    if not n.startswith("+"):
        n = "+" + n.lstrip("+")
    if len(n) > 8:
        return n[:4] + "XXXX" + n[-4:]
    return n


def _extract_otp(message: str) -> str:
    patterns = [
        r'(?:code|rمز|كود|verification|otp|pin)[:\s]+[‎]?(\d{3,8}(?:[- ]\d{3,4})?)',
        r'(\d{3,4})[-](\d{3,4})',
        r'\b(\d{4,8})\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, message, re.IGNORECASE)
        if m:
            if len(m.groups()) > 1 and m.group(2):
                return m.group(1) + m.group(2)
            return m.group(1).replace(" ", "").replace("-", "")
    return "N/A"


def _detect_service(message: str) -> str:
    ml = message.lower()
    services = {
        "WHATSAPP": ["whatsapp", "واتساب"],
        "FACEBOOK": ["facebook", "fb", "meta"],
        "INSTAGRAM": ["instagram", "insta"],
        "TELEGRAM": ["telegram", "تيليجرام"],
        "TWITTER": ["twitter", "x.com"],
        "TIKTOK": ["tiktok"],
        "SNAPCHAT": ["snapchat"],
        "GOOGLE": ["google", "gmail"],
        "UBER": ["uber"],
        "DISCORD": ["discord"],
        "LINKEDIN": ["linkedin"],
        "YOUTUBE": ["youtube"],
        "NETFLIX": ["netflix"],
        "AMAZON": ["amazon"],
        "PAYPAL": ["paypal"],
        "MICROSOFT": ["microsoft", "outlook", "hotmail"],
        "APPLE": ["apple", "icloud"],
        "BINANCE": ["binance"],
        "VIBER": ["viber"],
        "SIGNAL": ["signal"],
    }
    for service, keywords in services.items():
        for kw in keywords:
            if kw in ml:
                return service
    return "SMS"


def _clean_html(text) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", str(text)).strip()


def _clean_number(number) -> str:
    return re.sub(r"\D", "", str(number or ""))


def _row_to_tuple(row, sms_idx: int = IDX_SMS):
    date_str = number_str = sms_str = ""
    if isinstance(row, (list, tuple)):
        if len(row) > IDX_DATE:
            date_str = _clean_html(row[IDX_DATE])
        if len(row) > IDX_NUMBER:
            number_str = _clean_number(row[IDX_NUMBER])
        if len(row) > sms_idx:
            sms_str = _clean_html(row[sms_idx])
    elif isinstance(row, dict):
        for k in ("date", "time", "datetime", "dt", "created_at"):
            if k in row:
                date_str = _clean_html(row[k]); break
        for k in ("number", "msisdn", "cli", "from", "sender", "num"):
            if k in row:
                number_str = _clean_number(row[k]); break
        for k in ("sms", "message", "msg", "body", "text"):
            if k in row:
                sms_str = _clean_html(row[k]); break
    unique_key = f"{date_str}|{number_str}|{sms_str}"
    return date_str, number_str, sms_str, unique_key


def _build_ajax_url(base_url: str, scraper_type: str = "agent") -> str:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow  = today + timedelta(days=1)
    fdate1 = f"{yesterday.strftime('%Y-%m-%d')} 00:00:00"
    fdate2 = f"{tomorrow.strftime('%Y-%m-%d')} 23:59:59"
    ajax_path = AJAX_PATH_CLIENT if scraper_type == "client" else AJAX_PATH_AGENT
    params = (
        "fdate1=" + quote_plus(fdate1) +
        "&fdate2=" + quote_plus(fdate2) +
        "&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient="
        "&fgnumber=&fgcli=&fg=0&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
        "&iDisplayStart=0&iDisplayLength=100&mDataProp_0=0&mDataProp_1=1&mDataProp_2=2"
        "&mDataProp_3=3&mDataProp_4=4&mDataProp_5=5&mDataProp_6=6&mDataProp_7=7"
        "&mDataProp_8=8&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1&_=" +
        str(int(time.time() * 1000))
    )
    return base_url.rstrip("/") + ajax_path + "?" + params


def _extract_rows(j) -> list:
    if j is None:
        return []
    for key in ("data", "aaData", "rows", "aa_data"):
        if isinstance(j, dict) and key in j:
            return j[key]
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for v in j.values():
            if isinstance(v, list):
                return v
    return []


# ─── Per-scraper session login ─────────────────────────────────

def _get_session(name: str) -> requests.Session:
    if name not in _scraper_sessions:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "en-US,en;q=0.9",
        })
        _scraper_sessions[name] = s
    return _scraper_sessions[name]


def _login_scraper(name: str, base_url: str, username: str, password: str) -> bool:
    session = _get_session(name)
    login_page  = base_url.rstrip("/") + "/ints/login"
    login_post  = base_url.rstrip("/") + "/ints/signin"

    try:
        resp = session.get(login_page, timeout=TIMEOUT)
        match = re.search(r"What is (\d+) \+ (\d+)", resp.text)
        captcha = str(int(match.group(1)) + int(match.group(2))) if match else "0"

        payload = {
            "username": username,
            "password": password,
            "capt": captcha,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": login_page,
        }
        resp2 = session.post(login_post, data=payload, headers=headers,
                             timeout=TIMEOUT, allow_redirects=True)

        success = (
            "dashboard" in resp2.text.lower()
            or "logout" in resp2.text.lower()
            or "/ints/agent" in resp2.url
            or resp2.url != login_page
        )
        if success:
            logger.info(f"[Scraper:{name}] ✅ Login successful")
            _scraper_logged_in[name] = True
        else:
            logger.warning(f"[Scraper:{name}] ❌ Login failed")
            _scraper_logged_in[name] = False
        return success
    except Exception as e:
        logger.error(f"[Scraper:{name}] Login error: {e}")
        _scraper_logged_in[name] = False
        return False


def _fetch_ajax(name: str, base_url: str, username: str, password: str,
                scraper_type: str = "agent"):
    session = _get_session(name)
    url = _build_ajax_url(base_url, scraper_type)
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code == 403 or (r.url and "login" in r.url.lower()):
            raise Exception("Session expired")
        r.raise_for_status()
        if not r.text or not r.text.strip():
            return None
        return r.json()
    except Exception as e:
        if "Session expired" in str(e):
            logger.info(f"[Scraper:{name}] Session expired, re-logging in...")
            if _login_scraper(name, base_url, username, password):
                try:
                    url2 = _build_ajax_url(base_url, scraper_type)
                    r2 = session.get(url2, timeout=TIMEOUT)
                    r2.raise_for_status()
                    return r2.json()
                except Exception:
                    return None
        logger.error(f"[Scraper:{name}] AJAX fetch error: {e}")
        return None


def _fetch_evs_panel(name: str, base_url: str, username: str, password: str) -> list:
    """EVS Panel থেকে সব SMS records fetch করা"""
    session = _get_session(name)
    base    = base_url.rstrip("/")
    records = []

    today     = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow  = today + timedelta(days=1)
    fdate1 = f"{yesterday.strftime('%Y-%m-%d')} 00:00:00"
    fdate2 = f"{tomorrow.strftime('%Y-%m-%d')} 23:59:59"

    params = (
        f"fdate1={quote_plus(fdate1)}&fdate2={quote_plus(fdate2)}"
        "&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient="
        "&fgnumber=&fgcli=&fg=0&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
        "&iDisplayStart=0&iDisplayLength=200"
        "&mDataProp_0=0&mDataProp_1=1&mDataProp_2=2&mDataProp_3=3&mDataProp_4=4"
        "&mDataProp_5=5&mDataProp_6=6&mDataProp_7=7&mDataProp_8=8"
        f"&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1"
        f"&_={int(time.time() * 1000)}"
    )

    ajax_urls = [
        base + "/ints/agent/res/data_smscdr.php",
        base + "/ints/client/res/data_smscdr.php",
    ]

    for url in ajax_urls:
        try:
            r = session.get(url + "?" + params, timeout=TIMEOUT,
                            headers={"X-Requested-With": "XMLHttpRequest"})
            if "login" in r.url.lower():
                _scraper_sessions.pop(name, None)
                _scraper_logged_in[name] = False
                return []
            if not r.text or not r.text.strip():
                continue
            data = r.json()
            rows = data.get("aaData") or data.get("data") or []
            if rows:
                logger.info(f"[Scraper:{name}] EVS AJAX success via {url}, rows: {len(rows)}")
                for row in rows:
                    if isinstance(row, (list, tuple)) and len(row) >= 6:
                        records.append({
                            "dt":     str(row[0]).strip(),
                            "number": re.sub(r'[^\d]', '', str(row[2])),
                            "cli":    str(row[3]).strip() if len(row) > 3 else "",
                            "sms":    str(row[5]).strip() if len(row) > 5 else "",
                        })
                return records
        except Exception as e:
            logger.warning(f"[Scraper:{name}] EVS URL {url} error: {e}")
            continue

    return records


# ─── Main async scraping task ──────────────────────────────────

async def _find_assignment_with_grace(number: str):
    """
    সব format-এ active assignment খোঁজো; না পেলে grace period-এ খোঁজো —
    number change/country change করার সাথে সাথেই OTP এলে যাতে মিস না যায়।
    """
    assignment = await get_assignment_by_number(number)
    if not assignment:
        assignment = await get_assignment_by_number("+" + number.lstrip("+"))
    if assignment:
        return assignment

    # Race condition guard: number-টা এইমাত্র assign হয়ে থাকতে পারে,
    # DB commit সম্পূর্ণ হতে সামান্য সময় লাগে — একবার আবার চেষ্টা করো
    await asyncio.sleep(1.5)
    assignment = await get_assignment_by_number(number)
    if not assignment:
        assignment = await get_assignment_by_number("+" + number.lstrip("+"))
    if assignment:
        return assignment

    # Grace period — number change/country change করা user-এর কাছে পাঠাও
    # (rate-সহ, যাতে reward miss না হয়) — এটাই মূল fix, আগে এখানে কোনো fallback ছিল না
    try:
        grace_min = int(await get_setting("otp_grace_minutes") or "0")
        if grace_min > 0:
            cn = number.lstrip("+")
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


async def _process_scraper_otp(bot, scraper_name: str, otp_group_id: str,
                                date_str: str, number: str, sms: str):
    country_name, country_flag = _get_country(number)
    service = _detect_service(sms)
    otp     = _extract_otp(sms)
    masked  = _mask_number(number)
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    await save_otp_to_number(number, otp)

    assignment = await _find_assignment_with_grace(number)

    if assignment and assignment.get("country_name") and assignment["country_name"] != "Unknown":
        country_flag = assignment["country_flag"]
        country_name = assignment["country_name"]

    # প্রতিটা OTP এখানে লগ হয় — DM যদি কোনো কারণে miss হয়ে যায়, এই লগ থেকেই
    # পরে retry sweep বা ইউজারের "আমার সর্বশেষ OTP" বাটন দিয়ে উদ্ধার করা যাবে
    otp_log_id = await log_otp_event(
        number, otp, service, sms,
        user_id=assignment["user_id"] if assignment else None
    )

    try:
        support_username = await get_setting("support_username") or "@support"
        channel_link     = await get_setting("main_channel_link") or await get_setting("otp_group_link") or "https://t.me/otpgroup"
    except Exception:
        support_username = "@support"
        channel_link     = "https://t.me/otpgroup"

    support_clean = support_username.lstrip("@")

    try:
        bot_info = await bot.get_me()
        bot_link = f"https://t.me/{bot_info.username}"
    except Exception:
        bot_link = "https://t.me/bot"

    service_emoji = get_service_emoji(service)
    language = get_language_from_message(sms)

    group_msg = (
        f"{country_flag} #{country_name.replace(' ', '')}  {service_emoji} #{service}\n"
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

    async def _send_group():
        try:
            if otp_group_id:
                gid = int(otp_group_id) if str(otp_group_id).lstrip("-").isdigit() else otp_group_id
                await bot.send_message(chat_id=gid, text=group_msg,
                                       parse_mode="HTML", reply_markup=keyboard)
                logger.info(f"[Scraper:{scraper_name}] ✅ OTP sent: {otp} for {masked}")
        except Exception as e:
            logger.error(f"[Scraper:{scraper_name}] Failed to send to OTP group: {e}")

    send_tasks = [_send_group()]

    if assignment:
        user_id = assignment["user_id"]
        rate    = assignment["rate_per_otp"]
        service_emoji_dm = get_service_emoji(service)
        if rate > 0:
            hold = await get_panel_hold_setting(scraper_name)
            is_hold = bool(hold and hold["hold_enabled"])
            await reward_user_for_otp(user_id, rate, bot=bot, panel_name=scraper_name)
            bal = await get_user_balance(user_id)
            if is_hold:
                reward_line = f"🔒 <b>Hold:</b> ৳{rate} ({hold['hold_days']} দিন পর ব্যালেন্সে যোগ হবে)"
            else:
                reward_line = f"🎁 <b>Reward:</b> ৳{rate}"
        else:
            from database import increment_otp_count
            await increment_otp_count(user_id)
            reward_line = "🎁 <b>Reward:</b> N/A"
            bal = await get_user_balance(user_id)
        user_msg = (
            f"🎉 <b>NEW OTP ARRIVED!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📱 <b>Number:</b> {number}\n"
            f"{service_emoji_dm} <b>Service:</b> {service}\n"
            f"🔑 <b>OTP Code:</b> {otp}\n"
            f"{reward_line}\n"
            f"👛 <b>Balance:</b> ৳{bal:.2f}"
        )
        try:
            dm_otp_btn = InlineKeyboardButton(
                f"✅ {otp}",
                copy_text=CopyTextButton(otp),
                style="success"
            )
        except Exception:
            dm_otp_btn = InlineKeyboardButton(
                f"✅ {otp}",
                callback_data=f"copy_text_{otp}",
                style="success"
            )
        dm_keyboard = InlineKeyboardMarkup([[dm_otp_btn]])

        async def _send_dm():
            last_err = None
            for attempt in range(3):
                try:
                    await bot.send_message(chat_id=user_id, text=user_msg, parse_mode="HTML", reply_markup=dm_keyboard)
                    await mark_otp_delivered(otp_log_id)
                    return
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str or "chat not found" in err_str:
                        # ইউজার বট ব্লক করেছে বা account deactivated — আর retry করে লাভ নেই
                        await mark_otp_permanently_failed(otp_log_id)
                        break
                    await increment_otp_attempt(otp_log_id)
                    await asyncio.sleep(1.5)
            logger.error(f"[Scraper:{scraper_name}] ❌ Failed to forward OTP to user {user_id} after retries: {last_err} (redelivery sweep will keep retrying if not permanently failed)")

        send_tasks.append(_send_dm())
    else:
        # কোনো assignment (active/grace) পাওয়া যায়নি — otp_log-এ user_id ছাড়াই থেকে যাবে,
        # redelivery sweep প্রতি ২০ সেকেন্ডে আবার assignment খুঁজে দেখবে, তাই admin অ্যালার্টের দরকার নেই
        logger.info(f"[Scraper:{scraper_name}] ⏳ No assignment found yet for {masked} — queued for redelivery sweep")

    await asyncio.gather(*send_tasks)


async def _poll_one_scraper(bot, scraper: dict, otp_group_id: str):
    name         = scraper["name"]
    base_url     = scraper["base_url"]
    username     = scraper["username"]
    password     = scraper["password"]
    scraper_type = scraper.get("scraper_type", "agent")

    if name not in _sent_keys:
        _sent_keys[name] = set()

    # ── EVS Panel ────────────────────────────────────────────────
    if scraper_type == "evs":
        if not _scraper_logged_in.get(name):
            await asyncio.to_thread(_login_scraper, name, base_url, username, password)
            if not _scraper_logged_in.get(name):
                return

        records = await asyncio.to_thread(_fetch_evs_panel, name, base_url, username, password)
        new_otp_tasks = []
        for rec in records:
            number = rec.get("number", "")
            sms    = rec.get("sms", "")
            dt     = rec.get("dt", "")
            if not number or not sms:
                continue
            # OTP extract করে key বানাও — same number-এ আলাদা OTP আলাদা key হবে
            otp_match = re.search(r'\b(\d{4,8})\b', sms)
            otp_part  = otp_match.group(1) if otp_match else sms[-10:]
            key = f"{number}|{otp_part}|{dt}"
            if key in _sent_keys[name]:
                continue
            _sent_keys[name].add(key)
            new_otp_tasks.append(_process_scraper_otp(bot, name, otp_group_id, dt, number, sms))

        if new_otp_tasks:
            # সব নতুন OTP একসাথে (parallel) পাঠানো হচ্ছে, একটার জন্য আরেকটা wait করবে না
            await asyncio.gather(*new_otp_tasks, return_exceptions=True)

        if len(_sent_keys[name]) > 2000:
            _sent_keys[name] = set(list(_sent_keys[name])[-1000:])
        return

    # ── Standard panel ───────────────────────────────────────────
    if not _scraper_logged_in.get(name):
        await asyncio.to_thread(_login_scraper, name, base_url, username, password)
        if not _scraper_logged_in.get(name):
            return

    j = await asyncio.to_thread(_fetch_ajax, name, base_url, username, password, scraper_type)
    rows = _extract_rows(j)

    idx_sms = 4 if scraper_type == "client" else IDX_SMS
    valid = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) > idx_sms:
            d = _clean_html(row[IDX_DATE])
            n = _clean_number(row[IDX_NUMBER])
            s = _clean_html(row[idx_sms]) if row[idx_sms] else ""
            if d and n and s:
                valid.append(row)

    def _get_dt(r):
        try:
            return datetime.strptime(_clean_html(r[IDX_DATE]), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    valid.sort(key=_get_dt)

    new_otp_tasks = []
    for row in valid:
        d_str, num, sms, key = _row_to_tuple(row, idx_sms)
        if key in _sent_keys[name]:
            continue
        _sent_keys[name].add(key)
        new_otp_tasks.append(_process_scraper_otp(bot, name, otp_group_id, d_str, num, sms))

    if new_otp_tasks:
        # সব নতুন OTP একসাথে (parallel) পাঠানো হচ্ছে, একটার জন্য আরেকটা wait করবে না
        await asyncio.gather(*new_otp_tasks, return_exceptions=True)

    if len(_sent_keys[name]) > 1000:
        _sent_keys[name] = set(list(_sent_keys[name])[-1000:])


async def _redelivery_sweep(bot):
    """
    যেসব OTP delivered=0 অবস্থায় পড়ে আছে (DM fail হয়েছিল, বা তখন assignment
    পাওয়া যায়নি) — প্রতি ২০ সেকেন্ডে সেগুলো আবার পাঠানোর চেষ্টা করে।
    এই sweep শুধু scraping system না, api_handler.py-এর মাধ্যমে আসা OTP-ও কভার করে,
    কারণ সবাই একই otp_log টেবিল ব্যবহার করে। Window ২৪ ঘণ্টা / ৩০০ attempts —
    তাই সাময়িক নেটওয়ার্ক/টেলিগ্রাম সমস্যায় কোনো OTP কখনো হারিয়ে যায় না।
    এটাই শেষ safety net, যাতে সত্যিকার অর্থে কোনো OTP miss না হয়।
    """
    while True:
        try:
            pending = await get_undelivered_otps(max_age_minutes=1440, max_attempts=300)
            for row in pending:
                log_id = row["id"]
                number = row["number"]
                user_id = row["user_id"]

                if not user_id:
                    assignment = await get_assignment_by_number(number)
                    if not assignment:
                        assignment = await get_assignment_by_number("+" + number.lstrip("+"))
                    if not assignment:
                        try:
                            grace_min = int(await get_setting("otp_grace_minutes") or "0")
                            if grace_min > 0:
                                grace_user = await get_grace_period_user(number.lstrip("+"), grace_min)
                                if grace_user:
                                    assignment = {"user_id": grace_user["user_id"]}
                        except Exception:
                            pass
                    if not assignment:
                        continue  # এখনো assignment নেই, পরের sweep-এ আবার চেষ্টা হবে
                    user_id = assignment["user_id"]
                    await set_otp_log_user(log_id, user_id)

                try:
                    text = (
                        f"🔁 <b>OTP (পুনরায় পাঠানো হচ্ছে)</b>\n"
                        f"📱 <b>Number:</b> {number}\n"
                        f"🔑 <b>OTP Code:</b> {row['otp']}\n"
                        f"<i>আগেরবার ডেলিভারি সমস্যা হয়েছিল, দুঃখিত।</i>"
                    )
                    await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
                    await mark_otp_delivered(log_id)
                    logger.info(f"[RedeliverySweep] ✅ Resent OTP log #{log_id} to {user_id}")
                except Exception as e:
                    err_str = str(e).lower()
                    if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str or "chat not found" in err_str:
                        # ইউজার বট ব্লক করেছে/ডিএক্টিভেটেড — retry করে লাভ নেই, বন্ধ করে দাও
                        await mark_otp_permanently_failed(log_id)
                        logger.warning(f"[RedeliverySweep] log #{log_id}: user {user_id} unreachable, permanently marked: {e}")
                    else:
                        await increment_otp_attempt(log_id)
                        logger.warning(f"[RedeliverySweep] retry failed for log #{log_id}: {e}")
        except Exception as e:
            logger.error(f"[RedeliverySweep] loop error: {e}")
        await asyncio.sleep(20)


# ─── Public entry-point ────────────────────────────────────────

async def _scraper_worker(bot, scraper: dict, otp_group_id: str, interval: int):
    """
    একটা নির্দিষ্ট প্যানেলের জন্য independent, নিজস্ব লুপ।
    এই worker অন্য কোনো প্যানেলের জন্য wait করে না — তাই একটা প্যানেল slow/down
    থাকলেও বাকি সব প্যানেলের OTP ঠিক সময়ে (২ সেকেন্ডের ভিতর) চলে যাবে।
    """
    name = scraper["name"]
    logger.info(f"[Scraper:{name}] 🚀 worker started (every {interval}s)")
    while True:
        try:
            await _poll_one_scraper(bot, scraper, otp_group_id)
        except Exception as e:
            logger.error(f"[Scraper:{name}] Poll error: {e}")
        await asyncio.sleep(interval)


async def start_scraper_polling(bot, otp_group_id: str, interval: int = REFRESH_INTERVAL):
    """
    প্রতিটা active scraper/panel-এর জন্য আলাদা background task চালু করে।
    সব panel সমান্তরালে (parallel) poll হয় — একটা প্যানেল আটকে গেলেও
    বাকি সবগুলোর OTP ডেলিভারি স্বাভাবিক গতিতেই চলবে।
    নতুন কোনো scraper অ্যাডমিন প্যানেল থেকে যোগ করা হলে সেটাও প্রতি ৩০ সেকেন্ডে
    auto-detect করে নতুন worker চালু করে দেয়।
    """
    logger.info(f"🕷 Scraper polling manager started (per-panel interval: {interval}s)")
    running_workers: dict = {}   # name → asyncio.Task
    asyncio.create_task(_redelivery_sweep(bot))

    while True:
        try:
            scrapers = await get_all_scrapers()
            active_names = set()
            for scraper in scrapers:
                if not scraper.get("is_active", 1):
                    continue
                name = scraper["name"]
                active_names.add(name)
                task = running_workers.get(name)
                if task is None or task.done():
                    running_workers[name] = asyncio.create_task(
                        _scraper_worker(bot, scraper, otp_group_id, interval)
                    )

            # যেসব scraper deactivate/delete করা হয়েছে, তাদের worker বন্ধ করে দাও
            for name in list(running_workers.keys()):
                if name not in active_names:
                    running_workers[name].cancel()
                    del running_workers[name]

        except Exception as e:
            logger.error(f"Scraper polling manager error: {e}")

        # প্রতি ৩০ সেকেন্ডে নতুন/মুছে ফেলা scraper আছে কিনা চেক করে —
        # ততক্ষণে প্রতিটা worker নিজের গতিতেই OTP পুল করতে থাকে
        await asyncio.sleep(30)
