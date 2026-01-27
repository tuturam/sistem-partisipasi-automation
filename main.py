import os
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

load_dotenv()

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
CHROME_PROFILE_PATH = os.getenv('CHROME_PROFILE_PATH')

options = Options()
options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")

driver = webdriver.Chrome(options=options)
driver.set_window_size(1280, 800)

wait = WebDriverWait(driver, 15)

today = datetime.now().strftime("%Y-%m-%d")
screenshot_dir = os.path.join(os.path.dirname(__file__), today)
os.makedirs(screenshot_dir, exist_ok=True)

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

def do_tiktok_task(url):
    """Follow + Like on TikTok"""
    driver.get(url)
    time.sleep(3)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    time.sleep(2)

    try:
        captcha = driver.find_elements(By.ID, 'captcha-verify-container-main-page')
        if captcha:
            print("  - Captcha detected! Please solve it manually...")
            WebDriverWait(driver, 300).until(
                EC.invisibility_of_element_located((By.ID, 'captcha-verify-container-main-page'))
            )
            print("  - Captcha solved!")
            time.sleep(2)
    except:
        pass

    try:
        follow_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Follow')]")
        if follow_btn and 'Following' not in follow_btn.text:
            follow_btn.click()
            time.sleep(1)
            print("  - Followed!")
    except:
        print("  - Already following or follow button not found")

    try:
        like_btn = driver.find_element(By.CSS_SELECTOR, '[data-e2e="like-icon"]')
        like_btn.click()
        time.sleep(1)
        print("  - Liked!")
    except:
        print("  - Already liked or like button not found")

    time.sleep(2)

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
        follow_btns = driver.find_elements(By.XPATH, "//button[contains(text(), 'Follow')]")
        for btn in follow_btns:
            btn_text = btn.text.strip().lower()
            if btn_text == 'follow':
                btn.click()
                time.sleep(2)
                print("  - Followed!")
                break
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

def do_youtube_task(url):
    """Subscribe + Like + Watch on YouTube"""
    driver.get(url)
    time.sleep(5)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    time.sleep(5)

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

# ============ MAIN FLOW ============
driver.get("https://admin.sistem-partisipasi.jovasoftware.id/dashboard")

try:
    email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))
    email_input.send_keys(EMAIL)

    password_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
    password_input.send_keys(PASSWORD)

    submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
    submit_button.click()

    wait.until(EC.url_changes(driver.current_url))
    print("Login successful!")
except:
    print("Already logged in or login failed")

wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.rdt_TableBody')))

# Get all task detail links
rows = driver.find_elements(By.CSS_SELECTOR, '.rdt_TableRow')
task_links = []
for row in rows:
    link = row.find_element(By.CSS_SELECTOR, '[data-column-id="8"] a').get_attribute('href')
    task_links.append(link)

print(f"\nFound {len(task_links)} tasks to process\n")

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
                driver.get(url)
                time.sleep(3)

            screenshot_path = take_screenshot(i)
            task_data[i] = {'link': task_link, 'screenshot': screenshot_path}
        except Exception as e:
            print(f"  ❌ Error processing task {i}: {type(e).__name__}: {str(e)[:100]}")
            print(f"  Skipping to next task...")
            continue

print("\n=== All social media tasks completed! ===")
print(f"Screenshots saved to: {screenshot_dir}")
print(f"\nPlease check if all tasks are correct.")
input("Press Enter to upload proofs to each task...")

print("\n=== Uploading proofs ===")
for task_num, data in task_data.items():
    print(f"Uploading proof for Task {task_num}...")
    upload_proof_and_submit(data['link'], data['screenshot'])

print("\n=== All proofs uploaded and submitted! ===")
input("Press Enter to close the browser...")
driver.quit()
