import telebot
import requests
import pandas as pd
import numpy as np
import time
import threading
import json
import os
from datetime import datetime
from flask import Flask

TOKEN = "8822165462:AAHl6DjwPVZSE8G_MxghZF-x5gF1gQ6pAEg"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONFIGURAZIONE AMICI ---
# Aggiungi qui gli ID dei tuoi amici che possono usare il bot
ID_AUTORIZZATI = [123456789, 987654321] 

LOG_FILE = "operazioni_log.json"

@app.route('/')
def home():
    return "Bot Trader Privato Attivo!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- GESTIONE STATO MULTI-UTENTE ---
def get_stato_utente(user_id):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: 
                data = json.load(f)
                return data.get(str(user_id), {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False})
        except: pass
    return {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}

def salva_stato_utente(user_id, s):
    stati = {}
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: stati = json.load(f)
        except: pass
    stati[str(user_id)] = s
    with open(LOG_FILE, "w") as f: json.dump(stati, f)

# --- MOTORE ANALISI ---
def avvia_scansione(chat_id):
    bot.send_message(chat_id, "🚀 *Motore privato attivato!*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(chat_id)
        if not s["ATTIVO"]: break
        
        try:
            # Qui il tuo motore di analisi (es. richiesta dati API)
            time.sleep(10)
        except: break

# --- COMANDI ---
@bot.message_handler(commands=['start'])
def start(m):
    # Controllo se l'utente è autorizzato
    if m.chat.id not in ID_AUTORIZZATI:
        bot.reply_to(m, "🚫 Accesso non autorizzato.")
        return
        
    salva_stato_utente(m.chat.id, {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False})
    bot.reply_to(m, "💰 Inserisci Capitale:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    
    s = get_stato_utente(m.chat.id)
    if m.text.lower() == "basta":
        s["ATTIVO"] = False
        salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "🛑 Bot fermato.")
    elif s["CAPITALE"] == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "📈 Inserisci Asset (es: BTC-USD):")
    elif not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper()
        s["ATTIVO"] = True
        salva_stato_utente(m.chat.id, s)
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling()