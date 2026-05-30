import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector, socket

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321]
cache_utenti = {}

# --- FIX PER RENDER: SERVER FITTIZIO ---
def avvia_porta_render():
    port = int(os.environ.get("PORT", 10000))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen(5)
    while True:
        conn, addr = server.accept()
        conn.close()

# --- CONNESSIONE DATABASE ---
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

def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                base, quote = (op['simbolo'][:-4], "USDT") if "USDT" in op['simbolo'] else (op['simbolo'][:-3], "USD")
                p = float(requests.get(f"https://min-api.cryptocompare.com/data/price?fsym={base}&tsym={quote}").json().get(quote, 0))
                if p == 0: continue
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
    fsym, tsym = (raw[:-4], "USDT") if raw.endswith("USDT") else (raw[:-3], "USD") if raw.endswith("USD") else (raw, "USDT")
    
    bot.send_message(cid, f"🔍 *Scansione {fsym}/{tsym} avviata.*")
    while get_stato_utente(cid).get("ATTIVO"):
        try:
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30").json()["Data"]["Data"]
            df = pd.DataFrame(data)
            p = float(df['close'].iloc[-1])
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = (100 - (100 / (1 + rs))).iloc[-1]
            sma = df['close'].rolling(20).mean().iloc[-1]
            tipo = "BUY" if (p > sma and rsi < 70) else ("SELL" if (p < sma and rsi > 30) else None)
            if tipo:
                tp, sl = (p*1.02, p*0.99) if tipo == "BUY" else (p*0.98, p*1.01)
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, fsym+tsym))
                conn.commit(); conn.close()
                bot.send_message(cid, f"{'🟢' if tipo=='BUY' else '🔴'} *SEGNALE {tipo}* ({fsym+tsym}) inserito.")
                time.sleep(300)
        except: pass
        time.sleep(60)

@bot.message_handler(commands=['start', 'avvio', 'reset', 'stop', 'cancella'])
def cmd(m):
    if m.text == '/start':
        menu = ("🤖 *BENVENUTO*\n\nComandi disponibili:\n/start: Menu\n/avvio: Avvia scansione\n/stop: Ferma monitoraggio\n/reset: Pulisci dati\n\nInvia CAPITALE per iniziare.")
        bot.reply_to(m, menu, parse_mode="Markdown")
    elif m.text == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"]:
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s); threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start(); bot.reply_to(m, "🚀 Avviato.")
    elif m.text in ['/reset', '/cancella']: salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}); bot.reply_to(m, "🗑️ Resettato.")
    elif m.text == '/stop': s = get_stato_utente(m.chat.id); s["ATTIVO"] = False; salva_stato_utente(m.chat.id, s); bot.reply_to(m, "⏹️ Monitoraggio fermato.")

@bot.message_handler(func=lambda m: True)
def h(m):
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0:
        try: s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "✅ Capitale preso. Invia ASSET (es: BTCUSDT):")
        except: bot.reply_to(m, "⚠️ Invia un numero.")
    elif not s["SIMBOLO"]: s["SIMBOLO"] = m.text.upper(); salva_stato_utente(m.chat.id, s); bot.reply_to(m, f"✅ `{s['SIMBOLO']}` salvato. Invia /avvio.")

if __name__ == "__main__":
    threading.Thread(target=avvia_porta_render, daemon=True).start()
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    bot.remove_webhook()
    try: requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1")
    except: pass
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)