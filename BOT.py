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
    return "Bot Trader Perfetto con Scelta Server Attivo!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- GESTIONE STATO AVANZATA (CON LOG DI TRADE E SERVER) ---
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
        "SERVER": "",
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

def ottieni_cambio_eur():
    try:
        url = "https://min-api.cryptocompare.com/data/price?fsym=USD&tsyms=EUR"
        res = requests.get(url, timeout=5).json()
        return float(res.get("EUR", 0.92))
    except:
        return 0.92

# --- MOTORE ANALISI CON BREAK EVEN MATEMATICO ---
def avvia_scansione(chat_id):
    s = get_stato()
    bot.send_message(chat_id, f"🎯 *MOTORE ULTRA-RAPIDO ATTIVATO...*\n🌐 Server impostato: *{s['SERVER']}*", parse_mode="Markdown")
    ultimo_minuto_segnalato = -1
    
    while True:
        s = get_stato()
        if not s["ATTIVO"]: 
            break
        
        try:
            ora_attuale = datetime.now()
            minuto_attuale = ora_attuale.minute
            secondo_attuale = ora_attuale.second
            
            sym = s['SIMBOLO'].split('-')[0]
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={sym}&tsym=USD&limit=100"
            response = requests.get(url, timeout=5).json()
            
            if response.get("Response") == "Success":
                df_raw = pd.DataFrame(response["Data"]["Data"])
                usd_to_eur = ottieni_cambio_eur()
                
                p_corrente_eur = float(df_raw['close'].iloc[-1]) * usd_to_eur
                p_chiusura_confermata_eur = float(df_raw['close'].iloc[-2]) * usd_to_eur
                
                # ==========================================
                # LOGICA DI GESTIONE TRADE APERTO
                # ==========================================
                if s["TRADE_APERTO"]:
                    if s["DIREZIONE_TRADE"] == "BUY":
                        meta_strada = s["PREZZO_INGRESSO_EUR"] + ((s["TAKE_PROFIT_EUR"] - s["PREZZO_INGRESSO_EUR"]) * 0.5)
                        
                        if p_chiusura_confermata_eur >= meta_strada and not s["BREAK_EVEN_FATTO"]:
                            s["STOP_LOSS_EUR"] = s["PREZZO_INGRESSO_EUR"]
                            s["BREAK_EVEN_FATTO"] = True
                            salva_stato(s)
                            bot.send_message(chat_id, f"🛡️ *BREAK EVEN MATEMATICO CONFERMATO* | {sym}-EUR\nLa candela ha chiuso sopra il livello di sicurezza. Lo Stop Loss è stato ufficialmente spostato a prezzo d'ingresso ({s['STOP_LOSS_EUR']:.2f} €). Rischio Azzerato!", parse_mode="Markdown")
                        
                        elif p_corrente_eur >= s["TAKE_PROFIT_EUR"]:
                            bot.send_message(chat_id, f"🎉 *TARGET COLPITO (TAKE PROFIT)!* | +{(s['CAPITALE']*0.02*1.5):.2f} €", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                        elif p_corrente_eur <= s["STOP_LOSS_EUR"]:
                            perdita = 0.0 if s["BREAK_EVEN_FATTO"] else (s["CAPITALE"] * 0.02)
                            bot.send_message(chat_id, f"🛑 *STOP LOSS COLPITO.* Chiusura trade. Perdita: -{perdita:.2f} €", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                            
                    elif s["DIREZIONE_TRADE"] == "SELL":
                        meta_strada = s["PREZZO_INGRESSO_EUR"] - ((s["PREZZO_INGRESSO_EUR"] - s["TAKE_PROFIT_EUR"]) * 0.5)
                        
                        if p_chiusura_confermata_eur <= meta_strada and not s["BREAK_EVEN_FATTO"]:
                            s["STOP_LOSS_EUR"] = s["PREZZO_INGRESSO_EUR"]
                            s["BREAK_EVEN_FATTO"] = True
                            salva_stato(s)
                            bot.send_message(chat_id, f"🛡️ *BREAK EVEN MATEMATICO CONFERMATO* | {sym}-EUR\nLa candela ha chiuso sotto il livello di sicurezza. Lo Stop Loss è stato ufficialmente spostato a prezzo d'ingresso ({s['STOP_LOSS_EUR']:.2f} €). Rischio Azzerato!", parse_mode="Markdown")
                        
                        elif p_corrente_eur <= s["TAKE_PROFIT_EUR"]:
                            bot.send_message(chat_id, f"🎉 *TARGET COLPITO (TAKE PROFIT)!* | +{(s['CAPITALE']*0.02*1.5):.2f} €", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                        elif p_corrente_eur >= s["STOP_LOSS_EUR"]:
                            perdita = 0.0 if s["BREAK_EVEN_FATTO"] else (s["CAPITALE"] * 0.02)
                            bot.send_message(chat_id, f"🛑 *STOP LOSS COLPITO.* Chiusura trade. Perdita: -{perdita:.2f} €", parse_mode="Markdown")
                            s["TRADE_APERTO"] = False
                            salva_stato(s)
                
                # ==========================================
                # LOGICA DI GENERAZIONE NUOVO SEGNALE
                # ==========================================
                if secondo_attuale <= 5 and minuto_attuale != ultimo_minuto_segnalato and not s["TRADE_APERTO"]:
                    df_ha = calcola_heikin_ashi(df_raw)
                    df_raw['atr'] = calcola_atr(df_raw, period=14)
                    df_raw['sma20'] = df_raw['close'].rolling(20).mean()
                    
                    p_chiusura_usd = float(df_raw['close'].iloc[-1])
                    sma_usd = float(df_raw['sma20'].iloc[-1])
                    atr_usd = float(df_raw['atr'].iloc[-1])
                    
                    ha_open = float(df_ha['open'].iloc[-1])
                    ha_close = float(df_ha['close'].iloc[-1])
                    
                    direzione = None
                    if p_chiusura_usd > sma_usd and ha_close > ha_open:
                        direzione = "BUY"
                    elif p_chiusura_usd < sma_usd and ha_close < ha_open:
                        direzione = "SELL"
                    
                    if direzione:
                        p_chiusura_eur = p_chiusura_usd * usd_to_eur
                        atr_eur = atr_usd * usd_to_eur
                        distanza_sl = atr_eur * 2
                        
                        if direzione == "BUY":
                            stop_loss = p_chiusura_eur - distanza_sl if (distanza_sl < p_chiusura_eur * 0.05) else p_chiusura_eur * 0.98
                            take_profit = p_chiusura_eur + (p_chiusura_eur - stop_loss) * 1.5
                        else:
                            stop_loss = p_chiusura_eur + distanza_sl if (distanza_sl < p_chiusura_eur * 0.05) else p_chiusura_eur * 1.02
                            take_profit = p_chiusura_eur - (stop_loss - p_chiusura_eur) * 1.5

                        rischio_monetario = s["CAPITALE"] * 0.02
                        ampiezza_stop_percentuale = abs(p_chiusura_eur - stop_loss) / p_chiusura_eur
                        
                        if ampiezza_stop_percentuale > 0:
                            posizione_euro = rischio_monetario / ampiezza_stop_percentuale
                            lotti = posizione_euro / p_chiusura_eur
                            guadagno_stimato = rischio_monetario * 1.5
                        else:
                            lotti = 0.0
                            guadagno_stimato = 0.0
                        
                        s["TRADE_APERTO"] = True
                        s["DIREZIONE_TRADE"] = direzione
                        s["PREZZO_INGRESSO_EUR"] = p_chiusura_eur
                        s["STOP_LOSS_EUR"] = stop_loss
                        s["TAKE_PROFIT_EUR"] = take_profit
                        s["BREAK_EVEN_FATTO"] = False
                        salva_stato(s)
                        
                        messaggio_segnale = (
                            f"🚨 *SEGNALE DI TRADING* | {sym}-EUR\n"
                            f"🌐 *Exchange Server:* {s['SERVER']}\n"
                            f"🟢 *OPERAZIONE:* {direzione}\n"
                            f"🪙 *Lotti (Size):* {lotti:.5f} {sym}\n\n"
                            f"⏱️ *Tempistica:* ENTRA ADESSO (Candela Confermata)\n"
                            f"💶 *Prezzo Entrata:* {p_chiusura_eur:.2f} €\n"
                            f"🛑 *Stop Loss:* {stop_loss:.2f} €\n"
                            f"🎯 *Take Profit:* {take_profit:.2f} €\n\n"
                            f"💰 *Guadagno Stimato:* +{guadagno_stimato:.2f} €\n"
                            f"🛡️ _Break Even matematico attivo a chiusura candela_"
                        )
                        bot.send_message(chat_id, messaggio_segnale, parse_mode="Markdown")
                        ultimo_minuto_segnalato = minuto_attuale
                        
        except Exception as e:
            print(f"Errore scansione: {e}")
            
        time.sleep(5)

# --- COMANDI TELEGRAM CON NUOVA SEQUENZA ---
@bot.message_handler(commands=['start', 'avvia'])
def start(m):
    salva_stato({
        "CAPITALE": 0.0, "SERVER": "", "SIMBOLO": "", "ATTIVO": False, 
        "TRADE_APERTO": False, "DIREZIONE_TRADE": None,
        "PREZZO_INGRESSO_EUR": 0.0, "STOP_LOSS_EUR": 0.0,
        "TAKE_PROFIT_EUR": 0.0, "BREAK_EVEN_FATTO": False
    })
    bot.reply_to(m, "💰 Ciao! Inserisci il Capitale in Euro per iniziare:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    s = get_stato()
    
    # Fase 1: Inserimento Capitale
    if m.text.replace('.','',1).isdigit() and s["CAPITALE"] == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato(s)
        bot.reply_to(m, "🖥️ In quale server/exchange operi? (es: Binance, Bybit, Coinbase):")
        
    # Fase 2: Inserimento Server (Accetta testo se il capitale è impostato ma il server è vuoto)
    elif s["CAPITALE"] > 0 and s["SERVER"] == "":
        s["SERVER"] = m.text.upper()
        salva_stato(s)
        bot.reply_to(m, "📈 Perfetto. Ora inserisci l'Asset / Ticker (es: BTC-USD):")
        
    # Fase 3: Inserimento Asset e avvio
    elif "-" in m.text and s["CAPITALE"] > 0 and s["SERVER"] != "" and not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper()
        s["ATTIVO"] = True
        salva_stato(s)
        bot.reply_to(m, f"🚀 Cacciatore attivato su server {s['SERVER']} per l'asset {s['SIMBOLO']}.")
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
        
    elif m.text.lower() == "basta":
        s["ATTIVO"] = False
        s["TRADE_APERTO"] = False
        salva_stato(s)
        bot.reply_to(m, "🛑 Bot fermato e posizioni resettate.")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    try:
        bot.remove_webhook()
    except:
        pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)