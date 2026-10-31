# Partisipasi Automation (Headless + Telegram)

Semi-automated tool for completing social media tasks on the Partisipasi system with Telegram remote control.

## n8n Docker Stack (branch: `n8n`)

Branch ini juga menjalankan instance n8n lengkap dengan Chromium, task runner, code sandbox, dan SearXNG untuk assistant.

### Service yang berjalan

| Service | Fungsi | Port host |
|---|---|---|
| `n8n` | UI n8n + Chromium untuk node Puppeteer | `5680` |
| `runners` | Eksekusi Code node di container terpisah | internal |
| `searxng` | Web search assistant | internal |
| `sandbox-certs` | Generate sertifikat mTLS sekali jalan | - |
| `sandbox-api` | API code sandbox | internal |
| `sandbox-runner-1` | Menjalankan sandbox container (privileged) | internal |

Hanya port n8n yang di-publish. Service lain hanya bisa diakses dari network Compose.

### Fresh install

Prasyarat: Docker Desktop + Docker Compose v2.

**1. Generate `.env`**

Jalankan dari root repo (PowerShell):

```powershell
$envFile = Join-Path $PWD '.env'
if (-not (Test-Path $envFile)) { Copy-Item '.env.example' $envFile }

function New-Hex([int]$n) {
  $b = New-Object byte[] $n
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  ($b | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Set-EnvDefault([string]$key, [string]$value) {
  if (-not (Select-String -Path $envFile -Pattern "^$([regex]::Escape($key))=" -Quiet)) {
    Add-Content -Path $envFile -Value "$key=$value"
  }
}

$runner    = New-Hex 24
$sandbox   = New-Hex 24
$reg       = New-Hex 24
$runnerApi = New-Hex 24
$searx     = New-Hex 32

Set-EnvDefault 'N8N_VERSION' '2.41.6'
Set-EnvDefault 'N8N_SANDBOX_VERSION' '1.3.4'
Set-EnvDefault 'N8N_RUNNERS_MODE' 'external'
Set-EnvDefault 'N8N_RUNNERS_BROKER_LISTEN_ADDRESS' '0.0.0.0'
Set-EnvDefault 'N8N_RUNNERS_AUTH_TOKEN' $runner
Set-EnvDefault 'N8N_UNVERIFIED_PACKAGES_ENABLED' 'true'
Set-EnvDefault 'INSTANCE_AI_BRAVE_SEARCH_API_KEY' ''
Set-EnvDefault 'N8N_INSTANCE_AI_SEARXNG_URL' 'http://searxng:8080'
Set-EnvDefault 'SEARXNG_SECRET' $searx
Set-EnvDefault 'N8N_INSTANCE_AI_SANDBOX_ENABLED' 'true'
Set-EnvDefault 'N8N_INSTANCE_AI_SANDBOX_PROVIDER' 'n8n-sandbox'
Set-EnvDefault 'N8N_INSTANCE_AI_SANDBOX_API_URL' 'http://sandbox-api:8080'
Set-EnvDefault 'N8N_SANDBOX_SERVICE_URL' 'http://sandbox-api:8080'
Set-EnvDefault 'SANDBOX_API_KEYS' $sandbox
Set-EnvDefault 'N8N_SANDBOX_SERVICE_API_KEY' $sandbox
Set-EnvDefault 'SANDBOX_API_RUNNER_REGISTRATION_TOKEN' $reg
Set-EnvDefault 'SANDBOX_RUNNER_REGISTRATION_TOKEN' $reg
Set-EnvDefault 'SANDBOX_API_RUNNER_API_KEY' $runnerApi
Set-EnvDefault 'SANDBOX_RUNNER_API_KEYS' $runnerApi
```

Script ini:

- Copy `.env.example` ke `.env` kalau `.env` belum ada
- Generate secret n8n kalau key-nya belum ada
- **Tidak menimpa** nilai yang sudah ada
- Bisa dijalankan berulang kali dengan aman

