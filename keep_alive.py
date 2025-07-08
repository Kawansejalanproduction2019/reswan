from flask import Flask, jsonify
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!", 200

@app.route('/ping')
def ping():
    return "Pong! Bot is running!", 200

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "online"}), 200

@app.route('/status')
def status():
    return jsonify({"message": "Discord bot is running", "code": 200}), 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
