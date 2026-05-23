import telebot
import requests
import pandas as pd
import numpy as np
import time
import threading
import json
import os
from flask import Flask

TOKEN = "8822165462:AAHl6DjwPVZSE8G_MxghZF-x5gF1gQ6pAEg"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Il file di log ora si salva nella cartella corrente di Render
LOG_FILE = "operazioni_log.json"

# --- SERVER WEB PER RENDERE LIVE IL BOT ---
@app.route('/')
def home():
    return "Bot Trading Online!", 200

def run_flask():
    # Render assegna la porta automaticamente tramite la variabile PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- GESTIONE STATO ---
def salva_stato(s):
    with open(LOG_FILE, "w") as f: 
        json.dump(s, f)

def get_stato():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: return json.load(f)
        except: pass
    return {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}

# --- MOTORE ANALISI ---
def avvia_scansione(chat_id):
    bot.send_message(chat_id, "🔥 AVVIO SCANSIONE DEL MERCATO...")
    while True:
        s = get_stato()
        if not s["ATTIVO"]: 
            break
        try:
            sym = s['SIMBOLO'].split('-')[0]
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={sym}&tsym=USD&limit=20"
            data = requests.get(url, timeout=5).json()
            df = pd.DataFrame(data["Data"]["Data"])
            p_reale = float(df['close'].iloc[-1])
            sma = float(df['close'].rolling(10).mean().iloc[-1])
            
            if abs(p_reale - sma) > (sma * 0.0005):
                bot.send_message(chat_id, f"💎 *SETUP DETECTED*\nAsset: {s['SIMBOLO']}\nPrezzo: {p_reale:.2f}\nDirezione: {'LONG' if p_reale > sma else 'SHORT'}", parse_mode="Markdown")
        except Exception as e:
            print(f"Errore scansione: {e}")
        time.sleep(60)

# --- COMANDI TELEGRAM ---
@bot.message_handler(commands=['start', 'avvia'])
def start(m):
    # Reset dello stato al comando start
    salva_stato({"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False})
    bot.reply_to(m, "💰 Ciao! Inserisci il Capitale per iniziare:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    s = get_stato()
    # Se l'utente inserisce un numero ed è la prima fase
    if m.text.replace('.','',1).isdigit() and s["CAPITALE"] == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato(s)
        bot.reply_to(m, "📈 Perfetto. Ora inserisci il Ticker (es: BTC-USD):")
    # Se l'utente inserisce il ticker con il trattino
    elif "-" in m.text and s["CAPITALE"] > 0 and not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper()
        s["ATTIVO"] = True
        salva_stato(s)
        bot.reply_to(m, f"🚀 Cacciatore attivato su {s['SIMBOLO']}!")
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
    elif m.text.lower() == "basta":
        s["ATTIVO"] = False
        salva_stato(s)
        bot.reply_to(m, "🛑 Bot fermato.")

if __name__ == "__main__":
    # Avvia il server web in background per Render
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Avvia il bot di Telegram
    print("Bot in ascolto...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)