**2. Kredensial Python bot**

Isi bagian ini di `.env` kalau ingin bot Python juga dipakai:

```dotenv
EMAIL=your_email@example.com
PASSWORD=your_password
CHROME_PROFILE_PATH=C:\path\to\browser\profile
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
HEADLESS_MODE=True
```

Stack n8n tidak membutuhkan nilai ini.

**3. Jalankan**

```powershell
docker compose up -d
```

Buka `http://localhost:5680`, lalu buat akun owner.

**4. Assistant**

Sandbox dan web search otomatis aktif dari env. Yang tetap manual:

- Pilih model + credential AI di Settings → Instance AI
- Isi `INSTANCE_AI_BRAVE_SEARCH_API_KEY` kalau ingin web search lewat Brave, bukan SearXNG

### Env: otomatis vs manual

| Env | Sumber |
|---|---|
| `N8N_RUNNERS_AUTH_TOKEN` | generate script |
| `SANDBOX_API_KEYS` + `N8N_SANDBOX_SERVICE_API_KEY` | generate script, nilainya harus sama |
| `SANDBOX_API_RUNNER_REGISTRATION_TOKEN` + `SANDBOX_RUNNER_REGISTRATION_TOKEN` | generate script, nilainya harus sama |
| `SANDBOX_API_RUNNER_API_KEY` + `SANDBOX_RUNNER_API_KEYS` | generate script, nilainya harus sama |
| `SEARXNG_SECRET` | generate script |
| `EMAIL`, `PASSWORD`, `TELEGRAM_*` | manual (Python bot) |
| Model AI, akun owner | manual di UI n8n |

Semua secret di atas **per instalasi**. Jangan commit `.env` — sudah masuk `.gitignore`.

### Kalau diakses lewat reverse proxy / ngrok

Tambahkan ke `.env`:

```dotenv
N8N_PROXY_HOPS=1
```

Lalu sesuaikan `N8N_WEBHOOK_URL` di `compose.yaml` dengan URL publik kamu, atau hapus baris itu kalau tidak memakai webhook.

### Command harian

```powershell
docker compose up -d          # start
docker compose stop           # stop tanpa hapus container
docker compose down           # hapus container, volume tetap
docker compose logs -f n8n    # lihat log n8n
docker compose up -d --build  # rebuild setelah Dockerfile berubah
```

### Fresh volume

Community node `n8n-nodes-puppeteer` dan `n8n-nodes-browseract` sudah di-bake ke image. Saat volume kosong dibuat, Docker menyalin directory `/home/node/.n8n` dari image ke volume, jadi node langsung tersedia.

```powershell
docker compose down -v   # hapus semua data n8n
docker compose up -d     # volume baru, data table & workflow kosong lagi
```

Catatan:

- Data table **tidak** dibuat otomatis oleh container. Workflow yang memakai Data Table harus punya node `Table → Create` dengan opsi **Reuse Existing Tables**, atau tabel dibuat sekali lewat UI.
- `docker compose down -v` menghapus workflow, credential, data table, dan riwayat eksekusi.

### Troubleshooting

| Gejala | Penyebab / solusi |
|---|---|
| `pull ... 429 Too Many Requests` | Rate limit registry. Tunggu, `docker login`, atau pakai base `docker.io/n8nio/n8n` |
| `X-Forwarded-For ... trust proxy false` | Set `N8N_PROXY_HOPS=1` |
| `Unrecognized node type: n8n-nodes-puppeteer.puppeteer` | Volume belum punya community node. Rebuild image + volume baru, atau install via Settings → Community Nodes |
| Hasil web search kosong | Engine SearXNG kena rate limit/CAPTCHA. Isi Brave Search API key |
| `sandbox-runner` gagal cleanup saat stop | Normal, terjadi saat shutdown |
| `User attempted to access a workflow without permissions` | Buka/import ulang workflow sebagai owner project |

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
