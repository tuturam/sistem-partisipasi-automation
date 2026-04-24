import os
import requests
import json
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def test_telegram():
    if not TOKEN or not CHAT_ID:
        print("\n❌ ERROR: TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diisi di file .env")
        return

    print(f"--- Telegram Connection Test ---")
    print(f"Token: {TOKEN[:10]}... (hidden)")
    print(f"Chat ID: {CHAT_ID}")
    
    url_send = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    url_updates = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    
    # 1. Test Send Message
    print("\n1. Mengirim pesan tes ke HP Anda...")
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Koneksi Berhasil", "callback_data": "test_ok"},
                {"text": "❌ Batalkan Tes", "callback_data": "test_fail"}
            ]
        ]
    }
    
    try:
        payload = {
            "chat_id": CHAT_ID,
            "text": "🤖 *TEST CONNECTION*\n\nJika Anda menerima pesan ini, konfigurasi Token & Chat ID sudah benar.\n\nSilakan klik tombol di bawah untuk verifikasi balasan (bi-directional):",
            "parse_mode": "Markdown",
            "reply_markup": keyboard
        }
        res = requests.post(url_send, json=payload)
        res_data = res.json()
        
        if not res_data.get("ok"):
            print(f"❌ GAGAL mengirim pesan: {res_data.get('description')}")
            return
        
        message_id = res_data.get("result", {}).get("message_id")
        print("✅ Pesan terkirim!")
        
    except Exception as e:
        print(f"❌ ERROR: Terjadi kendala jaringan: {e}")
        return

    # 2. Test Polling (Receive Button Click)
    print("\n2. Menunggu Anda menekan tombol di Telegram (Timeout 60 detik)...")
    start_time = time.time()
    offset = None
    
    while time.time() - start_time < 60:
        try:
            params = {"timeout": 10}
            if offset:
                params["offset"] = offset
            
            res = requests.get(url_updates, params=params)
            updates = res.json()
            
            if updates.get("ok") and updates.get("result"):
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data")
                        
                        # Answer callback to stop loading icon
                        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": cb.get("id")})
                        
                        # Update status pesan (Visual feedback)
                        res_status = "✅ **KONEKSI BERHASIL**" if cb_data == "test_ok" else "⚠️ **TES DIBATALKAN**"
                        requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                      json={
                                          "chat_id": CHAT_ID, 
                                          "message_id": message_id,
                                          "text": f"🤖 *TEST CONNECTION*\n\nStatus: {res_status}",
                                          "parse_mode": "Markdown"
                                      })

                        if cb_data == "test_ok":
                            print("\n✨ BERHASIL TOTAL! ✨")
                            print("Bot bisa mengirim pesan DAN menerima input dari Anda.")
                            print("Sekarang Anda bisa menjalankan main.py dengan aman.")
                        else:
                            print("\n⚠️ TES DIBATALKAN.")
                            print("Bot bisa kirim pesan, tapi Anda menekan tombol 'Batal'.")
                        return

            time.sleep(1)
        except KeyboardInterrupt:
            print("\nTes dihentikan manual.")
            return
        except Exception as e:
            print(f"Sedang mencoba ulang... ({e})")
            time.sleep(2)

    print("\n⏰ TIMEOUT: Anda tidak menekan tombol dalam 60 detik.")
    print("Kirim pesan awal berhasil, tapi verifikasi balik (polling) gagal/timeout.")

if __name__ == "__main__":
    test_telegram()
