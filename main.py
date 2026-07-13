"""
Sistem Partisipasi Automation — Zendriver Edition
Undetectable browser automation via Chrome DevTools Protocol.
"""
import os
import re
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
        browser_args.extend([
            "--headless=new",
            "--window-size=1920,1080",
            # Anti-headless-detection
            "--disable-features=HeadlessChrome",
            "--lang=en-US",
        ])

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


async def _switch_to_visible_and_wait(tab: zd.Tab, url: str, timeout: int = 300) -> bool:
    """Stop headless browser, buka visible Brave, tunggu user solve captcha & tutup."""
    global browser
    print("    🖥️  Membuka Brave visible untuk solve captcha...")
    print(f"    ⏳ Kamu punya {timeout}s untuk solve captcha di jendela Brave")
    print("    💡 Tutup Brave setelah selesai solve")

    # Stop headless
    if browser:
        try:
            await browser.stop()
        except Exception:
            pass
        browser = None

    # Buka visible Brave
    subprocess.Popen([
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        f"--user-data-dir={CHROME_PROFILE_PATH}",
        url,
    ])

    # Tunggu user tutup Brave (polling — cuma automation profile)
    start = time.time()
    while time.time() - start < timeout:
        await asyncio.sleep(2)
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"@(Get-CimInstance Win32_Process -Filter \"Name='brave.exe'\" "
                 f"| Where-Object {{ $_.CommandLine -match 'AutomationProfile' }}).Count"],
                capture_output=True, text=True)
            count = int(result.stdout.strip() or "0")
            if count == 0:
                print("    ✅ Brave automation profile ditutup — captcha harusnya solved")
                return True
        except Exception:
            pass
        elapsed = int(time.time() - start)
        if elapsed % 30 == 0:
            print(f"    ⏳ Menunggu Brave automation profile ditutup... ({elapsed}s)")

    print(f"    ❌ Timeout ({timeout}s) — user ga nutup Brave")
    # Kill visible Brave
    _kill_automation_profile_brave()
    return False


async def _restart_headless() -> zd.Tab:
    """Restart browser dalam headless mode, return tab."""
    global browser
    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    browser = await zd.start(
        browser_executable_path=brave_path,
        user_data_dir=CHROME_PROFILE_PATH,
        headless=True,
        browser_args=[
            "--mute-audio", "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-gpu", "--headless=new", "--window-size=1920,1080",
            "--disable-features=HeadlessChrome", "--lang=en-US",
        ],
        disable_webrtc=True,
        disable_webgl=True,
    )
    tab = browser.main_tab
    await tab.set_window_size(1280, 800)
    _clean_lock_files()
    print("    🔒 Kembali ke headless mode")
    return tab


async def _restart_visible() -> zd.Tab:
    """Restart browser dalam VISIBLE mode (buat TikTok yg bandel)."""
    global browser
    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    browser = await zd.start(
        browser_executable_path=brave_path,
        user_data_dir=CHROME_PROFILE_PATH,
        headless=False,
        browser_args=[
            "--mute-audio", "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-gpu", "--window-size=1280,800",
        ],
        disable_webrtc=True,
        disable_webgl=True,
    )
    tab = browser.main_tab
    await tab.set_window_size(1280, 800)
    _clean_lock_files()
    print("    🖥️  Visible mode — user bisa lihat/solve captcha")
    return tab


