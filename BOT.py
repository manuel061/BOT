import telebot, requests, pandas as pd, numpy as np, time, threading, json, os
from flask import Flask

TOKEN = "8822165462:AAE0bK08EDjW-VBf0H-j_OxV3oBp3KNFmaU"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ID_AUTORIZZATI = [5628147908, 987654321] # Inserisci qui i vostri ID
LOG_FILE = "operazioni_log.json"

# --- LOGICA DI CALCOLO ---
def calcola_heikin_ashi(df):
    ha = pd.DataFrame(index=df.index, columns=['open', 'high', 'low', 'close'])
    ha['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha.iloc[0,0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)): ha.iloc[i,0] = (ha.iloc[i-1,0] + ha.iloc[i-1,3]) / 2
    ha['high'] = df[['high','open','close']].max(axis=1)
    ha['low'] = df[['low','open','close']].min(axis=1)
    return ha

def calcola_atr(df):
    r = pd.concat([df['high']-df['low'], np.abs(df['high']-df['close'].shift()), np.abs(df['low']-df['close'].shift())], axis=1).max(axis=1)
    return r.rolling(14).mean()

# --- MOTORE DI SCANSIONE (LA LOGICA COMPLETA) ---
def avvia_scansione(cid):
    while True:
        s = get_stato_utente(cid)
        if not s["ATTIVO"]: break
        try:
            fsym, tsym = s['SIMBOLO'].split('-')
            df = pd.DataFrame(requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=50", timeout=5).json()["Data"]["Data"])
            ha = calcola_heikin_ashi(df)
            atr = calcola_atr(df).iloc[-1]
            p = float(df['close'].iloc[-1])
            sma = df['close'].rolling(20).mean().iloc[-1]

            # GESTIONE TRADE APERTO
            if s.get("TRADE_APERTO"):
                # Break Even: se il prezzo raggiunge metà profitto
                diff = s["TAKE_PROFIT_EUR"] - s["PREZZO_INGRESSO_EUR"]
                if not s.get("BREAK_EVEN_FATTO") and abs(p - s["PREZZO_INGRESSO_EUR"]) >= abs(diff * 0.5):
                    s["STOP_LOSS_EUR"] = s["PREZZO_INGRESSO_EUR"]
                    s["BREAK_EVEN_FATTO"] = True
                    bot.send_message(cid, "🛡️ *BREAK EVEN ATTIVATO* (SL a ingresso)")
                
                # Chiusura TP o SL
                if (s["DIREZIONE"]=="BUY" and (p>=s["TAKE_PROFIT_EUR"] or p<=s["STOP_LOSS_EUR"])) or \
                   (s["DIREZIONE"]=="SELL" and (p<=s["TAKE_PROFIT_EUR"] or p>=s["STOP_LOSS_EUR"])):
                    bot.send_message(cid, f"🏁 *TRADE CHIUSO* - Prezzo: {p:.2f}")
                    s["TRADE_APERTO"] = False
                    s["BREAK_EVEN_FATTO"] = False

            # NUOVO SEGNALE
            elif ha['close'].iloc[-1] > ha['open'].iloc[-1] and p > sma:
                sl = p - (atr * 2)
                tp = p + (atr * 3)
                lotti = (s["CAPITALE"] * 0.02) / abs(p - sl)
                s.update({"TRADE_APERTO":True, "DIREZIONE":"BUY", "PREZZO_INGRESSO_EUR":p, "STOP_LOSS_EUR":sl, "TAKE_PROFIT_EUR":tp})
                bot.send_message(cid, f"📊 *BUY {s['SIMBOLO']}*\n🟢 Entrata: {p:.2f}\n📉 Lotti: {lotti/1000:.2f}\n🛑 SL: {sl:.2f}\n🎯 TP: {tp:.2f}", parse_mode="Markdown")
            
            salva_stato_utente(cid, s)
        except Exception as e: print(e)
        time.sleep(30)

# --- COMANDI E GESTIONE INPUT ---
def get_stato_utente(uid):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: return json.load(f).get(str(uid), {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False})
        except: pass
    return {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}

def salva_stato_utente(uid, s):
    stati = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    stati[str(uid)] = s
    with open(LOG_FILE, "w") as f: json.dump(stati, f)

@bot.message_handler(commands=['start'])
def start(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    salva_stato_utente(m.chat.id, {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False})
    bot.reply_to(m, "💰 Inserisci Capitale:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] == 0:
        s["CAPITALE"] = float(m.text)
        salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "📈 Inserisci Asset (es: BTC-USD):")
    elif not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper(); s["ATTIVO"] = True
        salva_stato_utente(m.chat.id, s)
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=app.run, kwargs={"host":"0.0.0.0", "port":int(os.environ.get("PORT", 10000))}, daemon=True).start()
    bot.infinity_polling()