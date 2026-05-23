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

# --- FUNZIONI TECNICHE DEL TRADER PERFETTO ---
def calcola_heikin_ashi(df):
    ha_df = pd.DataFrame(index=df.index, columns=['open', 'high', 'low', 'close'])
    ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_df.iloc[0, ha_df.columns.get_loc('open')] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('open')] = (ha_df['open'].iloc[i-1] + ha_df['close'].iloc[i-1]) / 2
    ha_df['high'] = df[['high', 'open', 'close']].max(axis=1)
    ha_df['low'] = df[['low', 'open', 'close']].min(axis=1)
    return ha_df

def calcola_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()

def ottieni_cambio_eur():
    """Recupera il tasso di cambio attuale USD -> EUR"""
    try:
        url = "https://min-api.cryptocompare.com/data/price?fsym=USD&tsyms=EUR"
        res = requests.get(url, timeout=5).json()
        return float(res.get("EUR", 0.92))
    except:
        return 0.92

# --- MOTORE ANALISI ---
def avvia_scansione(chat_id):
    bot.send_message(chat_id, "🎯 *MOTORE OPERATIVO AVVIATO...*", parse_mode="Markdown")
    
    while True:
        s = get_stato()
        if not s["ATTIVO"]: 
            break
        try:
            sym = s['SIMBOLO'].split('-')[0]
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={sym}&tsym=USD&limit=100"
            response = requests.get(url, timeout=10).json()
            
            if response.get("Response") == "Success":
                df_raw = pd.DataFrame(response["Data"]["Data"])
                
                # Calcolo indicatori matematici (base USD)
                df_ha = calcola_heikin_ashi(df_raw)
                df_raw['atr'] = calcola_atr(df_raw, period=14)
                df_raw['sma20'] = df_raw['close'].rolling(20).mean()
                
                p_chiusura_usd = float(df_raw['close'].iloc[-1])
                sma_usd = float(df_raw['sma20'].iloc[-1])
                atr_usd = float(df_raw['atr'].iloc[-1])
                
                ha_open = float(df_ha['open'].iloc[-1])
                ha_close = float(df_ha['close'].iloc[-1])
                
                # Definizione segnale BUY o SELL
                direzione = None
                if p_chiusura_usd > sma_usd and ha_close > ha_open:
                    direzione = "BUY"
                elif p_chiusura_usd < sma_usd and ha_close < ha_open:
                    direzione = "SELL"
                
                if direzione:
                    # Cambio valuta dinamico per mostrare tutto in €
                    usd_to_eur = ottieni_cambio_eur()
                    p_chiusura_eur = p_chiusura_usd * usd_to_eur
                    atr_eur = atr_usd * usd_to_eur
                    
                    distanza_sl = atr_eur * 2
                    
                    # Calcolo Stop Loss e Take Profit (Risk/Reward 1:1.5)
                    if direzione == "BUY":
                        stop_loss = p_chiusura_eur - distanza_sl if (distanza_sl < p_chiusura_eur * 0.05) else p_chiusura_eur * 0.98
                        take_profit = p_chiusura_eur + (p_chiusura_eur - stop_loss) * 1.5
                    else:
                        stop_loss = p_chiusura_eur + distanza_sl if (distanza_sl < p_chiusura_eur * 0.05) else p_chiusura_eur * 1.02
                        take_profit = p_chiusura_eur - (stop_loss - p_chiusura_eur) * 1.5

                    # Money Management perfetto (Rischio fisso del 2% del Capitale in EUR)
                    rischio_monetario = s["CAPITALE"] * 0.02
                    ampiezza_stop_percentuale = abs(p_chiusura_eur - stop_loss) / p_chiusura_eur
                    
                    if ampiezza_stop_percentuale > 0:
                        posizione_euro = rischio_monetario / ampiezza_stop_percentuale
                        lotti = posizione_euro / p_chiusura_eur
                        guadagno_stimato = rischio_monetario * 1.5
                    else:
                        lotti = 0.0
                        guadagno_stimato = 0.0
                    
                    # Analisi tempistica del minutaggio candela
                    secondi_attuali = datetime.now().second
                    if secondi_attuali <= 5:
                        tempistica = "ENTRA SUBITO"
                    else:
                        secondi_mancanti = 60 - secondi_attuali
                        tempistica = f"ATTENDI {secondi_mancanti}s per conferma"
                    
                    # MESSAGGIO RICHIESTO: DIREZIONE PRIMA DEI LOTTI + COMPATTO IN EURO
                    messaggio_segnale = (
                        f"🚨 *SEGNALE DI TRADING* | {sym}-EUR\n"
                        f"🟢 *OPERAZIONE:* {direzione}\n"
                        f"🪙 *Lotti (Size):* {lotti:.5f} {sym}\n\n"
                        f"⏱️ *Tempistica:* {tempistica}\n"
                        f"💶 *Prezzo Entrata:* {p_chiusura_eur:.2f} €\n"
                        f"🛑 *Stop Loss:* {stop_loss:.2f} €\n"
                        f"🎯 *Take Profit:* {take_profit:.2f} €\n\n"
                        f"💰 *Guadagno Stimato:* +{guadagno_stimato:.2f} €"
                    )
                    bot.send_message(chat_id, messaggio_segnale, parse_mode="Markdown")
                    
        except Exception as e:
            print(f"Errore scansione: {e}")
            
        time.sleep(60)

# --- COMANDI TELEGRAM ---
@bot.message_handler(commands=['start', 'avvia'])
def start(m):
    # Reset dello stato al comando start
    salva_stato({"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False})
    bot.reply_to(m, "💰 Ciao! Inserisci il Capitale in Euro per iniziare:")

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
        bot.reply_to(m, f"🚀 Cacciatore attivato su {s['SIMBOLO']}! Calcoli convertiti in EUR.")
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
    elif m.text.lower() == "basta":
        s["ATTIVO"] = False
        salva_stato(s)
        bot.reply_to(m, "🛑 Bot fermato.")

if __name__ == "__main__":
    # Avvia il server web in background per Render
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Rimuove il vecchio webhook per risolvere il conflitto 409
    try:
        bot.remove_webhook()
        print("Vecchio Webhook rimosso con successo.")
    except Exception as e:
        print(f"Errore durante la rimozione del webhook: {e}")
    
    # Avvia il bot di Telegram
    print("Bot in ascolto...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)