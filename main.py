"""
Sistem Partisipasi Automation — Zendriver Edition
Undetectable browser automation via Chrome DevTools Protocol.
"""
import os
import sys
import signal
import atexit
import asyncio
import json
import requests
import time
import subprocess
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

import zendriver as zd
from dotenv import load_dotenv

# ============================================================
#  CONFIG
# ============================================================

basedir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(basedir, '.env'))

PID_FILE = os.path.join(basedir, "bot.pid")

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
CHROME_PROFILE_PATH = os.getenv('CHROME_PROFILE_PATH')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HEADLESS_MODE = os.getenv('HEADLESS_MODE', 'False').lower() == 'true'

browser: zd.Browser | None = None
screenshot_dir: str | None = None


# ============================================================
#  PROCESS MANAGEMENT
# ============================================================

def _kill_automation_profile_brave():
    """Bunuh proses Brave yg pake automation profile SAJA."""
    if not CHROME_PROFILE_PATH:
        return
    try:
        ps_cmd = ('Get-CimInstance Win32_Process -Filter "Name = \'brave.exe\'" '
                  '| Select-Object ProcessId, CommandLine | ConvertTo-Json')
        result = subprocess.run(["powershell", "-Command", ps_cmd],
                                capture_output=True, text=True)
        if result.stdout.strip():
            data = json.loads(result.stdout)
            processes = data if isinstance(data, list) else [data]
            killed = 0
            for proc in processes:
                cmd_line = proc.get('CommandLine', '') or ''
                pid = proc.get('ProcessId')
                if cmd_line and CHROME_PROFILE_PATH.lower() in cmd_line.lower():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True)
                    killed += 1
            if killed:
                print(f"  - {killed} zombie Brave (automation) dibersihkan")
    except Exception:
        pass


def _clean_lock_files():
    """Hapus lock files di automation profile."""
    if not CHROME_PROFILE_PATH:
        return
    for lock in ["SingletonLock", "SingletonSocket", "DevToolsActivePort",
                 "Lockfile", "lockfile"]:
        lp = os.path.join(CHROME_PROFILE_PATH, lock)
        if os.path.exists(lp):
            try:
                os.remove(lp)
            except Exception:
                pass


