import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector, socket

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
cache_utenti = {}

def avvia_porta_render():
    port = int(os.environ.get("PORT", 10000))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen(5)
    while True:
        conn, addr = server.accept()
        conn.close()

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

def verifica_asset(simbolo):
    raw = "".join(filter(str.isalnum, simbolo)).upper()
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={raw}", timeout=5)
        if r.status_code == 200: return raw
        return None
    except: return None

def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                p = float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={op['simbolo']}").json().get('price', 0))
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
    simbolo = s["SIMBOLO"]
    bot.send_message(cid, f"🔍 *Scansione {simbolo} avviata.*")
    while get_stato_utente(cid).get("ATTIVO"):
        try:
            data = requests.get(f"https://api.binance.com/api/v3/klines?symbol={simbolo}&interval=1m&limit=30").json()
            df = pd.DataFrame(data, columns=['t', 'open', 'high', 'low', 'close', 'v', 'ct', 'qav', 'num', 'taker_b', 'taker_q', 'ignore'])
            df['close'] = df['close'].astype(float)
            p = df['close'].iloc[-1]
            delta = df['close'].diff()
            rsi = (100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / (-delta.where(delta < 0, 0).rolling(14).mean()))))).iloc[-1]
            sma = df['close'].rolling(20).mean().iloc[-1]
            tipo = "BUY" if (p > sma and rsi < 70) else ("SELL" if (p < sma and rsi > 30) else None)
            
            if tipo:
                lotto = (s["CAPITALE"] * 0.02) / (p * 0.01)
                tp, sl = (p*1.02, p*0.99) if tipo == "BUY" else (p*0.98, p*1.01)
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, simbolo))
                conn.commit(); conn.close()
                msg = f"✨ **SEGNALE {tipo}**\n\n🔹 **Asset:** `{simbolo}`\n💰 **Entrata:** `{p:.4f}`\n🔢 **Lotti:** `{lotto:.4f}`\n🎯 **TP:** `{tp:.4f}`\n🛑 **SL:** `{sl:.4f}`\n📊 *Analisi:* {'Rialzista' if p > sma else 'Ribassista'}"
                bot.send_message(cid, msg, parse_mode="Markdown")
                time.sleep(300)
        except: pass
        time.sleep(60)

@bot.message_handler(commands=['start', 'avvio', 'reset', 'stop', 'cancella'])
def cmd(m):
    if m.text == '/start':
        bot.reply_to(m, "🤖 *BENVENUTO*\nInvia CAPITALE per iniziare.", parse_mode="Markdown")
    elif m.text == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"]:
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s); threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start(); bot.reply_to(m, "🚀 Avviato.")
    elif m.text in ['/reset', '/cancella']: salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}); bot.reply_to(m, "🗑️ Resettato.")
    elif m.text == '/stop': s = get_stato_utente(m.chat.id); s["ATTIVO"] = False; salva_stato_utente(m.chat.id, s); bot.reply_to(m, "⏹️ Fermato.")

@bot.message_handler(func=lambda m: True)
def h(m):
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0:
        try: s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "✅ Capitale preso. Invia ASSET (es: BTCUSDT):")
        except: bot.reply_to(m, "⚠️ Invia un numero.")
    elif not s["SIMBOLO"]:
        simbolo = verifica_asset(m.text)
        if not simbolo: bot.reply_to(m, "❌ Asset non trovato su Binance. Reinserisci (es: BTCUSDT):")
        else: s["SIMBOLO"] = simbolo; salva_stato_utente(m.chat.id, s); bot.reply_to(m, f"✅ `{simbolo}` salvato. Invia /avvio.")

if __name__ == "__main__":
    threading.Thread(target=avvia_porta_render, daemon=True).start()
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    bot.infinity_polling(skip_pending=True)