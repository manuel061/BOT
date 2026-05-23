import telebot, requests, pandas as pd, numpy as np, time, threading, json, os

TOKEN = "8822165462:AAE0bK08EDjW-VBf0H-j_OxV3oBp3KNFmaU"
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321] 
LOG_FILE = "operazioni_log.json"

# [--- FUNZIONI DI CALCOLO INVARIATE ---]
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
    stati = {}
    if os.path.exists(LOG_FILE):
        try: with open(LOG_FILE, "r") as f: stati = json.load(f)
        except: pass
    stati[str(uid)] = s
    with open(LOG_FILE, "w") as f: json.dump(stati, f)

def get_stato_utente(uid):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f: return json.load(f).get(str(uid), {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False, "TRADE_APERTO":False, "ULTIMO_TRADE":0})
        except: pass
    return {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False, "TRADE_APERTO":False, "ULTIMO_TRADE":0}

# --- MOTORE DI SCANSIONE ---
def avvia_scansione(cid):
    bot.send_message(cid, "🔍 *Scansione avviata in background...*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            fsym, tsym = s['SIMBOLO'].split('-')
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=50"
            data = requests.get(url, timeout=10).json()["Data"]["Data"]
            df = pd.DataFrame(data)
            ha = calcola_heikin_ashi(df)
            p = float(df['close'].iloc[-1])
            
            # Print di controllo nel log di Render
            print(f"Controllo {s['SIMBOLO']}: Prezzo attuale {p}")

            if not s.get("TRADE_APERTO"):
                # FORZATURA PER VEDERE IL MESSAGGIO:
                # Se vuoi testare la grafica, cambia 'if False' in 'if True'
                if False: 
                    msg = f"📊 *BUY {s['SIMBOLO']} (TEST)*\n🟢 Entrata: {p:.2f}\n🛑 SL: {p-1:.2f}\n🎯 TP: {p+2:.2f}"
                    bot.send_message(cid, msg, parse_mode="Markdown")
                    s.update({"TRADE_APERTO":True, "DIREZIONE":"BUY", "PREZZO_INGRESSO":p})
                    salva_stato_utente(cid, s)
        except Exception as e: print(f"Errore scansione: {e}")
        time.sleep(60)

# --- COMANDI ---
@bot.message_handler(commands=['start', 'avvio', 'stop', 'cancella', 'test', 'test_msg'])
def cmd(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    c = m.text.split()[0]
    if c == '/start':
        bot.reply_to(m, "🤖 *COMANDI DISPONIBILI:*\n/avvio - Start\n/stop - Stop\n/cancella - Reset\n/test_msg - Test invio segnale")
    elif c == '/test_msg':
        bot.reply_to(m, "📊 *BUY TEST-ASSET*\n🟢 Entrata: 100.00\n📉 Lotti: 0.05\n🛑 SL: 99.00\n🎯 TP: 103.00", parse_mode="Markdown")
    elif c == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"] != "":
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s)
            bot.reply_to(m, "🚀 *Motore Avviato*")
            threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
        else: bot.reply_to(m, "⚠️ Configura Capitale e Asset prima.")
    elif c == '/stop':
        s = get_stato_utente(m.chat.id); s["ATTIVO"] = False; salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "🔴 *Motore Fermo*")
    elif c == '/cancella':
        salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False})
        bot.reply_to(m, "🗑️ *Reset Totale*")

@bot.message_handler(func=lambda m: True)
def h(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] == 0:
        try: s["CAPITALE"] = float(m.text); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "📈 Capitale ok. Inserisci Asset (es: BTC-USD):")
        except: bot.reply_to(m, "⚠️ Inserisci un numero.")
    elif s["SIMBOLO"] == "":
        s["SIMBOLO"] = m.text.upper(); salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "✅ DATI ACQUISITI, INIZIO RICERCA OPERAZIONI.")

if __name__ == "__main__":
    bot.remove_webhook()
    print("Bot pronto.")
    bot.infinity_polling(none_stop=True)