async def do_tiktok_task(tab: zd.Tab, url: str):
    """Follow + Like TikTok via zendriver CDP. Raise Exception kalo gagal total."""
    global _tiktok_prewarmed

    # Pre-warm: kunjungi TikTok homepage dulu buat load session cookies
    if not _tiktok_prewarmed:
        print("  [TikTok] Pre-warming session...")
        await tab.get("https://www.tiktok.com/")
        await asyncio.sleep(4)
        warm_block = await _detect_tiktok_block(tab)
        if warm_block:
            print(f"  ⚠️ TikTok pre-warm kena {warm_block}!")
            if HEADLESS_MODE:
                print("  🔓 Switching ke visible mode buat solve captcha...")
                if not await _switch_to_visible_and_wait(tab, "https://www.tiktok.com/"):
                    raise Exception(
                        "TikTok session belum verified! "
                        "Jalankan: python main.py --prewarm\n"
                        "Login/solve captcha di TikTok, tutup Brave, lalu /run lagi."
                    )
                print("  ✅ Pre-warm verified — switch back to headless...")
                tab = await _restart_headless()
            else:
                print("  ⚠️ Solve captcha di jendela Brave sekarang...")
                if await _wait_for_captcha_solve(tab):
                    print("  [TikTok] Pre-warm OK")
                else:
                    print("  ⚠️ Pre-warm timeout — lanjut aja")
        else:
            print("  [TikTok] Pre-warm OK — session verified")
        _tiktok_prewarmed = True

    print(f"  [TikTok] URL: {url}")

    for attempt in range(3):
        print(f"  [TikTok] Attempt {attempt + 1}/3...")
        # Navigate ke URL (kecuali last attempt + headless → skip ke visible)
        if attempt < 2 or not HEADLESS_MODE:
            await tab.get(url)
            await asyncio.sleep(5)
            final = tab.url
            print(f"  [TikTok] Final URL: {final}")
            if '/video/' not in (final or ''):
                print(f"  ⚠️ Bukan halaman video! Redirect: {final}")
        else:
            # Attempt 3 headless → langsung visible, jangan sentuh headless
            print("  [TikTok] Skip headless — langsung visible")

        # DETEKSI BLOK
        block = await _detect_tiktok_block(tab)
        if block == "captcha":
            print("  ⚠️ CAPTCHA terdeteksi!")
            if HEADLESS_MODE:
                print("  🔓 Switch ke visible mode...")
                if not await _switch_to_visible_and_wait(tab, url):
                    if attempt < 2:
                        continue
                    raise Exception("TikTok CAPTCHA — user timeout")
                tab = await _restart_visible()
                await tab.get(url)
                await asyncio.sleep(5)
                print(f"  [TikTok] Final URL (visible): {tab.url}")
            else:
                if not await _wait_for_captcha_solve(tab):
                    if attempt < 2:
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
            if HEADLESS_MODE:
                print("  🔓 Retry terakhir — switch ke visible mode...")
                if not await _switch_to_visible_and_wait(tab, url):
                    raise Exception("TikTok tetap blokir — coba lagi nanti.")
                # PROSES DI VISIBLE — jangan restart headless
                tab = await _restart_visible()
                await tab.get(url)
                await asyncio.sleep(5)
                print(f"  [TikTok] Final URL (visible): {tab.url}")
            else:
                raise Exception("TikTok blokir akses setelah 3x retry. Tunggu 30-60 menit.")

        # VERIFIKASI KONTEN
        if not await _wait_for_tiktok_content(tab):
            if attempt < 2:
                print("  ⚠️ Konten TikTok ga muncul")
                await asyncio.sleep(10)
                continue
            raise Exception("Konten TikTok ga muncul setelah 3x retry")

        # === FOLLOW (JS — profile page: text match, video page: data-e2e) ===
        follow_result = await tab.evaluate("""
            (() => {
                // Cek udah following
                if (document.querySelector('[data-e2e="unfollow-button"]')) {
                    return 'already-following';
                }
                // Cari feed-follow button (video page)
                const feedBtn = document.querySelector('[data-e2e="feed-follow"]');
                if (feedBtn && feedBtn.offsetParent !== null) {
                    feedBtn.scrollIntoView({behavior:'instant',block:'center'});
                    feedBtn.click();
                    feedBtn.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                    return 'clicked';
                }
                // Cari follow-button (profile page)
                const followBtn = document.querySelector('[data-e2e="follow-button"]');
                if (followBtn && followBtn.offsetParent !== null) {
                    followBtn.scrollIntoView({behavior:'instant',block:'center'});
                    followBtn.click();
                    followBtn.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                    return 'clicked';
                }
                // Fallback: exact text match
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.textContent || '').trim();
                    if ((t === 'Follow' || t === 'Ikuti') &&
                        btn.offsetParent !== null) {
                        btn.scrollIntoView({behavior:'instant',block:'center'});
                        btn.click();
                        btn.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                        return 'clicked';
                    }
                }
                return 'not-found';
            })()
        """)
        if follow_result == 'already-following':
            print("  - Follow: sudah di-follow")
        elif follow_result == 'clicked':
            await asyncio.sleep(1.5)
            print("  - Follow: ✅ berhasil")
        else:
            print("  - Follow: tombol tidak ditemukan")

        # === LIKE (TikTok video page — wait + verify) ===
        # 1. Tunggu like button proper render
        like_ready = False
        for _ in range(20):  # max 10 detik
            ready = await tab.evaluate(
                "(function(){"
                " var e=document.querySelector('[data-e2e=\"like-icon\"]');"
                " return !!(e && e.offsetParent && e.getBoundingClientRect().width>0);"
                "})()")
            if ready:
                like_ready = True
                break
            await asyncio.sleep(0.5)

        if not like_ready:
            print("  - Like: tombol belum render — skip")
        else:
            # 2. Click with verification — approach simpel
            like_result = 'not-found'
            for tap_attempt in range(3):
                like_result = await tab.evaluate("""
                    (function() {
                        if (document.querySelector('[data-e2e=\"unlike-icon\"]')) return 'already-liked';
                        if (document.querySelector('[aria-label*=\"Unlike\"]')) return 'already-liked';
                        // Coba click span like-icon (TikTok handler ada di span)
                        var sp = document.querySelector('[data-e2e=\"like-icon\"]');
                        if (sp && sp.offsetParent) {
                            sp.scrollIntoView({block:'center'});
                            sp.focus();
                            sp.click();
                            // Event chain
                            ['mousedown','mouseup','click','pointerdown','pointerup'].forEach(
                                function(t){sp.dispatchEvent(new Event(t,{bubbles:true,cancelable:true}));}
                            );
                            return 'clicked-span';
                        }
                        // Fallback: click button with aria-label Like
                        var btns = document.querySelectorAll('button');
                        for (var i=0;i<btns.length;i++) {
                            var a=btns[i].getAttribute('aria-label')||'';
                            if (a.indexOf('Like video')===0&&btns[i].offsetParent) {
                                btns[i].click();
                                return 'clicked-btn';
                            }
                        }
                        return 'not-found';
                    })()
                """)
                await asyncio.sleep(1.5)
                verified = await tab.evaluate("""
                    (function() {
                        if (document.querySelector('[data-e2e=\"unlike-icon\"]')) return 'yes';
                        if (document.querySelector('[aria-label*=\"Unlike\"]')) return 'yes';
                        return 'no';
                    })()
                """)
                if verified == 'yes':
                    break
                if like_result.startswith('clicked') and tap_attempt < 2:
                    print(f"    Like belum terverifikasi (att {tap_attempt+1}) — retry...")
                    await asyncio.sleep(1)

            if like_result == 'already-liked' or verified == 'yes':
                await asyncio.sleep(1)
                print(f"  - Like: ✅ berhasil")
            elif like_result.startswith('clicked'):
                await asyncio.sleep(1)
                print(f"  - Like: ✅ clicked (unverified — UI delay)")
            else:
                print(f"  - Like: tombol tidak ditemukan")

        # === DOUBLE-CHECK SILENT BLOCK ===
        follow_ok = follow_result in ('already-following', 'clicked')
        like_ok = like_result in ('already-liked', 'clicked')

        if not follow_ok and not like_ok:
            if attempt < 2:
                print("  ⚠️ Semua tombol ga ditemukan — kemungkinan halaman blokir")
                await asyncio.sleep(10)
                continue
            raise Exception("TikTok: tombol tidak ditemukan setelah 3x retry.")

        await asyncio.sleep(1)
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

            # --- FOLLOW (exact text match) ---
            followed = False
            for txt in ['Follow', 'Ikuti']:
                try:
                    found = await tab.evaluate(f"""
                        (() => {{
                            for (const el of document.querySelectorAll('button,div[role="button"]')) {{
                                const t = el.textContent.trim();
                                if (t === '{txt}' && el.offsetParent !== null) {{
                                    el.setAttribute('data-zd-fw', '1'); return true;
                                }}
                            }}
                            return false;
                        }})()
                    """)
                    if found:
                        el = await tab.select('[data-zd-fw="1"]', timeout=1)
                        if el:
                            await el.scroll_into_view()
                            await asyncio.sleep(0.3)
                            await el.click()
                            await asyncio.sleep(2)
                            print("  - Follow: ✅ berhasil")
                            followed = True
                            break
                except Exception:
                    pass

            if not followed:
                # Cek udah following
                following = await tab.evaluate("""
                    (() => {
                        for (const el of document.querySelectorAll('button,div[role="button"]')) {
                            const t = el.textContent.trim();
                            if (t === 'Following' || t === 'Mengikuti' ||
                                t === 'Requested' || t === 'Diminta') return true;
                        }
                        return false;
                    })()
                """)
                if following:
                    print("  - Follow: sudah di-follow")
                else:
                    print("  - Follow: tombol tidak ditemukan")

            # --- LIKE (polling — Instagram lazy-load interaction buttons) ---
            like_clicked = 'not-found'
            for _ in range(8):  # polling 8x0.5s = 4 detik
                like_clicked = await tab.evaluate("""
                    (() => {
                        for (const svg of document.querySelectorAll('svg[aria-label="Like"],svg[aria-label="Suka"]')) {
                            if (svg.offsetParent === null) continue;
                            const btn = svg.closest('div[role="button"]');
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                                btn.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                                return 'clicked-button';
                            }
                            svg.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                            return 'clicked-svg';
                        }
                        // Cek udah unlike
                        if (document.querySelector('svg[aria-label="Unlike"]') ||
                            document.querySelector('svg[aria-label="Tidak Suka"]')) {
                            return 'already-liked';
                        }
                        // Coba DIV[role=button] dengan text Like
                        for (const d of document.querySelectorAll('div[role="button"]')) {
                            const t = (d.textContent||'').trim();
                            if ((t === 'Like' || t === 'Suka') && d.offsetParent !== null) {
                                d.click();
                                d.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                                return 'clicked-div';
                            }
                        }
                        return 'not-found';
                    })()
                """)
                if like_clicked != 'not-found':
                    break
                await asyncio.sleep(0.5)

            if like_clicked in ('clicked-button', 'clicked-svg', 'clicked-div'):
                await asyncio.sleep(1)
                print(f"  - Like: ✅ berhasil ({like_clicked})")
            elif like_clicked == 'already-liked':
                print("  - Like: sudah di-like")
            else:
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
    liked = False
    for sel in ['like-button-view-model button',
                '#segmented-like-button button',
                'ytd-segmented-like-dislike-button-renderer button',
                'button[aria-label*="like this video"]']:
        try:
            btn = await tab.select(sel, timeout=2)
            pressed = btn.attrs.get('aria-pressed', '')
            if pressed == 'false':
                await btn.scroll_into_view()
                await asyncio.sleep(0.3)
                await btn.click()
                # JS fallback
                await tab.evaluate(f"""
                    (() => {{ const el = document.querySelector('{sel}');
                     if (el && el.getAttribute('aria-pressed')==='false') {{
                      el.click(); el.dispatchEvent(new MouseEvent('click',
                       {{bubbles:true,cancelable:true}})); }} }})()
                """)
                await asyncio.sleep(1)
                print("  - Like: ✅ berhasil")
                liked = True
                break
            elif pressed == 'true':
                print("  - Like: sudah di-like")
                liked = True
                break
        except Exception:
            continue

    if not liked:
        print("  - Like: tombol tidak ditemukan")

    await asyncio.sleep(2)


