import telebot, requests, pandas as pd, numpy as np, time, threading, json, os

TOKEN = "8822165462:AAE0bK08EDjW-VBf0H-j_OxV3oBp3KNFmaU"
bot = telebot.TeleBot(TOKEN)

ID_AUTORIZZATI = [5628147908, 987654321] 
LOG_FILE = "operazioni_log.json"

# --- FUNZIONI DI CALCOLO ---
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

def salva_stato_utente(uid, s):
    stati = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    stati[str(uid)] = s
    with open(LOG_FILE, "w") as f: json.dump(stati, f)

def get_stato_utente(uid):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: return json.load(f).get(str(uid), {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False, "TRADE_APERTO":False, "ULTIMO_TRADE":0})
        except: pass
    return {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False, "TRADE_APERTO":False, "ULTIMO_TRADE":0}

# --- MOTORE DI SCANSIONE SELETTIVO ---
def avvia_scansione(cid):
    while True:
        s = get_stato_utente(cid)
        if not s["ATTIVO"]: break
        try:
            fsym, tsym = s['SIMBOLO'].split('-')
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=50", timeout=5).json()["Data"]["Data"]
            df = pd.DataFrame(data)
            ha = calcola_heikin_ashi(df)
            atr = calcola_atr(df).iloc[-1]
            p = float(df['close'].iloc[-1])
            sma = df['close'].rolling(20).mean().iloc[-1]

            # GESTIONE TRADE APERTO
            if s.get("TRADE_APERTO"):
                diff = s["TAKE_PROFIT"] - s["PREZZO_INGRESSO"]
                if not s.get("BREAK_EVEN_FATTO") and abs(p - s["PREZZO_INGRESSO"]) >= abs(diff * 0.5):
                    s["STOP_LOSS"] = s["PREZZO_INGRESSO"]
                    s["BREAK_EVEN_FATTO"] = True
                    bot.send_message(cid, "🛡️ *BREAK EVEN ATTIVATO* (SL a ingresso)")
                    salva_stato_utente(cid, s)
                
                if (s["DIREZIONE"]=="BUY" and (p>=s["TAKE_PROFIT"] or p<=s["STOP_LOSS"])) or \
                   (s["DIREZIONE"]=="SELL" and (p<=s["TAKE_PROFIT"] or p>=s["STOP_LOSS"])):
                    bot.send_message(cid, f"🏁 *TRADE CHIUSO* - Prezzo finale: {p:.2f}")
                    s["TRADE_APERTO"] = False
                    s["BREAK_EVEN_FATTO"] = False
                    s["ULTIMO_TRADE"] = time.time() # Registra orario chiusura
                    salva_stato_utente(cid, s)

            # NUOVO SEGNALE SELETTIVO
            # Verifica: Cooldown 30 min (1800 sec) + Setup tecnico valido + Volatilità minima
            elif not s.get("TRADE_APERTO") and (time.time() - s.get("ULTIMO_TRADE", 0) > 1800):
                if ha['close'].iloc[-1] > ha['open'].iloc[-1] and p > sma and atr > (p * 0.0001):
                    sl = p - (atr * 2)
                    tp = p + (atr * 3)
                    lotti_calcolati = (s["CAPITALE"] * 0.02) / abs(p - sl)
                    lotti_finali = max(0.01, round(lotti_calcolati / 1000, 2))
                    
                    s.update({"TRADE_APERTO":True, "DIREZIONE":"BUY", "PREZZO_INGRESSO":p, "STOP_LOSS":sl, "TAKE_PROFIT":tp})
                    bot.send_message(cid, f"📊 *BUY {s['SIMBOLO']}*\n🟢 Entrata: {p:.2f}\n📉 Lotti: {lotti_finali:.2f}\n🛑 SL: {sl:.2f}\n🎯 TP: {tp:.2f}\n💰 Profitto stimato: {((tp-p)*(lotti_finali*1000)):.2f}", parse_mode="Markdown")
                    salva_stato_utente(cid, s)
        except: pass
        time.sleep(30)

@bot.message_handler(commands=['start'])
def start(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    salva_stato_utente(m.chat.id, {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False, "TRADE_APERTO": False, "ULTIMO_TRADE": 0})
    bot.reply_to(m, "💰 Inserisci Capitale:")

@bot.message_handler(func=lambda m: True)
def handle(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] == 0:
        try:
            s["CAPITALE"] = float(m.text)
            salva_stato_utente(m.chat.id, s)
            bot.reply_to(m, "📈 Capitale ricevuto. Inserisci Asset (es: BTC-USD):")
        except: bot.reply_to(m, "⚠️ Inserisci un numero valido.")
    elif not s["ATTIVO"]:
        s["SIMBOLO"] = m.text.upper(); s["ATTIVO"] = True
        salva_stato_utente(m.chat.id, s)
        threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
        bot.reply_to(m, "🚀 Motore di scansione (Alta Qualità) attivato.")

bot.infinity_polling()