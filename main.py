import os
import requests
import json
from datetime import datetime
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from dotenv import load_dotenv
import time
import subprocess

basedir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(basedir, '.env'))

PID_FILE = os.path.join(basedir, "bot.pid")

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
CHROME_PROFILE_PATH = os.getenv('CHROME_PROFILE_PATH')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HEADLESS_MODE = os.getenv('HEADLESS_MODE', 'False').lower() == 'true'

driver = None
wait = None
screenshot_dir = None
brave_process = None

def cleanup_browser_process():
    if not CHROME_PROFILE_PATH:
        return
    
    print(f"\n[Cleanup] Mencari proses Brave yang menggunakan profile: {CHROME_PROFILE_PATH}")
    try:
        # Get process list with command lines using PowerShell
        # This is more robust on Windows than wmic
        ps_cmd = f'Get-CimInstance Win32_Process -Filter "Name = \'brave.exe\'" | Select-Object ProcessId, CommandLine | ConvertTo-Json'
        cmd = ["powershell", "-Command", ps_cmd]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout.strip():
            import json
            try:
                data = json.loads(result.stdout)
                # PowerShell might return a single object or a list
                processes = data if isinstance(data, list) else [data]
                
                for proc in processes:
                    cmd_line = proc.get('CommandLine', '')
                    pid = proc.get('ProcessId')
                    
                    if cmd_line and CHROME_PROFILE_PATH.lower() in cmd_line.lower():
                        print(f"  - Menghentikan proses PID {pid} yang menggunakan profile ini...")
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            except:
                pass

        # Hapus file lock jika masih ada setelah proses dihentikan
        for filename in ["SingletonLock", "SingletonSocket", "DevToolsActivePort"]:
            file_path = os.path.join(CHROME_PROFILE_PATH, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"  - Berhasil menghapus file lock: {filename}")
                except:
                    pass
    except Exception as e:
        print(f"  - Gagal melakukan cleanup: {e}")

def cleanup_other_main_instances():
    """Menghentikan proses bot lain yang ID-nya tercatat di bot.pid"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())

            if old_pid == os.getpid():
                return

            print(f"\n[Cleanup] Menutup instance bot lama (PID {old_pid})...")
            # Gunakan taskkill untuk memastikan proses mati
            subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], capture_output=True)
            time.sleep(1)
        except (ValueError, ProcessLookupError, Exception):
            pass

def save_current_pid():
    """Mencatat PID proses saat ini ke file"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"Gagal mencatat PID: {e}")

def graceful_shutdown():
    """Cleanup dipanggil saat terminate/exit"""
    print("\n[Shutdown] Cleaning up...")
    if driver:
        try:
            driver.quit()
            print("  - Browser closed")
        except Exception:
            pass
    if brave_process:
        try:
            brave_process.terminate()
            brave_process.wait(timeout=5)
            print("  - Brave process terminated")
        except Exception:
            try:
                brave_process.kill()
            except Exception:
                pass
    # Bersihin lock files biar bisa dibuka manual
    if CHROME_PROFILE_PATH:
        for lock in ["SingletonLock", "SingletonSocket", "DevToolsActivePort"]:
            lp = os.path.join(CHROME_PROFILE_PATH, lock)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                    print(f"  - Removed lock: {lock}")
                except Exception:
                    pass

def signal_handler(sig, frame):
    """Handle SIGINT (Ctrl+C) dan SIGTERM"""
    print(f"\n[Shutdown] Signal {sig} diterima...")
    graceful_shutdown()
    sys.exit(0)

# Register signal handlers
import sys
import signal
signal.signal(signal.SIGINT, signal_handler)
try:
    signal.signal(signal.SIGTERM, signal_handler)
except AttributeError:
    pass  # Windows might not support SIGTERM in all Python versions

# Register atexit handler (fallback)
import atexit
atexit.register(graceful_shutdown)

