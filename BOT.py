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

LOG_FILE = "operazioni_log.json"

@app.route('/')
def home():
    return "Bot Trader Chirurgico BTC/XAU Attivo!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- GESTIONE STATO AVANZATA ---
def salva_stato(s):
    with open(LOG_FILE, "w") as f: 
        json.dump(s, f)

def get_stato():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: 
                return json.load(f)
        except: 
            pass
    return {
        "CAPITALE": 0.0, 
        "SIMBOLO": "", 
        "ATTIVO": False,
        "TRADE_APERTO": False,
        "DIREZIONE_TRADE": None,
        "PREZZO_INGRESSO_EUR": 0.0,
        "STOP_LOSS_EUR": 0.0,
        "TAKE_PROFIT_EUR": 0.0,
        "BREAK_EVEN_FATTO": False
    }

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

def ottieni_dati_mercato(simbolo):
    try:
        fsym = simbolo.split('-')[0].upper()
        tsym = simbolo.split('-')[1].upper()
        url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=100"
        res = requests.get(url, timeout=5).json()
        if res.get("Response") == "Success":
            return pd.DataFrame(res["Data"]["Data"])
    except Exception as e:
        print(f"Errore recupero dati per {simbolo}: {e}")
    return None

# --- MOTORE ANALISI ---
def avvia_scansione(chat_id):
    s = get_stato()
    bot.send_message(chat_id, "🎯 *MOTORE ULTRA-RAPIDO ATTIVATO...*", parse_mode="Markdown")
    ultimo_minuto_segnalato = -1
    
    while True:
        s = get_stato()
        if not s["ATTIVO"]: 
            break
        
        try:
            ora_attuale = datetime.now()
            minuto_attuale = ora_attuale.minute
            secondo_attuale = ora_attuale.second
            
            df_raw = ottieni_dati_mercato(s['SIMBOLO'])
            
            if df_raw is not None and not df_raw.empty:
                p_corrente = float(df_raw['close'].iloc[-1])
                p_chiusura_confermata = float(df_raw['close'].iloc[-2])
                
                # ==========================================
                # GESTIONE TRADE APERTO (BREAK EVEN)
                # ==========================================
                if s["TRADE_APERTO"]:
                    if s["DIREZIONE_TRADE"] == "BUY":
                        meta_strada = s["PREZZO_INGRESSO_EUR"] + ((s["TAKE_PROFIT_EUR"] - s["PREZZO_INGRESSO_EUR"]) * 0.5)
                        
                        if p_chiusura_confermata >= meta_strada and not s["BREAK_EVEN_FATTO"]:
                            s["STOP_LOSS_EUR"] = s["PREZZO_INGRESSO_EUR"]
                            s["BREAK_EVEN_FATTO"] = True
                            salva_stato(s)
                            bot.send_message(chat_id, "🛡️ *BREAK EVEN CONFERMATO*\nStop Loss spostato a ingresso.", parse_mode="Markdown")
                        
                        elif p_corrente >= s["TAKE_PROFIT_EUR"]:
                            bot.send_message(chat_id, "🎉 *TARGET COLPITO (TAKE PROFIT)!*", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                        elif p_corrente <= s["STOP_LOSS_EUR"]:
                            bot.send_message(chat_id, "🛑 *STOP LOSS COLPITO.*", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                            
                    elif s["DIREZIONE_TRADE"] == "SELL":
                        meta_strada = s["PREZZO_INGRESSO_EUR"] - ((s["PREZZO_INGRESSO_EUR"] - s["TAKE_PROFIT_EUR"]) * 0.5)
                        
                        if p_chiusura_confermata <= meta_strada and not s["BREAK_EVEN_FATTO"]:
                            s["STOP_LOSS_EUR"] = s["PREZZO_INGRESSO_EUR"]
                            s["BREAK_EVEN_FATTO"] = True
                            salva_stato(s)
                            bot.send_message(chat_id, "🛡️ *BREAK EVEN CONFERMATO*\nStop Loss spostato a ingresso.", parse_mode="Markdown")
                        
                        elif p_corrente <= s["TAKE_PROFIT_EUR"]:
                            bot.send_message(chat_id, "🎉 *TARGET COLPITO (TAKE PROFIT)!*", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                        elif p_corrente >= s["STOP_LOSS_EUR"]:
                            bot.send_message(chat_id, "🛑 *STOP LOSS COLPITO.*", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                
                # ==========================================
                # GENERAZIONE NUOVO SEGNALE
                # ==========================================
                if secondo_attuale <= 5 and minuto_attuale != ultimo_minuto_segnalato and not s["TRADE_APERTO"]:
                    df_ha = calcola_heikin_ashi(df_raw)
                    df_raw['atr'] = calcola_atr(df_raw, period=14)
                    df_raw['sma20'] = df_raw['close'].rolling(20).mean()
                    
                    p_chiusura = float(df_raw['close'].iloc[-1])
                    sma = float(df_raw['sma20'].iloc[-1])
                    atr = float(df_raw['atr'].iloc[-1])
                    
                    ha_open = float(df_ha['open'].iloc[-1])
                    ha_close = float(df_ha['close'].iloc[-1])
                    
                    direzione = None
                    if p_chiusura > sma and ha_close > ha_open:
                        direzione = "BUY"
                    elif p_chiusura < sma and ha_close < ha_open:
                        direzione = "SELL"
                    
                    if direzione:
                        distanza_sl = atr * 2
                        
                        if direzione == "BUY":
                            stop_loss = p_chiusura - distanza_sl if (distanza_sl < p_chiusura * 0.05) else p_chiusura * 0.98
                            take_profit = p_chiusura + (p_chiusura - stop_loss) * 1.5
                        else:
                            stop_loss = p_chiusura + distanza_sl if (distanza_sl < p_chiusura * 0.05) else p_chiusura * 1.02
                            take_profit = p_chiusura - (stop_loss - p_chiusura) * 1.5

                        rischio_monetario = s["CAPITALE"] * 0.02
                        ampiezza_stop_percentuale = abs(p_chiusura - stop_loss) / p_chiusura
                        
                        if ampiezza_stop_percentuale > 0:
                            posizione_valuta = rischio_monetario / ampiezza_stop_percentuale
                            lotti = posizione_valuta / p_chiusura
                        else:
                            lotti = 0.0
                        
                        p_entrata_clean = int(p_chiusura) if p_chiusura.is_integer() else round(p_chiusura, 2)
                        sl_clean = int(stop_loss) if stop_loss.is_integer() else round(stop_loss, 2)
                        tp_clean = int(take_profit) if take_profit.is_integer() else round(take_profit, 2)
                        
                        lotti_clean = round(lotti / 1000, 2) if round(lotti / 1000, 2) > 0.01 else 0.01

                        s["TRADE_APERTO"] = True
                        s["DIREZIONE_TRADE"] = direzione
                        s["PREZZO_INGRESSO_EUR"] = float(p_entrata_clean)
                        s["STOP_LOSS_EUR"] = float(sl_clean)
                        s["TAKE_PROFIT_EUR"] = float(tp_clean)
                        s["BREAK_EVEN_FATTO"] = False
                        salva_stato(s)
                        
                        valuta_simbolo = "$" if "USD" in s['SIMBOLO'] else "€"
                        messaggio_segnale = (
                            f"*{direzione}* {p_entrata_clean} {valuta_simbolo}\n"
                            f"{lotti_clean}\n"
                            f"{sl_clean} {valuta_simbolo}\n"
                            f"{tp_clean} {valuta_simbolo}"
                        )
                        bot.send_message(chat_id, messaggio_segnale, parse_mode="Markdown")
                        ultimo_minuto_segnalato = minuto_attuale
                        
        except Exception as e:
            print(f"Errore scansione: {e}")
            
        time.sleep(5)

# --- COMANDI TELEGRAM ---
@bot.message_handler(commands=['start', 'avvia'])
def start(m):
    if os.path.exists(LOG_FILE):
        try: os.remove(LOG_FILE)
        except: pass
        
    salva_stato({
        "CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False, 
        "TRADE_APERTO": False, "DIREZIONE_TRADE": None,
        "PREZZO_INGRESSO_EUR": 0.0, "STOP_LOSS_EUR": 0.0,
        "TAKE_PROFIT_EUR": 0.0, "BREAK_EVEN_FATTO": False
    })
    bot.reply_to(m, "💰 Ciao! Inserisci il Capitale per iniziare:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    s = get_stato()
    
    if m.text.lower() == "basta":
        s["ATTIVO"] = False
        s["TRADE_APERTO"] = False
        salva_stato(s)
        bot.reply_to(m, "🛑 Bot fermato e posizioni resettate.")
        return

    # Fase 1: Inserimento Capitale (accetta solo numeri puri)
    if m.text.replace('.','',1).isdigit() and s["CAPITALE"] == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato(s)
        bot.reply_to(m, "📈 Perfetto. Ora inserisci l'Asset / Ticker (es: XAU-USD oppure BTC-USD):")
        return
        
    # Fase 2: Inserimento Asset (Cerca la presenza obbligatoria del trattino)
    elif "-" in m.text and s["CAPITALE"] > 0 and not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper()
        s["ATTIVO"] = True
        salva_stato(s)
        bot.reply_to(m, f"🚀 Cacciatore attivato per l'asset {s['SIMBOLO']}.")
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
        return

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    try:
        bot.remove_webhook()
    except:
        pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)