# Partisipasi Automation

Semi-automated tool for completing social media tasks on the Partisipasi system.

## Requirements

- Python 3.x
- Google Chrome browser

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:
   ```
   cp .env.example .env
   ```

3. Edit `.env` with your details:
   ```
   EMAIL=your_email@example.com
   PASSWORD=your_password
   CHROME_PROFILE_PATH=C:\Users\YourName\AppData\Local\Google\Chrome\AutomationProfile
   ```

4. Create a separate Chrome profile for automation:
   - Run Chrome once with the profile path to set up cookies/logins example : `"C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\Users\Cendy\AppData\Local\Google\Chrome\AutomationProfile"`

5. Log in to your social media accounts (TikTok, Instagram, YouTube) in the automation profile

## Usage

```
python main.py
```

## How It Works

### Phase 1: Social Media Tasks (Automated)
1. Logs in to the Partisipasi dashboard
2. Collects all pending tasks
3. For each task:
   - Extracts social media URLs from description
   - Navigates to each URL
   - Performs Follow/Like/Subscribe actions
   - Takes a screenshot

### Phase 2: Manual Verification (Semi-Automated)
4. Pauses and asks you to verify screenshots are correct
5. Press Enter to continue

### Phase 3: Upload & Submit (Automated)
6. Goes back to each task detail page
7. Uploads the screenshot as proof
8. Clicks Submit button
9. Waits for redirect before moving to next task

## Manual Intervention Required

- **TikTok Captcha**: If a captcha appears, solve it manually. The script waits up to 5 minutes.
- **Verification Pause**: Review screenshots before uploading to ensure tasks were completed correctly.

## Supported Platforms

- TikTok (Follow + Like)
- Instagram (Follow + Like)
- YouTube (Subscribe + Like)

## Notes

- Screenshots are saved to a folder named with today's date (e.g., `2026-01-21/`)
- Each screenshot is named `task_N.png` where N is the task number
- Close other Chrome windows before running to avoid profile conflicts