def init_driver():
    global driver, wait, screenshot_dir, brave_process

    print("\n[Init] Menyiapkan browser...")

    # Cek apakah profile sedang dipake oleh Brave lain (user manual)
    profile_in_use = False
    if CHROME_PROFILE_PATH:
        try:
            ps_cmd = 'Get-CimInstance Win32_Process -Filter "Name = \'brave.exe\'" | Select-Object ProcessId, CommandLine | ConvertTo-Json'
            result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
            if result.stdout.strip():
                data = json.loads(result.stdout)
                processes = data if isinstance(data, list) else [data]
                for proc in processes:
                    cmd_line = proc.get('CommandLine', '') or ''
                    if cmd_line and CHROME_PROFILE_PATH.lower() in cmd_line.lower():
                        profile_in_use = True
                        break
        except Exception:
            pass

    if profile_in_use:
        print("  ⚠️ Brave sedang berjalan dengan profile ini.")
        print("  ⚠️ TUTUP Brave terlebih dahulu agar cookies tersimpan ke disk.")
        print("  ⚠️ Kalau tidak ditutup, verifikasi/cookies bisa hilang!")
        print("  ⏳ Menunggu 10 detik... (Ctrl+C untuk batal)")
        time.sleep(10)
        # Clean lock files dari session sebelumnya
        for lock in ["SingletonLock", "SingletonSocket", "Lockfile", "DevToolsActivePort"]:
            lp = os.path.join(CHROME_PROFILE_PATH, lock)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                except Exception:
                    pass

    options = Options()
    if CHROME_PROFILE_PATH:
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")

    # Flags untuk meningkatkan stabilitas dan mencegah crash
    options.add_argument("--mute-audio")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Anti-detection stealth
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    if not os.path.exists(brave_path):
        raise Exception(f"Brave Browser tidak ditemukan di lokasi: {brave_path}")

    options.binary_location = brave_path

    if HEADLESS_MODE:
        options.add_argument("--headless=new")

    try:
        driver = webdriver.Chrome(options=options)
        driver.set_window_size(1280, 800)
        wait = WebDriverWait(driver, 15)

        # --- Anti-detection: hide navigator.webdriver ---
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, "webdriver", {get: () => undefined});
                Object.defineProperty(navigator, "plugins", {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, "languages", {get: () => ["en-US", "en"]});
            '''
        })
        print("  - Stealth anti-detection injected")

        today = datetime.now().strftime("%Y-%m-%d")
        screenshot_dir = os.path.join(os.path.dirname(__file__), today)
        os.makedirs(screenshot_dir, exist_ok=True)
        print("  - Browser siap!")
    except Exception as e:
        print(f"  - CRITICAL ERROR saat init driver: {e}")
        # Clean lock files saja, jangan kill process
        if CHROME_PROFILE_PATH:
            for lock in ["SingletonLock", "SingletonSocket", "DevToolsActivePort"]:
                lp = os.path.join(CHROME_PROFILE_PATH, lock)
                if os.path.exists(lp):
                    try:
                        os.remove(lp)
                    except Exception:
                        pass
        raise e

def get_platform(url):
    """Determine platform from URL"""
    domain = urlparse(url).netloc.lower()
    if 'tiktok.com' in domain:
        return 'tiktok'
    elif 'instagram.com' in domain:
        return 'instagram'
    elif 'youtube.com' in domain or 'youtu.be' in domain:
        return 'youtube'
    return None

def extract_urls_from_description(description_element):
    """Extract all URLs from the task description"""
    links = description_element.find_elements(By.TAG_NAME, 'a')
    urls = [link.get_attribute('href') for link in links if link.get_attribute('href')]
    return urls

# ============================================================
#  TIKTOK HELPER: block detection + content verification
# ============================================================

def _detect_tiktok_block():
    """
    Cek halaman TikTok saat ini — return tipe blok atau None (aman).
    Prioritas urutan: captcha > login > access-denied > none.
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
    except Exception:
        body_text = ""

    # --- CAPTCHA (prioritas tertinggi, butuh manual solve) ---
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
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return "captcha"
        except Exception:
            pass

    # --- LOGIN REDIRECT ---
    current_url = driver.current_url.lower()
    if '/login' in current_url or '/signup' in current_url:
        return "login_required"

    login_input_selectors = [
        'input[name="username"]',
        'input[placeholder*="phone"]',
        'input[placeholder*="email"]',
        'input[placeholder*="user"]',
    ]
    for sel in login_input_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return "login_required"
        except Exception:
            pass

    # --- ACCESS DENIED / RATE LIMIT ---
    denied_phrases = [
        "access denied",
        "too many requests",
        "something went wrong",
        "you are visiting our service too frequently",
        "try again later",
        "you've been temporarily blocked",
        "verify you are human",
        "verify to continue",
        "are you a human",
    ]
    for phrase in denied_phrases:
        if phrase in body_text:
            return "blocked"

    page_title = driver.title.lower()
    blocked_titles = ["access denied", "too many requests", "verify", "blocked", "sorry"]
    for t in blocked_titles:
        if t in page_title:
            return "blocked"

    # --- BLANK PAGE / SILENT BLOCK ---
    # TikTok kadang return halaman kosong tanpa teks sebagai blokir halus
    if len(body_text.strip()) < 20:
        # Konfirmasi: cek sumber halaman (bukan cuma body text)
        try:
            page_source = driver.page_source.lower()
            # Kalau source code juga pendek atau hampir kosong → blocked
            if len(page_source) < 500:
                return "blocked"
            # Kalau body pendek tapi source ada → cek pola error di source
            if "captcha" in page_source or "verify" in page_source or "block" in page_source:
                return "blocked"
        except Exception:
            pass

    # --- HTTP ERROR via page content ---
    # Beberapa block pattern: empty body with error in HTML
    try:
        if "<pre>" in driver.page_source.lower() and "error" in driver.page_source.lower():
            return "blocked"
    except Exception:
        pass

    return None


def _wait_for_captcha_solve(timeout=300):
    """Tunggu user solve captcha manual. Return True kalo solved, False kalo timeout."""
    print("    ⏳ Menunggu Anda solve captcha...")
    start = time.time()
    last_log = start
    while time.time() - start < timeout:
        time.sleep(1)
        status = _detect_tiktok_block()
        if status != "captcha":
            # Captcha mungkin hilang, tapi cek apakah yg muncul malah block lain
            if status is None:
                print("    ✅ Captcha solved!")
                return True
            elif status == "blocked":
                print("    ❌ Captcha solved tapi muncul Access Denied")
                return False
        elapsed = int(time.time() - start)
        if time.time() - last_log > 30:
            remaining = timeout - elapsed
            print(f"    ⏳ Masih menunggu... ({elapsed}s / {timeout}s, sisa {remaining}s)")
            last_log = time.time()
    print(f"    ❌ Timeout menunggu captcha ({timeout}s)")
    return False


def _wait_for_tiktok_content(timeout=15):
    """
    Konfirmasi halaman TikTok beneran render konten video.
    Poll elemen khas TikTok; fallback ke body text length.
    Return True kalo konten muncul, False kalo kosong/block.
    """
    content_selectors = [
        '[data-e2e="follow-button"]',
        '[data-e2e="unfollow-button"]',
        '[data-e2e="like-icon"]',
        '[data-e2e="unlike-icon"]',
        '[data-e2e="video-title"]',
        'video',
    ]

    deadline = time.time() + timeout
    while time.time() < deadline:
        # Cek dulu — jangan sampe yg muncul malah block screen
        if _detect_tiktok_block() is not None:
            return False

        for sel in content_selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    return True
            except Exception:
                pass
        time.sleep(0.5)

    # Fallback: body text > 100 karakter = mungkin konten udah render
    try:
        body_text = driver.find_element(By.TAG_NAME, 'body').text.strip()
        if len(body_text) > 100:
            return True
    except Exception:
        pass

    return False


# ============================================================
#  TIKTOK TASK (REWRITE)
# ============================================================

def do_tiktok_task(url):
    """
    Follow + Like pada halaman TikTok.
    Deteksi blok sebelum interaksi. Retry 3x dengan backoff.
    Raise Exception kalo gagal total (biar main loop catch & skip).
    """
    print(f"  [TikTok] Memproses: {url}")

    for attempt in range(3):
        print(f"  [TikTok] Attempt {attempt + 1}/3...")
        driver.get(url)
        time.sleep(4)

        # === DETEKSI BLOK ===
        block = _detect_tiktok_block()
        if block == "captcha":
            print("  ⚠️ CAPTCHA terdeteksi!")
            if not _wait_for_captcha_solve():
                if attempt < 2:
                    print(f"  ⏳ Retry setelah captcha timeout...")
                    continue
                raise Exception("TikTok CAPTCHA timeout — butuh intervensi manual")
            # Captcha solved, refresh page
            driver.get(url)
            time.sleep(3)

        elif block == "login_required":
            raise Exception(
                "TikTok redirect ke halaman login — "
                "session mungkin expired. Buka TikTok di browser profile "
                "dan login ulang secara manual, lalu coba lagi."
            )

        elif block == "blocked":
            if attempt < 2:
                backoff = (attempt + 1) * 15
                print(f"  ❌ Access Denied / Rate Limited")
                print(f"  ⏳ Menunggu {backoff}s sebelum retry...")
                time.sleep(backoff)
                continue
            raise Exception(
                "TikTok terus memblokir akses setelah 3x retry. "
                "Kemungkinan IP kena rate-limit. Tunggu 30-60 menit sebelum coba lagi."
            )

        # === VERIFIKASI KONTEN ===
        if not _wait_for_tiktok_content():
            if attempt < 2:
                print("  ⚠️ Konten TikTok ga muncul — mungkin blokir silent")
                time.sleep(10)
                continue
            raise Exception("TikTok konten video ga muncul setelah 3x retry")

        # === FOLLOW ===
        follow_done = False
        follow_btn = None
        # Cek apakah udah follow
        try:
            unfollow_btn = driver.find_element(By.CSS_SELECTOR, '[data-e2e="unfollow-button"]')
            if unfollow_btn.is_displayed():
                print("  - Follow: sudah di-follow sebelumnya")
                follow_done = True
        except Exception:
            pass

        if not follow_done:
            follow_btn = None
            # Cari tombol follow
            for sel, by_type in [
                ('[data-e2e="follow-button"]', By.CSS_SELECTOR),
                ('//button[contains(text(), "Follow")]', By.XPATH),
                ('button[class*="follow"]:not([class*="unfollow"])', By.CSS_SELECTOR),
            ]:
                try:
                    els = driver.find_elements(by_type, sel)
                    for btn in els:
                        if btn.is_displayed():
                            text = btn.text.lower()
                            if 'following' not in text:
                                follow_btn = btn
                                break
                    if follow_btn:
                        break
                except Exception:
                    pass

            if follow_btn:
                driver.execute_script("arguments[0].scrollIntoView(true);", follow_btn)
                time.sleep(0.5)
                follow_btn.click()
                time.sleep(1.5)
                print("  - Follow: ✅ berhasil")
            else:
                print("  - Follow: tombol tidak ditemukan (mungkin private/bug akun)")

        # === LIKE ===
        like_done = False
        like_btn = None
        # Cek apakah udah like
        try:
            unlike_btn = driver.find_element(By.CSS_SELECTOR, '[data-e2e="unlike-icon"]')
            if unlike_btn.is_displayed():
                print("  - Like: sudah di-like sebelumnya")
                like_done = True
        except Exception:
            pass

        if not like_done:
            like_btn = None
            for sel in [
                '[data-e2e="like-icon"]',
                'button[aria-label*="Like"]',
                '[class*="like-button"]',
            ]:
                try:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    for btn in els:
                        if btn.is_displayed():
                            aria = (btn.get_attribute('aria-label') or '').lower()
                            if 'unlike' not in aria:
                                like_btn = btn
                                break
                    if like_btn:
                        break
                except Exception:
                    pass

            if like_btn:
                driver.execute_script("arguments[0].scrollIntoView(true);", like_btn)
                time.sleep(0.5)
                like_btn.click()
                time.sleep(1)
                print("  - Like: ✅ berhasil")
            else:
                print("  - Like: tombol tidak ditemukan")

        # === DOUBLE-CHECK: kalo dua-duanya ga ketemu → silent block ===
        follow_found = follow_done or (follow_btn is not None)
        like_found = like_done or (like_btn is not None)

        if not follow_found and not like_found:
            if attempt < 2:
                print("  ⚠️ Semua tombol ga ditemukan — kemungkinan halaman blokir/diblok")
                time.sleep(10)
                continue
            raise Exception(
                "TikTok: tidak ada tombol follow/like setelah 3x retry. "
                "Kemungkinan halaman diblokir atau konten tidak tersedia."
            )

        time.sleep(2)
        return  # sukses

    raise Exception("TikTok gagal setelah 3x retry (kemungkinan blokir persisten)")

def convert_instagram_reel_to_post(url):
    """Convert reels/reel URL to post /p/ URL if applicable"""
    lower_url = url.lower()
    if '/reels/' in lower_url or '/reel/' in lower_url:
        parts = url.split('/')
        post_id = None
        for i, part in enumerate(parts):
            if part.lower() in ('reels', 'reel') and i + 1 < len(parts):
                post_id = parts[i + 1].split('?')[0].split('#')[0]
                break
        if post_id:
            new_url = f"https://www.instagram.com/p/{post_id}/"
            if new_url != url:
                print(f"  - Converted URL to: {new_url}")
            return new_url
    return url


def perform_instagram_actions(target_url):
    """Run follow + like steps on a single Instagram URL"""
    driver.get(target_url)
    time.sleep(5)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    time.sleep(3)

    try:
        follow_btns = None
        selectors = [
            "//button[.//div[contains(text(), 'Follow')]]",
            "//div[@role='button'][descendant-or-self::*[contains(text(), 'Follow')]]",
        ]
        try:
            # Try nested div structure (new Instagram layout)
            for sel in selectors:
                follow_btns = driver.find_elements(By.XPATH, sel)
                if follow_btns:
                    break
        except:
            pass

        if not follow_btns:
            try:
                # Fallback to old structure
                for sel in selectors:
                    follow_btns = driver.find_elements(By.XPATH, sel)
                    if follow_btns:
                        break
            except:
                pass

        if follow_btns:
            for btn in follow_btns:
                btn_text = btn.text.strip().lower()
                if btn_text == 'follow':
                    btn.click()
                    time.sleep(2)
                    print("  - Followed!")
                    break
            else:
                print("  - Already following or no Follow button")
        else:
            print("  - Already following or no Follow button")
    except:
        print("  - Follow button not found")

    try:
        like_svgs = driver.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Like"]')
        if not like_svgs:
            like_svgs = driver.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Suka"]')

        if like_svgs:
            like_svg = like_svgs[-1]
            like_btn = like_svg.find_element(By.XPATH, "./ancestor::div[@role='button']")
            like_btn.click()
            time.sleep(1)
            print("  - Liked!")
        else:
            unlike_svgs = driver.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Unlike"]')
            if not unlike_svgs:
                unlike_svgs = driver.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Batal suka"]')

            if unlike_svgs:
                print("  - Already liked")
            else:
                print("  - Like button not found")
    except Exception as e:
        print(f"  - Like error: {e}")

    time.sleep(2)


def do_instagram_task(url):
    """Follow + Like on Instagram; always normalize reels to /p/ before visiting"""
    target_url = convert_instagram_reel_to_post(url)
    if target_url != url:
        print(f"  - Normalized to post URL: {target_url}")

    try:
        perform_instagram_actions(target_url)
    except TimeoutException:
        print("  - Timeout detected, retrying once with normalized URL...")
        perform_instagram_actions(target_url)

def handle_youtube_ads(max_wait=60):
    """Detect and skip YouTube ads if they appear"""
    print("\n🔍 Checking for YouTube ads...")

    start_time = time.time()

    while time.time() - start_time < max_wait:
        # Check if an ad is currently playing
        is_ad = driver.execute_script("""
            var player = document.getElementById('movie_player');
            if (player && player.classList.contains('ad-showing')) return true;
            if (document.querySelector('.ad-showing')) return true;
            if (document.querySelector('.ytp-ad-player-overlay')) return true;
            return false;
        """)

        if not is_ad:
            print("  ✅ No ad playing, continuing...")
            break

        print("  ⚠️ Ad detected! Looking for skip button...")

        # Try to find and click skip button with various selectors
        skip_selectors = [
            ".ytp-skip-ad-button",
            ".ytp-ad-skip-button",
            ".ytp-ad-skip-button-modern",
            "button.ytp-ad-skip-button",
            "button.ytp-ad-skip-button-modern",
            ".ytp-ad-skip-button-container button",
            "button[class*='ytp-ad-skip']",
            ".ytp-skip-ad-button__text",
        ]

        skipped = False
        for selector in skip_selectors:
            try:
                skip_btn = driver.find_element(By.CSS_SELECTOR, selector)
                if skip_btn.is_displayed() and skip_btn.is_enabled():
                    print(f"  🎯 Skip button found! ({selector})")
                    time.sleep(0.5)
                    try:
                        skip_btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", skip_btn)
                    print("  🎉 Ad skipped!")
                    skipped = True
                    time.sleep(2)
                    break
            except:
                continue

        if skipped:
            # Check if another ad appears (sometimes there are 2 ads)
            time.sleep(2)
            is_still_ad = driver.execute_script("""
                var player = document.getElementById('movie_player');
                if (player && player.classList.contains('ad-showing')) return true;
                return false;
            """)
            if is_still_ad:
                print("  ⚠️ Another ad detected, waiting again...")
                continue
            else:
                print("  ✅ All ads handled!")
                break
        else:
            # No skip button yet, wait a bit
            elapsed = int(time.time() - start_time)
            if elapsed % 5 == 0:
                print(f"    Waiting for skip button... {elapsed}s / {max_wait}s")
            time.sleep(1)

    else:
        print("  ⏰ Ad wait timeout reached, continuing anyway...")


def do_youtube_task(url):
    """Subscribe + Like + Watch on YouTube"""
    driver.get(url)
    time.sleep(5)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    time.sleep(5)

    # Handle ads before doing anything else
    handle_youtube_ads(max_wait=60)
    time.sleep(2)

    """Pasti ke akhir video dengan verifikasi"""

    print("\n⏩ Mencoba ke akhir video...")

    # Tunggu video benar-benar ready
    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.execute_script("""
                return document.readyState === 'complete' &&
                       document.querySelector('video') &&
                       document.querySelector('video').duration > 0;
            """)
        )
    except:
        print("  Video belum ready, lanjut anyway...")

    # Script SINGLE yang mencoba semua kemungkinan
    result = driver.execute_script("""
        try {
            // Coba cara 1: Video element langsung
            var videos = document.querySelectorAll('video');
            for (var i = 0; i < videos.length; i++) {
                if (videos[i].duration > 0) {
                    videos[i].currentTime = videos[i].duration - 0.5;
                    console.log('Set video[' + i + '] to ' + (videos[i].duration - 0.5));
                    return {success: true, method: 'video_element', time: videos[i].currentTime, duration: videos[i].duration};
                }
            }

            // Coba cara 2: YouTube player
            if (window.ytplayer && ytplayer.config && ytplayer.config.args) {
                var duration = ytplayer.config.args.length_seconds;
                var video = document.querySelector('video');
                if (video && duration) {
                    video.currentTime = duration - 0.5;
                    return {success: true, method: 'ytplayer_config', time: video.currentTime, duration: duration};
                }
            }

            // Coba cara 3: Movie player
            var moviePlayer = document.getElementById('movie_player');
            if (moviePlayer && typeof moviePlayer.seekTo === 'function') {
                var duration = moviePlayer.getDuration();
                if (duration) {
                    moviePlayer.seekTo(duration - 0.5, true);
                    return {success: true, method: 'movie_player', time: duration - 0.5, duration: duration};
                }
            }

            // Coba cara 4: Brute force
            var videoEl = document.querySelector('video');
            if (videoEl) {
                // Set ke waktu besar, biar browser handle
                videoEl.currentTime = 9999999;
                return {success: true, method: 'brute_force', time: 9999999, duration: videoEl.duration};
            }

            return {success: false, error: 'No video element found'};

        } catch (err) {
            return {success: false, error: err.toString()};
        }
    """)

    if result['success']:
        print(f"  ✅ BERHASIL ke akhir video!")
        print(f"     Method: {result.get('method', 'unknown')}")
        if 'time' in result and 'duration' in result:
            print(f"     Posisi: {result['time']:.1f} / {result['duration']:.1f} detik")
    else:
        print(f"  ❌ GAGAL: {result.get('error', 'Unknown error')}")

    time.sleep(3)  # Tunggu proses selesai

    try:
        subscribe_btn = driver.find_element(By.CSS_SELECTOR, 'ytd-subscribe-button-renderer button')
        btn_text = subscribe_btn.text.lower()
        if 'subscribe' in btn_text and 'subscribed' not in btn_text:
            driver.execute_script("arguments[0].click();", subscribe_btn)
            time.sleep(2)
            print("  - Subscribed!")
        else:
            print("  - Already subscribed")
    except:
        print("  - Subscribe button not found")

    try:
        like_btn = None
        try:
            like_btn = driver.find_element(By.CSS_SELECTOR, 'like-button-view-model button')
        except:
            pass

        if not like_btn:
            try:
                like_btn = driver.find_element(By.CSS_SELECTOR, '#segmented-like-button button')
            except:
                pass

        if not like_btn:
            try:
                like_btn = driver.find_element(By.CSS_SELECTOR, 'ytd-segmented-like-dislike-button-renderer button')
            except:
                pass

        if like_btn:
            aria_pressed = like_btn.get_attribute('aria-pressed')
            if aria_pressed == 'false':
                driver.execute_script("arguments[0].click();", like_btn)
                time.sleep(1)
                print("  - Liked!")
            else:
                print("  - Already liked")
        else:
            print("  - Like button not found")
    except Exception as e:
        print(f"  - Like error: {e}")


def take_screenshot(task_number):
    """Take full browser screenshot and return filepath"""
    filename = f"task_{task_number}.png"
    filepath = os.path.join(screenshot_dir, filename)
    driver.save_screenshot(filepath)
    print(f"  - Screenshot saved: {filepath}")
    return filepath

def upload_proof_and_submit(task_link, screenshot_path):
    """Upload screenshot proof to task detail page and submit"""
    driver.get(task_link)
    time.sleep(2)

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.prose')))
    time.sleep(1)

    file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"][accept="image/*"]')
    file_input.send_keys(screenshot_path)
    time.sleep(2)
    print(f"  - Uploaded: {screenshot_path}")

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1)

    try:
        # Click main submit button (outside dialog)
        submit_btn = driver.find_element(By.XPATH, "//button[text()='Submit' and not(ancestor::dialog)]")
        WebDriverWait(driver, 30).until(
            lambda d: submit_btn.get_attribute('disabled') is None
        )
        current_url = driver.current_url
        submit_btn.click()
        time.sleep(2)
        print("  - Clicked submit button")

        # Check if expired reason dialog appears
        try:
            dialog = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, 'upload_reason_modal'))
            )
            if dialog.is_displayed():
                print("  - Task expired dialog detected")

                # Fill textarea with reason
                reason_textarea = dialog.find_element(By.TAG_NAME, 'textarea')
                reason_textarea.clear()
                reason_textarea.send_keys("-")
                print("  - Filled expired reason")
                time.sleep(1)

                # Click Submit button inside the dialog
                dialog_submit_btn = dialog.find_element(By.XPATH, ".//button[text()='Submit']")
                dialog_submit_btn.click()
                print("  - Submitted expired reason")
                time.sleep(2)
        except TimeoutException:
            print("  - No expired dialog (submitted on time)")

        # Wait for URL change to confirm submission
        WebDriverWait(driver, 30).until(EC.url_changes(current_url))
        print(f"  - Submitted successfully!")
    except Exception as e:
        print(f"  - Submit error: {e}")

def send_telegram_album(task_data):
    """Kirim semua screenshot ke Telegram sebagai satu album"""
    print("\n[Telegram] Mengirim album screenshot...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    
    media = []
    files = {}
    
    for i, data in task_data.items():
        file_path = data['screenshot']
        file_name = os.path.basename(file_path)
        media.append({
            "type": "photo",
            "media": f"attach://{file_name}"
        })
        files[file_name] = open(file_path, 'rb')

    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "media": json.dumps(media)
        }
        res = requests.post(url, data=payload, files=files, timeout=60)
        res_json = res.json()
        if res_json.get("ok"):
            print("  - Berhasil mengirim foto.")
        else:
            print(f"  - Gagal kirim foto: {res_json}")
    except requests.exceptions.Timeout:
        print("  - Request Timeout (RTO) saat mengirim foto! Mungkin koneksi lambat.")
    except Exception as e:
        print(f"  - Error API Telegram: {e}")
    finally:
        for f in files.values():
            f.close()

def wait_for_telegram_confirmation(max_wait_seconds=300):
    """Kirim pesan validasi dan nge-block sampai di-klik pengguna atau timeout (via getUpdates)"""
    print(f"\n[Telegram] Menunggu konfirmasi Anda via tombol (Timeout: {max_wait_seconds}s)...")
    
    # 1. Kirim Pesan Validasi
    url_send = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Semua", "callback_data": "confirm"},
                {"text": "❌ Batal", "callback_data": "cancel"}
            ]
        ]
    }
    
    message_id = None
    try:
        req_msg = requests.post(url_send, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"Semua eksekusi sosial media selesai ✅\nSilakan cek foto di atas.\n\nLanjut Upload & Submit? (Timeout dlm {max_wait_seconds/60:.1f} mnt)",
            "reply_markup": keyboard
        }, timeout=20)
        message_id = req_msg.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"  - Error kirim tombol validasi: {e}")
        return False
        
    # 2. Polling menunggu CallbackQuery
    offset = None
    url_updates = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    
    start_time = time.time()
    last_print_time = start_time
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            print(f"\n[Telegram] Tidak ada respons dalam {max_wait_seconds} detik. Timeout (Batal otomatis).")
            if message_id:
                try:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText", 
                        json={
                            "chat_id": TELEGRAM_CHAT_ID, 
                            "message_id": message_id,
                            "text": "⏳ *WAKTU HABIS* - Tidak ada konfirmasi dari pengguna.\nStatus: ❌ **DIBATALKAN OTOMATIS**",
                            "parse_mode": "Markdown"
                        }, timeout=10)
                except: pass
            return False

        # Print progress tiap 60 detik biar tidak dikira stuck
        if time.time() - last_print_time > 60:
            print(f"  - Masih menunggu konfirmasi Telegram... (Sisa waktu: {int(max_wait_seconds - elapsed)}s)")
            last_print_time = time.time()

        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            
            # Timeout RTO python ditambahin supaya tidak freeze
            res = requests.get(url_updates, params=params, timeout=35)
            data = res.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    offset = update["update_id"] + 1
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data")
                        cb_id = cb.get("id")
                        
                        # Tutup status loading di aplikasi Telegram
                        try:
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": cb_id}, timeout=10)
                        except: pass
                        
                        if message_id:
                            status_text = "✅ **DIKONFIRMASI** - Memulai proses upload..." if cb_data == "confirm" else "❌ **DIBATALKAN**"
                            new_text = f"Semua eksekusi sosial media selesai ✅\n\nStatus: {status_text}"
                            
                            try:
                                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText", 
                                              json={
                                                  "chat_id": TELEGRAM_CHAT_ID, 
                                                  "message_id": message_id,
                                                  "text": new_text,
                                                  "parse_mode": "Markdown"
                                              }, timeout=10)
                            except: pass
                        
                        if cb_data == "confirm":
                            print("\n  - Respons Telegram: ✅ CONFIRM")
                            return True
                        elif cb_data == "cancel":
                            print("\n  - Respons Telegram: ❌ CANCEL")
                            return False
                            
            time.sleep(2) # Refresh polling
        except requests.exceptions.Timeout:
            # Hanya nge-print kalau dev butuh debug, atau abaikan untuk log bersih:
            # print("  - RTO polling Telegram (ini wajar), retrying...")
            pass
        except requests.exceptions.RequestException as e:
            print(f"  - Request error (RTO dll), retrying... {e}")
            time.sleep(5)
        except Exception as e:
            print(f"  - Error saat nge-pull chat: {e}")
            time.sleep(5)

def run_automation(chat_id):
    global driver, wait, screenshot_dir
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      json={"chat_id": chat_id, "text": "⏳ Memulai browser dan mengambil task..."})
        
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === Memulai Otomatisasi (Chat: {chat_id}) ===")
        init_driver()

        # ============ MAIN FLOW ============
        driver.get("https://admin.sistem-partisipasi.jovasoftware.id/dashboard")

        # ============ LOGIN / REDIRECT CHECK ============
        print("  - Memeriksa status login...")
        try:
            # Tunggu salah satu muncul: input email (blm login) atau table dashboard (sdh login)
            element = WebDriverWait(driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, 'input[type="email"]') or 
                         d.find_elements(By.CSS_SELECTOR, '.rdt_Table')
            )
            
            if driver.find_elements(By.CSS_SELECTOR, 'input[type="email"]'):
                print("  - Belum login, mencoba login...")
                email_input = driver.find_element(By.CSS_SELECTOR, 'input[type="email"]')
                email_input.send_keys(EMAIL)

                password_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
                password_input.send_keys(PASSWORD)

                submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                submit_button.click()

                wait.until(EC.url_changes(driver.current_url))
                print("  - Login berhasil!")
            else:
                print("  - Sudah dalam keadaan login (Dashboard).")
        except TimeoutException:
            print("  - Timeout saat menunggu halaman login/dashboard.")
            raise Exception("Halaman tidak merespon atau elemen tidak ditemukan.")

        # Tunggu .rdt_Table (wrapper), bukan .rdt_TableBody (isi)
        # Karena .rdt_TableBody tidak dirender jika data kosong
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.rdt_Table')))

        # Get all task detail links
        rows = driver.find_elements(By.CSS_SELECTOR, '.rdt_TableRow')
        task_links = []
        for row in rows:
            link = row.find_element(By.CSS_SELECTOR, '[data-column-id="8"] a').get_attribute('href')
            task_links.append(link)

        print(f"\nFound {len(task_links)} tasks to process\n")
        
        if not task_links:
             requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                          json={"chat_id": chat_id, "text": "✅ Tidak ada task yang ditemukan saat ini."})
             return

        task_data = {}

        for i, task_link in enumerate(task_links, 1):
            print(f"=== Processing Task {i} ===")

            try:
                driver.get(task_link)
                time.sleep(2)

                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.prose')))

                description_el = driver.find_element(By.CSS_SELECTOR, '.prose')
                urls = extract_urls_from_description(description_el)

                if not urls:
                    print(f"  No URLs found in task description")
                    continue
            except Exception as e:
                print(f"  ❌ Error loading task {i}: {type(e).__name__}: {str(e)[:100]}")
                print(f"  Skipping to next task...")
                continue

            print(f"  Found URLs: {urls}")

            for url in urls:
                platform = get_platform(url)
                print(f"  Platform: {platform}")

                try:
                    if platform == 'tiktok':
                        do_tiktok_task(url)
                    elif platform == 'instagram':
                        do_instagram_task(url)
                    elif platform == 'youtube':
                        do_youtube_task(url)
                    else:
                        print(f"  Unknown platform for URL: {url}")
                        print("Platform not social media, skipping...")
                        break

                    screenshot_path = take_screenshot(i)
                    task_data[i] = {'link': task_link, 'screenshot': screenshot_path}
                except Exception as e:
                    print(f"  ❌ Error processing task {i}: {type(e).__name__}: {str(e)[:100]}")
                    print(f"  Skipping to next task...")
                    continue

        print("\n=== Semua proses klik sosial media sudah selesai! ===")
        print(f"Screenshots disimpan di folder: {screenshot_dir}")

        # Kirim album ke telegram (jika ada file)
        if task_data:
            send_telegram_album(task_data)

            # Tunggu Validasi
            if wait_for_telegram_confirmation():
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                              json={"chat_id": chat_id, "text": "🚀 Memulai proses upload bukti screenshot..."})
                
                print("\n=== Mulai Mengunggah Bukti (Upload Proofs) ===")
                for task_num, data in task_data.items():
                    print(f"Upload untuk Task ke-{task_num}...")
                    upload_proof_and_submit(data['link'], data['screenshot'])
                print("\n=== Seluruh task sukses disubmit! ===")
                
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                              json={"chat_id": chat_id, "text": "🎉 Seluruh task sukses dikerjakan dan disubmit!"})
            else:
                print("\n=== Proses Dibatalkan oleh Anda ❌ ===")
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                              json={"chat_id": chat_id, "text": "❌ Proses dibatalkan oleh pengguna (Timeout/Batal)."})
        else:
            print("\nTidak ada task yang ditemukan/berhasil diproses.")

    except Exception as e:
        print(f"\n[CRITICAL] Error pada run_automation: {type(e).__name__}: {e}")
        # Bersihin lock files biar profile bisa dibuka manual next time
        if CHROME_PROFILE_PATH:
            for lock in ["SingletonLock", "SingletonSocket", "DevToolsActivePort"]:
                lp = os.path.join(CHROME_PROFILE_PATH, lock)
                if os.path.exists(lp):
                    try:
                        os.remove(lp)
                    except Exception:
                        pass
        
        err_msg = str(e)[:150]
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      json={"chat_id": chat_id, "text": f"❌ **CRITICAL ERROR**\nOtomatisasi berhenti.\n\nDetail: `{err_msg}`\n\nSilakan coba lagi /run beberapa saat lagi."})
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
            driver = None

def listen_telegram_command():
    print("🤖 Bot standby berjalan lokal... Menunggu perintah /run dari Telegram...")
    if not TELEGRAM_BOT_TOKEN:
        print("PERINGATAN: TELEGRAM_BOT_TOKEN tidak ditemukan di .env!")
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
                            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Menerima perintah /run dari chat_id: {chat_id}")
                            run_automation(chat_id)
            
            time.sleep(1)
        except requests.exceptions.Timeout:
            pass # Timeout wajar untuk long-polling
        except Exception as e:
            print(f"Error polling telegram: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Bersihin zombie Brave dari run sebelumnya — HANYA yg pake automation profile
    if CHROME_PROFILE_PATH:
        print("[Main] Membersihkan proses Brave zombie (automation profile)...")
        try:
            ps_cmd = 'Get-CimInstance Win32_Process -Filter "Name = \'brave.exe\'" | Select-Object ProcessId, CommandLine | ConvertTo-Json'
            result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
            if result.stdout.strip():
                data = json.loads(result.stdout)
                processes = data if isinstance(data, list) else [data]
                killed = 0
                for proc in processes:
                    cmd_line = proc.get('CommandLine', '') or ''
                    pid = proc.get('ProcessId')
                    if cmd_line and CHROME_PROFILE_PATH.lower() in cmd_line.lower():
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                        killed += 1
                if killed:
                    print(f"  - {killed} proses Brave zombie (automation profile) dibersihkan")
                else:
                    print("  - Tidak ada zombie")
        except Exception:
            pass
        # Bersihin lock files
        for lock in ["SingletonLock", "SingletonSocket", "DevToolsActivePort"]:
            lp = os.path.join(CHROME_PROFILE_PATH, lock)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                except Exception:
                    pass

    cleanup_other_main_instances()
    save_current_pid()
    print("\n[Main] Bot Listener Aktif...")
    listen_telegram_command()