def cleanup_other_main_instances():
    """Hentikan instance bot lain berdasarkan PID file."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            if old_pid == os.getpid():
                return
            print(f"\n[Cleanup] Menutup instance bot lama (PID {old_pid})...")
            subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                           capture_output=True)
            time.sleep(1)
        except (ValueError, ProcessLookupError, Exception):
            pass


def save_current_pid():
    """Catat PID proses saat ini."""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"Gagal mencatat PID: {e}")


def graceful_shutdown():
    """Cleanup saat terminate/exit."""
    print("\n[Shutdown] Cleaning up...")
    _clean_lock_files()


def signal_handler(sig, frame):
    print(f"\n[Shutdown] Signal {sig} diterima...")
    graceful_shutdown()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
try:
    signal.signal(signal.SIGTERM, signal_handler)
except AttributeError:
    pass
atexit.register(graceful_shutdown)


# ============================================================
#  BROWSER INIT (ZENDRIVER)
# ============================================================

async def init_browser() -> tuple[zd.Browser, zd.Tab]:
    """Launch Brave via zendriver CDP. Return (browser, tab)."""
    global browser, screenshot_dir

    print("\n[Init] Menyiapkan browser (zendriver CDP)...")

    # Bersihin zombie + lock dari run sebelumnya
    _kill_automation_profile_brave()
    _clean_lock_files()
    await asyncio.sleep(1)

    # Cek Brave binary
    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    if not os.path.exists(brave_path):
        raise Exception(f"Brave tidak ditemukan: {brave_path}")

    browser_args = [
        "--mute-audio",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-translate",
        "--disable-popup-blocking",
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--disable-features=TranslateUI",
        f"--window-size=1280,800",
    ]

    if HEADLESS_MODE:
        browser_args.append("--headless=new")

    print(f"  - Brave binary: {brave_path}")
    print(f"  - Profile: {CHROME_PROFILE_PATH}")

    browser = await zd.start(
        browser_executable_path=brave_path,
        user_data_dir=CHROME_PROFILE_PATH,
        headless=HEADLESS_MODE,
        browser_args=browser_args,
        disable_webrtc=True,
        disable_webgl=True,
    )

    tab = browser.main_tab
    await tab.set_window_size(1280, 800)

    today = datetime.now().strftime("%Y-%m-%d")
    screenshot_dir = os.path.join(basedir, today)
    os.makedirs(screenshot_dir, exist_ok=True)

    print("  - Browser siap (zendriver CDP — undetectable)!")
    return browser, tab


# ============================================================
#  PURE HELPERS (no browser)
# ============================================================

def get_platform(url: str) -> str | None:
    domain = urlparse(url).netloc.lower()
    if 'tiktok.com' in domain:
        return 'tiktok'
    elif 'instagram.com' in domain:
        return 'instagram'
    elif 'youtube.com' in domain or 'youtu.be' in domain:
        return 'youtube'
    return None


# ============================================================
#  TIKTOK — BLOCK DETECTION + TASK
# ============================================================

async def _detect_tiktok_block(tab: zd.Tab) -> str | None:
    """Return 'captcha' | 'login_required' | 'blocked' | None."""
    try:
        body_text = (await tab.evaluate("document.body.innerText")).lower()
    except Exception:
        body_text = ""

    # --- CAPTCHA ---
    captcha_selectors = [
        "#captcha-verify-container-main-page",
        "[id*='captcha']",
        "[class*='captcha-verify']",
        "[data-testid*='captcha']",
        "#verify-ele",
        "div[class*='verify']",
    ]
    for sel in captcha_selectors:
        try:
            el = await tab.select(sel, timeout=1)
            if el:
                return "captcha"
        except Exception:
            pass

    # --- LOGIN REDIRECT ---
    url_lower = tab.url.lower() if tab.url else ""
    if '/login' in url_lower or '/signup' in url_lower:
        return "login_required"

    login_selectors = [
        'input[name="username"]',
        'input[placeholder*="phone"]',
        'input[placeholder*="email"]',
        'input[placeholder*="user"]',
    ]
    for sel in login_selectors:
        try:
            el = await tab.select(sel, timeout=1)
            if el:
                return "login_required"
        except Exception:
            pass

    # --- ACCESS DENIED ---
    denied_phrases = [
        "access denied", "too many requests", "something went wrong",
        "you are visiting our service too frequently", "try again later",
        "you've been temporarily blocked", "verify you are human",
        "verify to continue", "are you a human",
    ]
    for phrase in denied_phrases:
        if phrase in body_text:
            return "blocked"

    try:
        title = (await tab.evaluate("document.title")).lower()
        blocked_titles = ["access denied", "too many requests", "verify",
                          "blocked", "sorry"]
        for t in blocked_titles:
            if t in title:
                return "blocked"
    except Exception:
        pass

    # --- BLANK PAGE ---
    if len(body_text.strip()) < 20:
        try:
            source = (await tab.evaluate("document.documentElement.outerHTML")).lower()
            if len(source) < 500:
                return "blocked"
            if any(k in source for k in ["captcha", "verify", "block"]):
                return "blocked"
        except Exception:
            pass

    return None


async def _wait_for_captcha_solve(tab: zd.Tab, timeout: int = 300) -> bool:
    """Polling sampai captcha hilang. Return True kalo solved."""
    print("    ⏳ Menunggu Anda solve captcha manual...")
    start = time.time()
    last_log = start
    while time.time() - start < timeout:
        await asyncio.sleep(1)
        status = await _detect_tiktok_block(tab)
        if status != "captcha":
            if status is None:
                print("    ✅ Captcha solved!")
                return True
            elif status == "blocked":
                print("    ❌ Captcha solved tapi muncul Access Denied")
                return False
        elapsed = int(time.time() - start)
        if time.time() - last_log > 30:
            remaining = timeout - elapsed
            print(f"    ⏳ Masih menunggu... ({elapsed}s, sisa {remaining}s)")
            last_log = time.time()
    print(f"    ❌ Timeout captcha ({timeout}s)")
    return False


async def _wait_for_tiktok_content(tab: zd.Tab, timeout: int = 15) -> bool:
    """Konfirmasi halaman video TikTok sudah render."""
    content_selectors = [
        '[data-e2e="follow-button"]', '[data-e2e="unfollow-button"]',
        '[data-e2e="like-icon"]', '[data-e2e="unlike-icon"]',
        '[data-e2e="video-title"]', 'video',
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await _detect_tiktok_block(tab) is not None:
            return False
        for sel in content_selectors:
            try:
                el = await tab.select(sel, timeout=0.5)
                if el:
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.5)

    # Fallback: body text > 100 chars
    try:
        text = await tab.evaluate("document.body.innerText")
        if len(text.strip()) > 100:
            return True
    except Exception:
        pass

    return False


_tiktok_prewarmed = False  # global flag — cuma warm sekali per session


async def do_tiktok_task(tab: zd.Tab, url: str):
    """Follow + Like TikTok via zendriver CDP. Raise Exception kalo gagal total."""
    global _tiktok_prewarmed

    # Pre-warm: kunjungi TikTok homepage dulu buat load session cookies
    if not _tiktok_prewarmed:
        print("  [TikTok] Pre-warming session...")
        await tab.get("https://www.tiktok.com/")
        await asyncio.sleep(4)
        # Cek apakah kena captcha/block saat pre-warm
        warm_block = await _detect_tiktok_block(tab)
        if warm_block:
            print(f"  ⚠️ TikTok pre-warm kena {warm_block}!")
            print("  ⚠️ Session belum verified. Buka Brave manual dulu, solve captcha, tutup, lalu /run lagi.")
        else:
            print("  [TikTok] Pre-warm OK — session verified")
        _tiktok_prewarmed = True

    print(f"  [TikTok] Memproses: {url}")

    for attempt in range(3):
        print(f"  [TikTok] Attempt {attempt + 1}/3...")
        await tab.get(url)
        await asyncio.sleep(4)

        # DETEKSI BLOK
        block = await _detect_tiktok_block(tab)
        if block == "captcha":
            print("  ⚠️ CAPTCHA terdeteksi!")
            if not await _wait_for_captcha_solve(tab):
                if attempt < 2:
                    print("  ⏳ Retry setelah captcha timeout...")
                    continue
                raise Exception("TikTok CAPTCHA timeout")
            await tab.get(url)
            await asyncio.sleep(3)

        elif block == "login_required":
            raise Exception(
                "TikTok redirect login — session expired. "
                "Buka Brave dengan automation profile, login manual, lalu coba lagi."
            )

        elif block == "blocked":
            if attempt < 2:
                backoff = (attempt + 1) * 15
                print(f"  ❌ Access Denied / Rate Limited — tunggu {backoff}s...")
                await asyncio.sleep(backoff)
                continue
            raise Exception("TikTok blokir akses setelah 3x retry. Tunggu 30-60 menit.")

        # VERIFIKASI KONTEN
        if not await _wait_for_tiktok_content(tab):
            if attempt < 2:
                print("  ⚠️ Konten TikTok ga muncul")
                await asyncio.sleep(10)
                continue
            raise Exception("Konten TikTok ga muncul setelah 3x retry")

        # === FOLLOW ===
        follow_done = False
        follow_btn = None

        try:
            el = await tab.select('[data-e2e="unfollow-button"]', timeout=1)
            if el:
                print("  - Follow: sudah di-follow")
                follow_done = True
        except Exception:
            pass

        if not follow_done:
            for sel in ['[data-e2e="follow-button"]',
                        'button:has-text("Follow")']:
                try:
                    el = await tab.select(sel, timeout=2)
                    if el:
                        txt = (el.text or "").lower()
                        if 'following' not in txt:
                            follow_btn = el
                            break
                except Exception:
                    pass

            # Fallback: find by text
            if not follow_btn:
                try:
                    el = await tab.find("Follow", timeout=2)
                    if el and 'following' not in (el.text or "").lower():
                        follow_btn = el
                except Exception:
                    pass

            if follow_btn:
                await follow_btn.scroll_into_view()
                await asyncio.sleep(0.5)
                await follow_btn.click()
                await asyncio.sleep(1.5)
                print("  - Follow: ✅ berhasil")
            else:
                print("  - Follow: tombol tidak ditemukan")

        # === LIKE ===
        like_done = False
        like_btn = None

        try:
            el = await tab.select('[data-e2e="unlike-icon"]', timeout=1)
            if el:
                print("  - Like: sudah di-like")
                like_done = True
        except Exception:
            pass

        if not like_done:
            for sel in ['[data-e2e="like-icon"]',
                        'button[aria-label*="Like"]',
                        '[class*="like-button"]']:
                try:
                    el = await tab.select(sel, timeout=2)
                    if el:
                        aria = (el.attrs.get('aria-label') or '').lower()
                        if 'unlike' not in aria:
                            like_btn = el
                            break
                except Exception:
                    pass

            if like_btn:
                await like_btn.scroll_into_view()
                await asyncio.sleep(0.5)
                await like_btn.click()
                await asyncio.sleep(1)
                print("  - Like: ✅ berhasil")
            else:
                print("  - Like: tombol tidak ditemukan")

        # === DOUBLE-CHECK SILENT BLOCK ===
        follow_found = follow_done or (follow_btn is not None)
        like_found = like_done or (like_btn is not None)

        if not follow_found and not like_found:
            if attempt < 2:
                print("  ⚠️ Semua tombol ga ditemukan — kemungkinan halaman blokir")
                await asyncio.sleep(10)
                continue
            raise Exception("TikTok: tombol tidak ditemukan setelah 3x retry.")

        await asyncio.sleep(2)
        return  # sukses

    raise Exception("TikTok gagal setelah 3x retry")


# ============================================================
#  INSTAGRAM
# ============================================================

def _convert_instagram_reel(url: str) -> str:
    lower = url.lower()
    if '/reels/' in lower or '/reel/' in lower:
        parts = url.split('/')
        for i, part in enumerate(parts):
            if part.lower() in ('reels', 'reel') and i + 1 < len(parts):
                post_id = parts[i + 1].split('?')[0].split('#')[0]
                return f"https://www.instagram.com/p/{post_id}/"
    return url


async def do_instagram_task(tab: zd.Tab, url: str):
    """Follow + Like Instagram via zendriver."""
    target = _convert_instagram_reel(url)
    if target != url:
        print(f"  [IG] Normalized: {target}")

    for attempt in range(2):
        try:
            await tab.get(target)
            await asyncio.sleep(5)

            # --- FOLLOW ---
            try:
                btn = await tab.find("Follow", timeout=3)
                txt = (btn.text or "").strip().lower()
                if txt == 'follow':
                    await btn.scroll_into_view()
                    await asyncio.sleep(0.5)
                    await btn.click()
                    await asyncio.sleep(2)
                    print("  - Follow: ✅ berhasil")
                else:
                    print("  - Follow: sudah di-follow")
            except Exception:
                print("  - Follow: tombol tidak ditemukan")

            # --- LIKE ---
            try:
                svg_els = await tab.select_all('svg[aria-label="Like"]', timeout=2)
                svg_els.extend(await tab.select_all('svg[aria-label="Suka"]', timeout=1))
            except Exception:
                svg_els = []

            if svg_els:
                svg = svg_els[-1]
                # Naik ke parent div[role='button']
                try:
                    parent_div = await svg.query_selector("xpath=ancestor::div[@role='button']")
                    if not parent_div:
                        parent_div = svg
                    await parent_div.click()
                    await asyncio.sleep(1)
                    print("  - Like: ✅ berhasil")
                except Exception:
                    print("  - Like: gagal klik")
            else:
                try:
                    unlike = await tab.select('svg[aria-label="Unlike"]', timeout=1)
                    if unlike:
                        print("  - Like: sudah di-like")
                    else:
                        print("  - Like: tombol tidak ditemukan")
                except Exception:
                    print("  - Like: tombol tidak ditemukan")

            await asyncio.sleep(2)
            return
        except Exception as e:
            if attempt == 1:
                raise
            print(f"  [IG] Retry setelah error: {e}")
            await asyncio.sleep(2)


# ============================================================
#  YOUTUBE
# ============================================================

async def do_youtube_task(tab: zd.Tab, url: str):
    """Subscribe + Like + Watch YouTube via zendriver."""
    print(f"  [YT] Memproses: {url}")
    await tab.get(url)
    await asyncio.sleep(5)

    # --- SKIP ADS ---
    try:
        for _ in range(10):  # max 10 detik cek ad
            is_ad = await tab.evaluate(
                "document.querySelector('.ad-showing') || "
                "document.querySelector('.ytp-ad-player-overlay') ? true : false"
            )
            if not is_ad:
                break
            for sel in [".ytp-skip-ad-button", ".ytp-ad-skip-button-modern",
                        "button[class*='ytp-ad-skip']"]:
                try:
                    btn = await tab.select(sel, timeout=1)
                    if btn:
                        await btn.click()
                        print("  - Ad skipped")
                        await asyncio.sleep(1)
                        break
                except Exception:
                    pass
            await asyncio.sleep(1)
    except Exception:
        pass

    # --- SEEK TO END ---
    try:
        result = await tab.evaluate("""
            (() => {
                const v = document.querySelector('video');
                if (v && v.duration > 0) { v.currentTime = v.duration - 0.5; return 'ok'; }
                return 'fail';
            })()
        """)
        if result == 'ok':
            print("  - Seek to end: ✅")
    except Exception:
        pass
    await asyncio.sleep(2)

    # --- SUBSCRIBE ---
    try:
        btn = await tab.select('ytd-subscribe-button-renderer button', timeout=3)
        txt = (btn.text or "").lower()
        if 'subscribe' in txt and 'subscribed' not in txt:
            await btn.click()
            await asyncio.sleep(2)
            print("  - Subscribe: ✅ berhasil")
        else:
            print("  - Subscribe: sudah subscribed")
    except Exception:
        print("  - Subscribe: tombol tidak ditemukan")

    # --- LIKE ---
    try:
        for sel in ['like-button-view-model button',
                    '#segmented-like-button button',
                    'ytd-segmented-like-dislike-button-renderer button']:
            try:
                btn = await tab.select(sel, timeout=2)
                pressed = btn.attrs.get('aria-pressed', '')
                if pressed == 'false':
                    await btn.click()
                    await asyncio.sleep(1)
                    print("  - Like: ✅ berhasil")
                else:
                    print("  - Like: sudah di-like")
                break
            except Exception:
                continue
        else:
            print("  - Like: tombol tidak ditemukan")
    except Exception as e:
        print(f"  - Like error: {e}")

    await asyncio.sleep(2)


# ============================================================
#  SCREENSHOT + UPLOAD
# ============================================================

async def take_screenshot(tab: zd.Tab, task_number: int) -> str:
    filename = f"task_{task_number}.png"
    filepath = os.path.join(screenshot_dir, filename)
    await tab.save_screenshot(filepath)
    print(f"  - Screenshot: {filepath}")
    return filepath


async def upload_proof_and_submit(tab: zd.Tab, task_link: str,
                                   screenshot_path: str):
    """Upload screenshot ke task detail dan submit."""
    await tab.get(task_link)
    await asyncio.sleep(2)

    # Tunggu .prose
    try:
        await tab.select('.prose', timeout=10)
    except Exception:
        pass
    await asyncio.sleep(1)

    # Upload file
    try:
        file_input = await tab.select('input[type="file"][accept="image/*"]', timeout=5)
        await file_input.send_keys(screenshot_path)
        await asyncio.sleep(2)
        print(f"  - Uploaded: {screenshot_path}")
    except Exception as e:
        print(f"  - Upload error: {e}")
        return

    # Scroll ke bawah
    await tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    # Click submit
    try:
        btn = await tab.find("Submit", timeout=10)
        # Pastikan bukan di dalam dialog expired
        await btn.click()
        await asyncio.sleep(2)
        print("  - Clicked submit")

        # Cek dialog expired
        try:
            dialog = await tab.select('#upload_reason_modal', timeout=3)
            if dialog:
                print("  - Task expired dialog")
                textarea = await dialog.select('textarea', timeout=2)
                if textarea:
                    await textarea.send_keys("-")
                    await asyncio.sleep(1)
                submit_btn = await dialog.find("Submit", timeout=2)
                if submit_btn:
                    await submit_btn.click()
                    print("  - Submitted expired reason")
                    await asyncio.sleep(2)
        except Exception:
            print("  - No expired dialog (on time)")

        print("  - Submitted successfully!")
    except Exception as e:
        print(f"  - Submit error: {e}")


# ============================================================
#  TELEGRAM (sync — pakai requests)
# ============================================================

def send_telegram_album(task_data: dict):
    """Kirim screenshot ke Telegram sebagai album."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    print("\n[Telegram] Mengirim album screenshot...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    media = []
    files = {}

    for i, data in task_data.items():
        file_path = data['screenshot']
        file_name = os.path.basename(file_path)
        media.append({"type": "photo", "media": f"attach://{file_name}"})
        files[file_name] = open(file_path, 'rb')

    try:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "media": json.dumps(media)}
        res = requests.post(url, data=payload, files=files, timeout=60)
        res_json = res.json()
        if res_json.get("ok"):
            print("  - Foto terkirim.")
        else:
            print(f"  - Gagal: {res_json}")
    except requests.exceptions.Timeout:
        print("  - Request Timeout kirim foto")
    except Exception as e:
        print(f"  - Error Telegram: {e}")
    finally:
        for f in files.values():
            f.close()


