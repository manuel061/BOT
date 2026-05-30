import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321]
cache_utenti = {}

def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"), user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASS", "12345678"), database=os.environ.get("DB_NAME", "seganli_bot"),
        port=int(os.environ.get("DB_PORT", 3306))
    )

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
            cursor.execute("REPLACE INTO utenti (cid, capitale, simbolo, attivo) VALUES (%s, %s, %s, %s)", (uid, s["CAPITALE"], s["SIMBOLO"], int(s["ATTIVO"])))
            conn.commit(); conn.close()
        except: pass
    threading.Thread(target=_salva, daemon=True).start()

def calcola_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                p = float(requests.get(f"https://min-api.cryptocompare.com/data/price?fsym={op['simbolo'][:-4]}&tsym=USDT").json().get("USDT", 0))
                if (op['tipo'] == "BUY" and p >= op['tp']) or (op['tipo'] == "SELL" and p <= op['tp']):
                    bot.send_message(op['cid'], f"✅ *TP PRESO!* {op['simbolo']} a `{p}`")
                    cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
                elif (op['tipo'] == "BUY" and p <= op['sl']) or (op['tipo'] == "SELL" and p >= op['sl']):
                    bot.send_message(op['cid'], f"❌ *SL PRESO!* {op['simbolo']} a `{p}`")
                    cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(45)

def avvia_scansione(cid):
    s = get_stato_utente(cid)
    raw = "".join(filter(str.isalnum, s['SIMBOLO'])).upper()
    fsym, tsym = (raw[:-4], raw[-4:]) if len(raw) > 4 else ("BTC", "USDT")
    
    try:
        if "Error" in requests.get(f"https://min-api.cryptocompare.com/data/price?fsym={fsym}&tsym={tsym}").json().get("Response", ""): raise Exception()
    except: bot.send_message(cid, "❌ Asset non valido. Invia /reset e riprova."); return

    bot.send_message(cid, f"🔍 *Scansione {fsym}/{tsym} avviata.*")
    while get_stato_utente(cid).get("ATTIVO"):
        try:
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30").json()["Data"]["Data"]
            df = pd.DataFrame(data)
            p, rsi = float(df['close'].iloc[-1]), calcola_rsi(df).iloc[-1]
            
            tipo = "BUY" if (p > df['close'].rolling(20).mean().iloc[-1] and rsi < 70) else ("SELL" if (p < df['close'].rolling(20).mean().iloc[-1] and rsi > 30) else None)
            if tipo:
                tp, sl = (p*1.02, p*0.99) if tipo == "BUY" else (p*0.98, p*1.01)
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, fsym+tsym))
                conn.commit(); conn.close()
                bot.send_message(cid, f"{'🟢' if tipo=='BUY' else '🔴'} *SEGNALE {tipo}* ({fsym+tsym}) inserito.")
                time.sleep(300)
        except: pass
        time.sleep(60)

@bot.message_handler(commands=['start', 'avvio', 'reset'])
def cmd(m):
    if m.text == '/start': bot.reply_to(m, "🤖 Invia CAPITALE.")
    elif m.text == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"]:
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s); threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start(); bot.reply_to(m, "🚀 Avviato.")
    elif m.text == '/reset': salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}); bot.reply_to(m, "🗑️ Resettato.")

@bot.message_handler(func=lambda m: True)
def h(m):
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0: s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "✅ Capitale preso. Invia ASSET:")
    elif not s["SIMBOLO"]: s["SIMBOLO"] = m.text.upper(); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "✅ Salvato. Invia /avvio.")

if __name__ == "__main__":
    # 1. Avvia il monitoraggio in background
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    
    # 2. Pulizia forzata per evitare il conflitto 409
    try:
        print("Pulizia sessioni precedenti...")
        bot.remove_webhook()
        # Il parametro offset=-1 azzera la coda di messaggi in sospeso
        requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1")
    except Exception as e:
        print(f"Errore pulizia: {e}")

    # 3. Avvio con configurazione ottimizzata
    print("Bot avviato correttamente.")
    bot.infinity_polling(
        skip_pending=True, 
        none_stop=True, 
        timeout=60, 
        long_polling_timeout=60
    )