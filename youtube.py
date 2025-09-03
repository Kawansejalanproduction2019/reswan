import googleapiclient.discovery
import json
import time
from threading import Thread
from flask import Flask, request, jsonify
from collections import deque
import random
import os
import re
import google.oauth2.credentials
import google.auth.transport.requests
import requests
import googleapiclient.errors

app = Flask(__name__)

# --- Inisialisasi Bot dan Data ---
try:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
except FileNotFoundError:
    print("Error: File 'config.json' tidak ditemukan.")
    os._exit(1)
except json.JSONDecodeError:
    print("Error: File 'config.json' tidak valid. Periksa format JSON.")
    os._exit(1)


api_keys = deque(config['youtube_api_keys'])
youtube_service = None
current_live_chat_id = None
is_monitoring = False
credentials = None

def load_data(filename):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        if filename == 'commands.json':
            return {}
        if filename == 'automessages.json':
            return {"messages": [], "interval_minutes": 10}
        return None

def save_data(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

# --- Fungsi Core Bot ---
def get_youtube_service():
    """
    Mengatur layanan YouTube dan mengelola otorisasi.
    Sekarang akan mencoba OAuth, jika gagal karena kuota, akan beralih ke API Key.
    """
    global youtube_service, credentials

    # Coba menggunakan OAuth credentials terlebih dahulu
    if os.path.exists("credentials.json"):
        try:
            credentials = google.oauth2.credentials.Credentials.from_authorized_user_file(
                "credentials.json", ["https://www.googleapis.com/auth/youtube.force-ssl"]
            )
            if credentials and credentials.expired and credentials.refresh_token:
                print("Token kedaluwarsa. Mencoba refresh...")
                credentials.refresh(google.auth.transport.requests.Request())
                print("Refresh token berhasil.")

            if not credentials or not credentials.valid:
                print("Kredensial tidak valid. Mungkin refresh token juga kedaluwarsa.")
                print("Silakan jalankan ulang 'oauth_flow.py' untuk mendapatkan token baru.")
                os._exit(1)

            youtube_service = googleapiclient.discovery.build(
                "youtube", "v3", credentials=credentials
            )
            print("Menggunakan layanan YouTube dengan otorisasi OAuth 2.0.")
            return youtube_service

        except Exception as e:
            error_text = str(e)
            if "quotaExceeded" in error_text:
                print("DETAIL ERROR: Kuota OAuth untuk operasi baca telah terlampaui.")
                print("Bot akan beralih ke API Key untuk sementara.")
                # Lanjutkan ke loop di bawah untuk mencoba API Key
            else:
                print(f"!! GAGAL MEMUAT KREDENSIAL OAUTH !!")
                print(f"Error: {e}")
                print(f"Pastikan file 'credentials.json' valid.")
                print(f"Bot akan berhenti.")
                os._exit(1)
    
    # Jika OAuth gagal karena kuota atau file tidak ada, coba API Keys
    while True:
        try:
            current_key = api_keys[0]
            youtube_service = googleapiclient.discovery.build("youtube", "v3", developerKey=current_key)
            youtube_service.channels().list(part="id", id="UC_x5XG1OV2P6uZZ5tdeowsg").execute()
            print(f"Menggunakan layanan YouTube dengan API Key: {current_key[-4:]} (read-only)")
            return youtube_service
        except Exception as e:
            print(f"Error dengan API Key {current_key[-4:]}: {e}")
            print("Mencoba API Key berikutnya...")
            api_keys.rotate(-1)
            if not api_keys:
                print("Semua API Key habis. Bot berhenti.")
                os._exit(1)
            time.sleep(1)

def send_chat_message(message_text):
    """Mengirim pesan ke live chat menggunakan OAuth secara manual."""
    global credentials, current_live_chat_id
    
    if not current_live_chat_id or not credentials:
        print("Bot tidak terhubung ke live chat atau tidak memiliki kredensial.")
        return False
        
    # Pastikan token tidak kedaluwarsa sebelum mengirim
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(google.auth.transport.requests.Request())
        
    url = "https://youtube.googleapis.com/youtube/v3/liveChat/messages?part=snippet"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json"
    }
    body = {
        "snippet": {
            "liveChatId": current_live_chat_id,
            "type": "textMessageEvent",
            "textMessageDetails": {
                "messageText": message_text
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        print(f"[BOT RESPONSE] Berhasil mengirim pesan: '{message_text}'")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Terjadi kesalahan saat mengirim pesan: {e}")
        try:
            error_details = e.response.json()
            if e.response.status_code == 403 and any(err['reason'] == 'quotaExceeded' for err in error_details.get('error', {}).get('errors', [])):
                print("DETAIL ERROR: Kuota untuk operasi tulis telah terlampaui.")
                print("Solusi: Tunggu hingga kuota direset (biasanya 24 jam) atau gunakan akun YouTube lain.")
            else:
                print(f"Detail error: {e.response.text}")
        except:
            pass
        return False
    except Exception as e:
        print(f"Terjadi kesalahan tak terduga: {e}")
        return False

def read_live_chat():
    global youtube_service, current_live_chat_id, is_monitoring
    
    if not youtube_service:
        youtube_service = get_youtube_service()
        if not youtube_service:
            return

    next_page_token = None
    
    print("Menunggu perintah untuk memulai pemantauan live chat...")
    while True:
        if not is_monitoring or not current_live_chat_id:
            time.sleep(5)
            continue
            
        try:
            request = youtube_service.liveChatMessages().list(
                liveChatId=current_live_chat_id,
                part="snippet",
                pageToken=next_page_token
            )
            response = request.execute()
            
            commands = load_data('commands.json')
            for item in response.get("items", []):
                message = item["snippet"]["displayMessage"].lower()
                
                for trigger, response_text in commands.items():
                    if f"!{trigger}" == message or trigger == message:
                        print(f"Trigger '{trigger}' terdeteksi!")
                        send_chat_message(response_text)
                        
            next_page_token = response.get("nextPageToken")
            time.sleep(response.get("pollingIntervalMillis", 1000) / 1000.0)

        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 403 and 'quotaExceeded' in str(e):
                print("Error kuota terdeteksi saat membaca chat. Beralih ke API Key berikutnya...")
                api_keys.rotate(-1) # Pindah ke key berikutnya
                youtube_service = get_youtube_service() # Dapatkan layanan dengan key baru
            else:
                print(f"Terjadi kesalahan saat membaca chat: {e}")
                is_monitoring = False
                current_live_chat_id = None
                youtube_service = get_youtube_service()
                if not youtube_service:
                    break
                time.sleep(5)
        except Exception as e:
            print(f"Terjadi kesalahan saat membaca chat: {e}")
            is_monitoring = False
            current_live_chat_id = None
            youtube_service = get_youtube_service()
            if not youtube_service:
                break
            time.sleep(5)

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    global current_live_chat_id, is_monitoring, youtube_service
    data = request.json
    live_url = data.get('url')
    
    if not live_url:
        return jsonify({"success": False, "message": "URL tidak boleh kosong."}), 400

    video_id_match = re.search(r'(?<=v=)[a-zA-Z0-9_-]{11}', live_url)
    if not video_id_match:
        return jsonify({"success": False, "message": "URL live stream tidak valid."}), 400
    video_id = video_id_match.group(0)

    for i in range(len(api_keys)):
        try:
            if not youtube_service:
                youtube_service = get_youtube_service()
                if not youtube_service:
                    return jsonify({"success": False, "message": "Gagal mendapatkan layanan YouTube."}), 500

            broadcasts = youtube_service.liveBroadcasts().list(
                part="snippet",
                id=video_id
            ).execute()

            if broadcasts['items'] and broadcasts['items'][0]['snippet']['liveChatId']:
                current_live_chat_id = broadcasts['items'][0]['snippet']['liveChatId']
                is_monitoring = True
                return jsonify({"success": True, "message": f"Bot berhasil terhubung ke live chat: {live_url}"})
            else:
                is_monitoring = False
                return jsonify({"success": False, "message": "URL bukan live stream yang aktif."}), 400
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 403 and 'quotaExceeded' in str(e):
                print("Error kuota terdeteksi saat memulai pemantauan. Beralih ke API Key berikutnya...")
                api_keys.rotate(-1)
                youtube_service = get_youtube_service()
                return jsonify({"success": False, "message": "Error kuota. Mencoba API Key berikutnya. Silakan coba lagi."}), 500
            else:
                is_monitoring = False
                return jsonify({"success": False, "message": f"Terjadi kesalahan: {e}"}), 500
        except Exception as e:
            is_monitoring = False
            return jsonify({"success": False, "message": f"Terjadi kesalahan: {e}"}), 500

    is_monitoring = False
    return jsonify({"success": False, "message": "Semua API Key kehabisan kuota."}), 500

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global is_monitoring, current_live_chat_id
    if is_monitoring:
        is_monitoring = False
        current_live_chat_id = None
        return jsonify({"success": True, "message": "Bot berhasil dihentikan."})
    else:
        return jsonify({"success": True, "message": "Bot tidak sedang memantau live stream."})

@app.route('/add_command', methods=['POST'])
def add_command():
    data = request.json
    trigger = data.get('trigger', '').lower()
    response_text = data.get('response')
    
    if not trigger or not response_text:
        return jsonify({"success": False, "message": "Trigger dan response tidak boleh kosong."}), 400

    commands = load_data('commands.json')
    commands[trigger] = response_text
    save_data(commands, 'commands.json')
    
    return jsonify({"success": True, "message": f"Command '{trigger}' berhasil ditambahkan."})

@app.route('/add_automessage', methods=['POST'])
def add_automessage():
    data = request.json
    message = data.get('message')
    
    if not message:
        return jsonify({"success": False, "message": "Pesan tidak boleh kosong."}), 400

    auto_messages_data = load_data('automessages.json')
    auto_messages_data['messages'].append(message)
    save_data(auto_messages_data, 'automessages.json')
    
    return jsonify({"success": True, "message": "Pesan otomatis berhasil ditambahkan."})

@app.route('/update_interval', methods=['POST'])
def update_interval():
    data = request.json
    interval = data.get('interval')
    
    if not isinstance(interval, int) or interval <= 0:
        return jsonify({"success": False, "message": "Interval harus angka positif."}), 400

    auto_messages_data = load_data('automessages.json')
    auto_messages_data['interval_minutes'] = interval
    save_data(auto_messages_data, 'automessages.json')

    return jsonify({"success": True, "message": f"Interval pesan otomatis diperbarui menjadi {interval} menit."})

if __name__ == "__main__":
    api_thread = Thread(target=app.run, kwargs={'port': config['port'], 'host': '0.0.0.0'})
    api_thread.daemon = True
    api_thread.start()

    chat_thread = Thread(target=read_live_chat)
    chat_thread.daemon = True
    chat_thread.start()

    auto_message_thread = Thread(target=send_auto_messages)
    auto_message_thread.daemon = True
    auto_message_thread.start()

    print("Bot YouTube sedang berjalan dan siap menerima perintah. Tekan Ctrl+C untuk keluar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Bot YouTube berhenti.")