def wait_for_telegram_confirmation(max_wait: int = 300) -> bool:
    """Kirim tombol konfirmasi, tunggu response. Return True kalo dikonfirmasi."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return True  # tanpa telegram, auto confirm

    url_send = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Confirm Semua", "callback_data": "confirm"},
            {"text": "❌ Batal", "callback_data": "cancel"}
        ]]
    }

    message_id = None
    try:
        req = requests.post(url_send, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"Semua eksekusi sosial media selesai ✅\nLanjut Upload & Submit? ({max_wait/60:.1f} mnt)",
            "reply_markup": keyboard
        }, timeout=20)
        message_id = req.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"  - Error kirim tombol: {e}")
        return False

    print(f"\n[Telegram] Menunggu konfirmasi... (Timeout: {max_wait}s)")
    offset = None
    url_updates = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    start_time = time.time()
    last_print = start_time

    while time.time() - start_time < max_wait:
        elapsed = time.time() - start_time
        if elapsed - last_print > 60:
            print(f"  - Menunggu... (sisa {int(max_wait - elapsed)}s)")
            last_print = elapsed

        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            res = requests.get(url_updates, params=params, timeout=35)
            data = res.json()

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data")
                        cb_id = cb.get("id")

                        # Answer callback
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                                json={"callback_query_id": cb_id}, timeout=10)
                        except Exception:
                            pass

                        # Update message
                        if message_id:
                            status = "✅ DIKONFIRMASI" if cb_data == "confirm" else "❌ DIBATALKAN"
                            try:
                                requests.post(
                                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                                    json={"chat_id": TELEGRAM_CHAT_ID,
                                          "message_id": message_id,
                                          "text": f"Semua selesai ✅\nStatus: {status}"},
                                    timeout=10)
                            except Exception:
                                pass

                        if cb_data == "confirm":
                            print("\n  - Respons: ✅ CONFIRM")
                            return True
                        elif cb_data == "cancel":
                            print("\n  - Respons: ❌ CANCEL")
                            return False
        except requests.exceptions.Timeout:
            pass
        except requests.exceptions.RequestException:
            await_sleep_sync(5)
        except Exception as e:
            print(f"  - Error polling: {e}")
            await_sleep_sync(5)

        time.sleep(2)

    # Timeout
    print(f"\n[Telegram] Timeout ({max_wait}s) — batal otomatis")
    if message_id:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                          json={"chat_id": TELEGRAM_CHAT_ID,
                                "message_id": message_id,
                                "text": "⏳ WAKTU HABIS — ❌ DIBATALKAN OTOMATIS"},
                          timeout=10)
        except Exception:
            pass
    return False


def await_sleep_sync(seconds: float):
    """time.sleep wrapper — buat dipake di sync context."""
    time.sleep(seconds)


# ============================================================
#  MAIN AUTOMATION (ASYNC)
# ============================================================

async def run_automation(chat_id: str):
    """Main flow: login → tasks → screenshot → upload."""
    global browser

    try:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": "⏳ Memulai browser dan mengambil task..."})

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === Otomatisasi (zendriver) ===")

        # Init browser
        browser, tab = await init_browser()
        print(f"  - Browser ready: {await tab.evaluate('navigator.userAgent')}")

        # ============ LOGIN ============
        print("  - Membuka dashboard...")
        await tab.get("https://admin.sistem-partisipasi.jovasoftware.id/dashboard")
        await asyncio.sleep(3)

        # Cek login
        try:
            email_input = await tab.select('input[type="email"]', timeout=5)
            if email_input:
                print("  - Belum login, mencoba login...")
                await email_input.send_keys(EMAIL)
                await asyncio.sleep(0.5)

                pass_input = await tab.select('input[type="password"]', timeout=3)
                await pass_input.send_keys(PASSWORD)
                await asyncio.sleep(0.5)

                submit = await tab.select('button[type="submit"]', timeout=3)
                await submit.click()
                await asyncio.sleep(5)
                print("  - Login berhasil!")
            else:
                print("  - Sudah dalam keadaan login.")
        except Exception:
            print("  - Sudah login (email field tidak ditemukan).")

        # Tunggu table
        try:
            await tab.select('.rdt_Table', timeout=15)
        except Exception:
            raise Exception("Dashboard table tidak muncul — login gagal?")

        # Ambil task links
        rows = await tab.select_all('.rdt_TableRow')
        task_links = []
        BASE = "https://admin.sistem-partisipasi.jovasoftware.id"
        for row in rows:
            try:
                link_el = await row.query_selector('[data-column-id="8"] a')
                if link_el:
                    href = link_el.attrs.get('href', '')
                    if href:
                        # Resolve relative URL → absolute
                        if href.startswith('/'):
                            href = BASE + href
                        task_links.append(href)
            except Exception:
                pass

        print(f"\nFound {len(task_links)} tasks\n")

        if not task_links:
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": chat_id, "text": "✅ Tidak ada task."})
            return

        task_data = {}

        for i, task_link in enumerate(task_links, 1):
            print(f"=== Processing Task {i}/{len(task_links)} ===")

            try:
                await tab.get(task_link)
                await asyncio.sleep(2)

                try:
                    await tab.select('.prose', timeout=10)
                except Exception:
                    pass

                # Extract URLs from description
                urls = []
                try:
                    link_els = await tab.select_all('.prose a')
                    for el in link_els:
                        href = el.attrs.get('href', '')
                        if href:
                            # Resolve relative URLs
                            if href.startswith('/'):
                                href = BASE + href
                            urls.append(href)
                except Exception:
                    pass

                if not urls:
                    print("  No URLs found")
                    continue
            except Exception as e:
                print(f"  ❌ Error loading task {i}: {e}")
                continue

            print(f"  URLs: {urls}")

            for url in urls:
                platform = get_platform(url)
                print(f"  Platform: {platform}")

                try:
                    if platform == 'tiktok':
                        await do_tiktok_task(tab, url)
                    elif platform == 'instagram':
                        await do_instagram_task(tab, url)
                    elif platform == 'youtube':
                        await do_youtube_task(tab, url)
                    else:
                        print(f"  Unknown platform: {url} — skip")
                        break

                    screenshot_path = await take_screenshot(tab, i)
                    task_data[i] = {'link': task_link, 'screenshot': screenshot_path}
                except Exception as e:
                    print(f"  ❌ Error task {i}: {e}")
                    continue

        # ============ TELEGRAM + UPLOAD ============
        print("\n=== Semua proses sosial media selesai! ===")
        print(f"Screenshots: {screenshot_dir}")

        if task_data:
            send_telegram_album(task_data)

            if wait_for_telegram_confirmation():
                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                  json={"chat_id": chat_id, "text": "🚀 Memulai upload bukti..."})

                print("\n=== Upload Bukti ===")
                for task_num, data in task_data.items():
                    print(f"Upload Task {task_num}...")
                    await upload_proof_and_submit(tab, data['link'], data['screenshot'])
                print("\n=== Semua task sukses disubmit! ===")

                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                  json={"chat_id": chat_id, "text": "🎉 Semua task selesai!"})
            else:
                print("\n=== Dibatalkan ❌ ===")
                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                  json={"chat_id": chat_id, "text": "❌ Dibatalkan."})
        else:
            print("\nTidak ada task yg berhasil diproses.")

    except Exception as e:
        print(f"\n[CRITICAL] {type(e).__name__}: {e}")
        _clean_lock_files()
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            err_msg = str(e)[:150]
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": chat_id,
                                "text": f"❌ CRITICAL ERROR\n`{err_msg}`"})
    finally:
        if browser:
            try:
                await browser.stop()
                print("  - Browser closed")
            except Exception:
                pass
            browser = None
        _clean_lock_files()


# ============================================================
#  TELEGRAM LISTENER (SYNC)
# ============================================================

def listen_telegram_command():
    """Polling Telegram getUpdates, jalankan /run command."""
    print("🤖 Bot standby (zendriver CDP) — menunggu /run...")
    if not TELEGRAM_BOT_TOKEN:
        print("WARNING: TELEGRAM_BOT_TOKEN tidak ada!")
        return

    offset = None
    url_updates = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            res = requests.get(url_updates, params=params, timeout=35)
            data = res.json()

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"].strip().lower()
                        if text == "/run":
                            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                                  f"/run dari chat_id: {chat_id}")
                            asyncio.run(run_automation(str(chat_id)))
            time.sleep(1)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"Error polling: {e}")
            time.sleep(5)


# ============================================================
#  ENTRY POINT
# ============================================================

if __name__ == "__main__":
    # Bersihin zombie Brave automation profile
    _kill_automation_profile_brave()
    _clean_lock_files()
    cleanup_other_main_instances()
    save_current_pid()
    print("\n[Main] Bot Listener Aktif (zendriver)...")
    listen_telegram_command()
