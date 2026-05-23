import telebot, requests, pandas as pd, numpy as np, time, threading, json, os

TOKEN = "8822165462:AAE0bK08EDjW-VBf0H-j_OxV3oBp3KNFmaU"
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321] 
LOG_FILE = "operazioni_log.json"

# --- CALCOLI ---
def calcola_heikin_ashi(df):
    ha = pd.DataFrame(index=df.index, columns=['open', 'high', 'low', 'close'])
    ha['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha.iloc[0,0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)): ha.iloc[i,0] = (ha.iloc[i-1,0] + ha.iloc[i-1,3]) / 2
    ha['high'] = df[['high','open','close']].max(axis=1)
    ha['low'] = df[['low','open','close']].min(axis=1)
    return ha

def get_stato_utente(uid):
    if os.path.exists(LOG_FILE):
        try: 
            with open(LOG_FILE, "r") as f: 
                return json.load(f).get(str(uid), {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False})
        except: 
            pass
    return {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}

def salva_stato_utente(uid, s):
    stati = {}
    if os.path.exists(LOG_FILE):
        try: with open(LOG_FILE, "r") as f: stati = json.load(f)
        except: pass
    stati[str(uid)] = s
    with open(LOG_FILE, "w") as f: json.dump(stati, f)

# --- MOTORE DI SCANSIONE ---
def avvia_scansione(cid):
    bot.send_message(cid, "🔍 *RICERCA OPERAZIONI IN CORSO...*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            fsym, tsym = s['SIMBOLO'].split('-')
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=20", timeout=10).json()["Data"]["Data"]
            df = pd.DataFrame(data)
            ha = calcola_heikin_ashi(df)
            p = float(df['close'].iloc[-1])
            
            # LOGICA: Trend rialzista (BUY)
            if ha['close'].iloc[-1] > ha['open'].iloc[-1]:
                sl = round(p * 0.99, 2)
                tp = round(p * 1.02, 2)
                lotti = max(0.01, round((s["CAPITALE"] * 0.02) / 100, 2))
                
                # MESSAGGIO RICHIESTO (SOLO DATI)
                msg = (f"📈 *BUY*\n"
                       f"Entrata: {p:.2f}\n"
                       f"Lotti: {lotti:.2f}\n"
                       f"SL: {sl:.2f}\n"
                       f"TP: {tp:.2f}")
                bot.send_message(cid, msg, parse_mode="Markdown")
                time.sleep(300) # Attesa per non inondare di messaggi
        except: pass
        time.sleep(30)

# --- COMANDI ---
@bot.message_handler(commands=['start', 'avvio', 'stop', 'cancella', 'test'])
def cmd(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    c = m.text.split()[0]
    if c == '/start':
        txt = ("🤖 *BENVENUTO*\n"
               "Comandi disponibili:\n"
               "/avvio - Inizia scansione\n"
               "/stop - Ferma scansione\n"
               "/cancella - Reset impostazioni\n"
               "/test - Verifica connessione\n\n"
               "Per favore, invia il CAPITALE (es: 1000)")
        bot.reply_to(m, txt, parse_mode="Markdown")
    elif c == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"] != "":
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s)
            threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
    elif c == '/stop':
        s = get_stato_utente(m.chat.id); s["ATTIVO"] = False; salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "🔴 *Motore Fermo*")
    elif c == '/cancella':
        salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False})
        bot.reply_to(m, "🗑️ *Reset Totale eseguito.*")

@bot.message_handler(func=lambda m: True)
def h(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] == 0:
        try: 
            s["CAPITALE"] = float(m.text)
            salva_stato_utente(m.chat.id, s)
            bot.reply_to(m, "✅ Capitale impostato. Ora invia l'ASSET (es: BTC-USD):")
        except: bot.reply_to(m, "⚠️ Inserisci un valore numerico per il capitale.")
    elif s["SIMBOLO"] == "":
        s["SIMBOLO"] = m.text.upper()
        salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "✅ Asset acquisito. Digita /avvio per iniziare.")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling(none_stop=True)