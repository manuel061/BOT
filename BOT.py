import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321]
cache_utenti = {}

# --- CONNESSIONE DATABASE ---
def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASS", "12345678"),
        database=os.environ.get("DB_NAME", "seganli_bot"),
        port=int(os.environ.get("DB_PORT", 3306))
    )

# --- FUNZIONI DI SUPPORTO ---
def get_stato_utente(uid):
    if uid in cache_utenti: return cache_utenti[uid]
    try:
        conn = get_db(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM utenti WHERE cid = %s", (uid,))
        res = cursor.fetchone(); conn.close()
        stato = {"CAPITALE": float(res['capitale']), "SIMBOLO": res['simbolo'], "ATTIVO": bool(res['attivo'])} if res else {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}
        cache_utenti[uid] = stato
        return stato
    except: return {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}

def salva_stato_utente(uid, s):
    cache_utenti[uid] = s
    def _salva():
        try:
            conn = get_db(); cursor = conn.cursor()
            cursor.execute("REPLACE INTO utenti (cid, capitale, simbolo, attivo) VALUES (%s, %s, %s, %s)",
                           (uid, s["CAPITALE"], s["SIMBOLO"], int(s["ATTIVO"])))
            conn.commit(); conn.close()
        except: pass
    threading.Thread(target=_salva).start()

# --- MOTORE DI SCANSIONE E CONTROLLI ---
def calcola_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def avvia_scansione(cid):
    s = get_stato_utente(cid)
    raw = "".join(filter(str.isalnum, s['SIMBOLO'])).upper()
    fsym, tsym = (raw[:-4], raw[-4:]) if len(raw) > 4 else ("BTC", "USDT")
    
    # Controllo se l'asset esiste
    try:
        test = requests.get(f"https://min-api.cryptocompare.com/data/price?fsym={fsym}&tsym={tsym}", timeout=10).json()
        if "Response" in test and test["Response"] == "Error": raise Exception("Asset non trovato")
    except:
        bot.send_message(cid, "❌ *Mercato chiuso o Asset non valido.* Inserisci un nuovo ticker (es: BTCUSDT):")
        s["SIMBOLO"] = ""; salva_stato_utente(cid, s); return

    bot.send_message(cid, f"🔍 *Ricerca su {fsym}/{tsym} avviata (RSI Attivo)*")
    
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30", timeout=15).json()
            if not data.get("Data"): raise Exception
            df = pd.DataFrame(data["Data"]["Data"])
            p = float(df['close'].iloc[-1])
            
            # Logica TP/SL semplificata per esempio
            # (In un sistema reale dovresti gestire queste variabili nel DB)
            rsi = calcola_rsi(df).iloc[-1]
            
            # Esempio di segnalazione TP/SL (simulato)
            # Qui il bot monitora il prezzo attuale rispetto al target
            # NOTA: Per il sistema completo dovresti confrontare con il prezzo d'entrata salvato
            
            # ... (Logica Heikin Ashi e RSI come prima) ...
            # Se TP raggiunto:
            # bot.send_message(cid, "✅ *TP PRESO!*", parse_mode="Markdown")
            # Se SL raggiunto:
            # bot.send_message(cid, "❌ *SL PRESO!*", parse_mode="Markdown")
            
        except:
            bot.send_message(cid, "⚠️ *Connessione persa.* Reset dell'asset richiesto.")
            s["ATTIVO"] = False; salva_stato_utente(cid, s); break
        time.sleep(60)

@bot.message_handler(commands=['start'])
def cmd_start(m):
    bot.reply_to(m, "🤖 *BENVENUTO*\nInvia il CAPITALE.", parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def h(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0:
        try: 
            s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s)
            bot.reply_to(m, "✅ Capitale salvato. Invia ASSET:")
        except: bot.reply_to(m, "⚠️ Invia un numero.")
    elif s["SIMBOLO"] == "":
        s["SIMBOLO"] = m.text.strip().upper(); salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, f"✅ `{s['SIMBOLO']}` salvato. Invia /avvio.")

if __name__ == "__main__":
    # Rimuove il webhook e force-chiude altre sessioni
    try:
        bot.remove_webhook()
        # Richiesta diretta per pulire eventuali update pendenti su Telegram
        requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1")
    except Exception as e:
        print(f"Errore durante la pulizia: {e}")

    print("Bot avviato correttamente...")
    bot.infinity_polling(none_stop=True, timeout=60, long_polling_timeout=60)