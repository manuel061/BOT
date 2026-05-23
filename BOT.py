import telebot
import requests
import pandas as pd
import numpy as np
import time
import threading
import json
import os

TOKEN = "8822165462:AAHl6DjwPVZSE8G_MxghZF-x5gF1gQ6pAEg"
bot = telebot.TeleBot(TOKEN)
LOG_FILE = "/home/manuelstentella/operazioni_log.json"

# --- STATO ---
def salva_stato(s):
    with open(LOG_FILE, "w") as f: json.dump(s, f)

def get_stato():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f: return json.load(f)
    return {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}

# --- MOTORE ANALISI ---
def avvia_scansione(chat_id):
    bot.send_message(chat_id, "🔥 AVVIO SCANSIONE DEL MERCATO, A BREVE ARRIVERANNO LE OPERAZIONI...")
    while True:
        s = get_stato()
        if not s["ATTIVO"]: break
        
        try:
            # Analisi Semplificata per test
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={s['SIMBOLO'].split('-')[0]}&tsym=USD&limit=20"
            data = requests.get(url, timeout=5).json()
            df = pd.DataFrame(data["Data"]["Data"])
            p_reale = float(df['close'].iloc[-1])
            sma = float(df['close'].rolling(10).mean().iloc[-1])
            
            # Notifica solo se c'è variazione significativa (setup)
            if abs(p_reale - sma) > (sma * 0.0005):
                bot.send_message(chat_id, f"💎 *SETUP #{time.time()[-5:]}*\nAsset: {s['SIMBOLO']}\nPrezzo: {p_reale:.2f}\nDirezione: {'LONG' if p_reale > sma else 'SHORT'}", parse_mode="Markdown")
        except: pass
        time.sleep(60)

# --- COMANDI ---
@bot.message_handler(commands=['start', 'avvia'])
def start(m):
    bot.reply_to(m, "💰 Inserisci il Capitale:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    s = get_stato()
    if m.text.replace('.','',1).isdigit() and s.get("CAPITALE", 0) == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato(s)
        bot.reply_to(m, "📈 Inserisci Ticker (es: BTC-USD):")
    elif "-" in m.text:
        s["SIMBOLO"] = m.text.upper()
        s["ATTIVO"] = True
        salva_stato(s)
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
    elif m.text.lower() == "basta":
        s["ATTIVO"] = False
        salva_stato(s)
        bot.reply_to(m, "🛑 Bot fermato.")

print("Bot in attesa di comandi...")
bot.infinity_polling()