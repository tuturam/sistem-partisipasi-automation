# Partisipasi Automation (Headless + Telegram)

Semi-automated tool for completing social media tasks on the Partisipasi system with Telegram remote control.

## Requirements

- Python 3.x
- Brave Browser (Default path in script)
- Telegram Bot (for remote confirmation)

## Setup

1. **Install dependencies**:
   Menggunakan `uv` (rekomendasi):
   ```bash
   uv sync
   ```
   Atau pip biasa:
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables**:
   Copy `.env.example` ke `.env` dan isi datanya:
   ```bash
   EMAIL=your_email@example.com
   PASSWORD=your_password
   CHROME_PROFILE_PATH=C:\Users\YourName\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default
   
   # Telegram Setup
   TELEGRAM_BOT_TOKEN=123456789:ABCDEF...
   TELEGRAM_CHAT_ID=1234567890
   HEADLESS_MODE=True
   ```

3. **Telegram Bot Setup**:
   - Create bot via [@BotFather](https://t.me/botfather) untuk mendapatkan Token.
   - Dapatkan Chat ID Anda via [@userinfobot](https://t.me/userinfobot).
   - **Penting**: Chat bot Anda terlebih dahulu dan klik `/start`.

4. **Verify Connection**:
   Jalankan script pengetesan untuk memastikan bot sudah konfigurasi dengan benar:
   ```bash
   python test_telegram.py
   ```

## Usage

### Run Manual
```bash
python main.py
```

### Run via Task Scheduler (Background)
Agar script berjalan otomatis di background tanpa jendela hitam (CMD):
1.  Buka **Task Scheduler** di Windows.
2.  **Create Basic Task** -> Beri nama "partisipasi" -> Pilih Trigger (misal: Daily / At Logon).
3.  **Action**: Pilih **Start a program**.
4.  **Program/script**: Arahkan ke file `pythonw.exe` di dalam folder venv Anda:
    `C:\path\to\your\project\.venv\Scripts\pythonw.exe`
5.  **Add arguments**: Isi dengan `main.py`.
6.  **Start in (PROPER SETUP)**: Isi dengan folder project Anda (SANGAT PENTING agar file `.env` terbaca):
    `C:\path\to\your\project\`

> [!IMPORTANT]
> Jika kolom **Start in** tidak diisi, script akan gagal membaca Token Telegram dan bot tidak akan merespons.

## How It Works

### Phase 1: Automation (Headless)
1. Browser berjalan di background (tidak terlihat).
2. Login ke dashboard Partisipasi.
3. Melakukan tugas Like/Follow/Subscribe secara otomatis.
4. Mengambil screenshot bukti tiap tugas.

### Phase 2: Remote Verification (Telegram)
5. Script mengirimkan **Album Foto** berisi semua screenshot ke Telegram Anda.
6. Script mengirim tombol: `[ ✅ Confirm Semua ]` dan `[ ❌ Batal ]`.
7. Script akan "menunggu" sampai Anda menekan salah satu tombol di HP Anda.

### Phase 3: Submit (Automated)
8. Jika dikonfirmasi, browser akan lanjut mengunggah foto bukti ke website.
9. Data disubmit, dan browser ditutup otomatis.

## Notes

- Jika **TikTok Captcha** terdeteksi, script akan menunggu manual (disarankan matikan `HEADLESS_MODE` sementara jika ingin debug captcha).
- Menggunakan `pythonw.exe` akan menghilangkan jendela hitam CMD saat berjalan di background via Task Scheduler.
- Pastikan tidak ada jendela browser dengan profile yang sama yang sedang terbuka saat script berjalan.