# ============================================================
#  SCREENSHOT + UPLOAD
# ============================================================

async def _wait_page_ready(tab: zd.Tab):
    """Tunggu halaman selesai loading — cuma readyState, tanpa delay."""
    for _ in range(20):  # max 10 detik
        try:
            ready = await tab.evaluate("document.readyState")
            if ready == "complete":
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def take_screenshot(tab: zd.Tab, task_number: int) -> str:
    filename = f"task_{task_number}.png"
    filepath = os.path.join(screenshot_dir, filename)
    await tab.save_screenshot(filepath)
    print(f"  - Screenshot: {filepath}")
    return filepath


async def upload_proof_and_submit(tab: zd.Tab, task_link: str,
                                   screenshot_path: str):
    """Upload via CDP DOM.setFileInputFiles + click submit."""
    abs_path = os.path.abspath(screenshot_path)
    fname = os.path.basename(screenshot_path)
    print(f"  [Upload] {fname}")

    await tab.get(task_link)
    await asyncio.sleep(4)

    try:
        await tab.select('.prose', timeout=15)
    except Exception:
        pass
    await asyncio.sleep(2)

    # === DAPATKAN file input node ID ===
    node_id = 0
    # Mark element for CDP
    await tab.evaluate("""
        (() => {
            for (const el of document.querySelectorAll('input[type="file"]')) {
                el.setAttribute('data-zd-up', '1');
                break;
            }
        })()
    """)
    await asyncio.sleep(0.3)

    try:
        doc = await tab.send(zd.cdp.dom.get_document(depth=0))
        print(f"    doc nodeId={doc.node_id}")
        node_id = await tab.send(
            zd.cdp.dom.query_selector(
                node_id=doc.node_id,
                selector='[data-zd-up="1"]'
            )
        )
        print(f"    file input nodeId={node_id}")
    except Exception as e:
        print(f"    CDP query error: {e}")

    # === UPLOAD via CDP ===
    if node_id and node_id != 0:
        try:
            # Use forward slashes for CDP
            cdp_path = abs_path.replace("\\", "/")
            await tab.send(zd.cdp.dom.set_file_input_files(
                files=[cdp_path],
                node_id=node_id
            ))
            await asyncio.sleep(2)

            # Dispatch change event for React
            await tab.evaluate("""
                (() => {
                    const el = document.querySelector('[data-zd-up="1"]');
                    if (el) {
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                    }
                })()
            """)
            await asyncio.sleep(1)

            fc = await tab.evaluate(
                "(document.querySelector('input[type=\"file\"]')?.files?.length) || 0")
            print(f"    files.length={fc}")
            if fc > 0:
                print(f"    ✅ File uploaded")
            else:
                print(f"    ⚠️ files.length=0 — try anyway")
        except Exception as e:
            print(f"    CDP setFileInputFiles error: {e}")
    else:
        print(f"    ⚠️ File input nodeId invalid — skip CDP upload")

    # === CLICK SUBMIT (TANPA pre-fill reason — biar dialog handle) ===
    await tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    clicked = await tab.evaluate("""
        (() => {
            for (const btn of document.querySelectorAll('button')) {
                if (btn.textContent.trim() === 'Submit' &&
                    !btn.closest('#upload_reason_modal')) {
                    if (btn.disabled) return 'disabled';
                    btn.click();
                    return 'clicked';
                }
            }
            return 'not-found';
        })()
    """)
    print(f"    Main submit: {clicked}")

    if clicked == 'disabled':
        for i in range(30):
            await asyncio.sleep(1)
            r = await tab.evaluate("""
                (() => {
                    for (const btn of document.querySelectorAll('button')) {
                        if (btn.textContent.trim() === 'Submit' &&
                            !btn.closest('#upload_reason_modal')) {
                            if (!btn.disabled) { btn.click(); return 'clicked'; }
                            return 'still-disabled';
                        }
                    }
                    return 'gone';
                })()
            """)
            if r in ('clicked', 'gone'):
                print(f"    Submit clicked after {i+1}s")
                break

    await asyncio.sleep(3)

    # === EXPIRED DIALOG (muncu kalau reason kosong) ===
    try:
        dialog = await tab.select('#upload_reason_modal', timeout=5)
        if dialog:
            print("    Task expired — dialog muncul, isi reason...")
            # Isi reason textarea DALAM dialog
            await tab.evaluate("""
                (() => {
                    const ta = document.querySelector('#upload_reason_modal textarea');
                    if (ta) { ta.value = '-';
                     ta.dispatchEvent(new Event('input', {bubbles: true}));
                     ta.dispatchEvent(new Event('change', {bubbles: true})); }
                })()
            """)
            await asyncio.sleep(0.5)
            # Click dialog Submit — INI submit sebenarnya
            await tab.evaluate("""
                (() => {
                    const btns = document.querySelectorAll('#upload_reason_modal button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === 'Submit') { btn.click(); return; }
                    }
                })()
            """)
            await asyncio.sleep(3)
            print("    Expired dialog submitted")
        else:
            print("    No expired dialog — submitted on time")
    except Exception:
        print("    No expired dialog (on time)")

    print(f"    ✅ Done — {fname}")


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

        # Tunggu table + data ready (AJAX loading)
        try:
            await tab.select('.rdt_Table', timeout=15)
        except Exception:
            raise Exception("Dashboard table tidak muncul — login gagal?")
        # Tunggu data rows muncul (react-datatable render async)
        await asyncio.sleep(3)
        for _ in range(10):  # retry kalo masih kosong
            rows = await tab.select_all('.rdt_TableRow')
            if rows:
                break
            await asyncio.sleep(1)

        # Ambil task links
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
                await asyncio.sleep(3)

                # Tunggu konten muncul
                try:
                    await tab.select('.prose', timeout=10)
                except Exception:
                    pass
                await asyncio.sleep(2)  # tunggu render react

                # Extract URLs from description
                urls = []
                try:
                    link_els = await tab.select_all('.prose a')
                    if not link_els:
                        # Retry — mungkin masih loading
                        await asyncio.sleep(2)
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

                    # Screenshot — retry with browser restart if CDP drops
                    for ss_attempt in range(3):
                        try:
                            if ss_attempt > 0:
                                # Restart case: navigate ke social URL
                                await tab.get(url)
                                await asyncio.sleep(3)
                            # ss_attempt==0: tab masih di halaman setelah like — langsung SS
                            await _wait_page_ready(tab)
                            print(f"  [SS] URL: {tab.url}")
                            screenshot_path = await take_screenshot(tab, i)
                            task_data[i] = {'link': task_link, 'screenshot': screenshot_path}
                            break
                        except Exception as ss_err:
                            err_msg = str(ss_err)
                            if 'no close frame' in err_msg and ss_attempt < 2:
                                print(f"  ⚠️ CDP disconnected — restarting browser...")
                                try:
                                    await browser.stop()
                                except Exception:
                                    pass
                                browser = None
                                await asyncio.sleep(1)
                                _clean_lock_files()
                                browser, tab = await init_browser()
                                await tab.get("https://admin.sistem-partisipasi.jovasoftware.id/dashboard")
                                await asyncio.sleep(2)
                                print(f"  ✅ Browser restarted")
                            else:
                                raise
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

                # Restart browser — CDP WebSocket putus setelah idle lama
                print("\n=== Restart Browser untuk Upload ===")
                try:
                    await browser.stop()
                except Exception:
                    pass
                browser = None
                await asyncio.sleep(1)
                _clean_lock_files()

                # Re-init (headless ok — dashboard ga peduli)
                brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
                browser = await zd.start(
                    browser_executable_path=brave_path,
                    user_data_dir=CHROME_PROFILE_PATH,
                    headless=HEADLESS_MODE,
                    browser_args=[
                        "--mute-audio", "--no-sandbox", "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ] + (["--headless=new", "--window-size=1920,1080",
                          "--disable-features=HeadlessChrome", "--lang=en-US"]
                         if HEADLESS_MODE else []),
                    disable_webrtc=True,
                    disable_webgl=True,
                )
                tab = browser.main_tab
                await tab.set_window_size(1280, 800)

                # Login ulang dashboard
                print("  - Login ulang dashboard...")
                await tab.get("https://admin.sistem-partisipasi.jovasoftware.id/dashboard")
                await asyncio.sleep(3)
                try:
                    email_input = await tab.select('input[type="email"]', timeout=5)
                    if email_input:
                        await email_input.send_keys(EMAIL)
                        await tab.select('input[type="password"]', timeout=3)
                        await (await tab.select('input[type="password"]', timeout=3)).send_keys(PASSWORD)
                        await (await tab.select('button[type="submit"]', timeout=3)).click()
                        await asyncio.sleep(5)
                except Exception:
                    pass
                print("  - Browser siap untuk upload")

                print("\n=== Upload Bukti ===")
                failed_tasks = []
                for task_num, data in task_data.items():
                    print(f"Upload Task {task_num}...")
                    try:
                        await upload_proof_and_submit(tab, data['link'], data['screenshot'])
                    except Exception as upload_err:
                        print(f"  ❌ Task {task_num} upload gagal: {upload_err}")
                        failed_tasks.append(task_num)

                if failed_tasks:
                    if len(failed_tasks) == len(task_data):
                        msg = (f"❌ Upload GAGAL TOTAL — {len(failed_tasks)}/{len(task_data)} task.\n"
                               f"Task gagal: {failed_tasks}\n"
                               f"Cek log untuk detail error.")
                    else:
                        msg = (f"⚠️ Upload sebagian — {len(failed_tasks)}/{len(task_data)} gagal.\n"
                               f"Gagal: Task {failed_tasks}")
                    print(f"\n=== {msg} ===")
                else:
                    msg = "🎉 Semua task sukses disubmit!"
                    print(f"\n=== {msg} ===")

                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                  json={"chat_id": chat_id, "text": msg})
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
    import argparse
    parser = argparse.ArgumentParser(description="Sistem Partisipasi Bot (zendriver)")
    parser.add_argument("--prewarm", action="store_true",
                        help="Buka Brave automation profile untuk pre-warm session")
    args = parser.parse_args()

    if args.prewarm:
        print("[Prewarm] Membuka Brave dengan automation profile...")
        print("[Prewarm] 1. Login/solve captcha di TikTok")
        print("[Prewarm] 2. Tutup Brave setelah selesai")
        _kill_automation_profile_brave()
        _clean_lock_files()
        subprocess.Popen([
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            f"--user-data-dir={CHROME_PROFILE_PATH}",
        ])
        sys.exit(0)

    # Normal mode: bot listener
    _kill_automation_profile_brave()
    _clean_lock_files()
    cleanup_other_main_instances()
    save_current_pid()
    print("\n[Main] Bot Listener Aktif (zendriver)...")
    listen_telegram_command()
