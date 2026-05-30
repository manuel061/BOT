import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)

# --- SERVER HEALTH CHECK (Render) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def do_HEAD(self): self.send_response(200); self.end_headers()

def avvia_porta_render():
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthCheck)
    server.serve_forever()

# --- CONNESSIONE DATABASE ---
def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"), user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASS", "12345678"), database=os.environ.get("DB_NAME", "seganli_bot"),
        port=int(os.environ.get("DB_PORT", 3306))
    )

def salva_stato_db(uid, cap, sym, att):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("REPLACE INTO utenti (cid, capitale, simbolo, attivo) VALUES (%s, %s, %s, %s)", (uid, float(cap), sym, int(att)))
        conn.commit(); conn.close()
    except: pass

def get_stato_utente(uid):
    try:
        conn = get_db(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM utenti WHERE cid = %s", (uid,))
        res = cursor.fetchone(); conn.close()
        return res if res else {"cid": uid, "capitale": 0.0, "simbolo": "", "attivo": 0}
    except: return {"cid": uid, "capitale": 0.0, "simbolo": "", "attivo": 0}

# --- LOGICA ASSET POTENZIATA ---
def verifica_asset(simbolo):
    # Pulisce l'input: trasforma "BTC-USD" o "BTC/USD" in "BTCUSDT" o "BTCUSD"
    pulito = "".join(filter(str.isalnum, simbolo)).upper()
    for s in [pulito, pulito + "USDT", pulito + "USD"]:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={s}", timeout=5)
            if r.status_code == 200: return s
        except: continue
    return None

# --- MONITORAGGIO E SCANSIONE ---
def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                p = float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={op['simbolo']}").json().get('price', 0))
                if p > 0:
                    if (op['tipo'] == "BUY" and p >= op['tp']) or (op['tipo'] == "SELL" and p <= op['tp']):
                        bot.send_message(op['cid'], f"✅ *TP PRESO!* {op['simbolo']} a `{p}`")
                        cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
                    elif (op['tipo'] == "BUY" and p <= op['sl']) or (op['tipo'] == "SELL" and p >= op['sl']):
                        bot.send_message(op['cid'], f"❌ *SL PRESO!* {op['simbolo']} a `{p}`")
                        cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(60)

def avvia_scansione(cid):
    while True:
        s = get_stato_utente(cid)
        if not s['attivo']: break
        try:
            data = requests.get(f"https://api.binance.com/api/v3/klines?symbol={s['simbolo']}&interval=1m&limit=30").json()
            df = pd.DataFrame(data, columns=['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i'])
            df['c'] = df['c'].astype(float)
            p = df['c'].iloc[-1]
            sma = df['c'].rolling(20).mean().iloc[-1]
            tipo = "BUY" if (p > sma) else "SELL"
            
            lotto = (s['capitale'] * 0.02) / (p * 0.01)
            tp, sl = (p*1.02, p*0.99) if tipo == "BUY" else (p*0.98, p*1.01)
            
            conn = get_db(); cursor = conn.cursor()
            cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, s['simbolo']))
            conn.commit(); conn.close()
            bot.send_message(cid, f"✨ *SEGNALE {tipo}* {s['simbolo']}\n💰 Entrata: {p:.4f}\n🎯 TP: {tp:.4f}\n🛑 SL: {sl:.4f}", parse_mode="Markdown")
            time.sleep(300)
        except: pass
        time.sleep(60)

# --- COMANDI ---
@bot.message_handler(commands=['start', 'avvio', 'reset', 'stop'])
def cmd(m):
    cid = m.chat.id
    if m.text == '/start': bot.reply_to(m, "🤖 Benvenuto! Invia il CAPITALE (es: 1000)")
    elif m.text == '/avvio':
        s = get_stato_utente(cid)
        if s['capitale'] > 0 and s['simbolo']:
            salva_stato_db(cid, s['capitale'], s['simbolo'], 1)
            threading.Thread(target=avvia_scansione, args=(cid,), daemon=True).start()
            bot.reply_to(m, "🚀 Scansione avviata.")
        else: bot.reply_to(m, "⚠️ Configurazione incompleta!")
    elif m.text == '/reset':
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM utenti WHERE cid = %s", (cid,))
        conn.commit(); conn.close(); bot.reply_to(m, "🗑️ Tutto resettato.")
    elif m.text == '/stop':
        salva_stato_db(cid, get_stato_utente(cid)['capitale'], get_stato_utente(cid)['simbolo'], 0)
        bot.reply_to(m, "⏹️ Scansione fermata.")

@bot.message_handler(func=lambda m: True)
def h(m):
    cid = m.chat.id
    s = get_stato_utente(cid)
    if s['capitale'] <= 0:
        try: salva_stato_db(cid, float(m.text.replace(',', '.')), "", 0); bot.reply_to(m, "✅ Capitale salvato. Ora invia l'ASSET (es: BTC, BTCUSDT)")
        except: bot.reply_to(m, "⚠️ Inviami un numero valido per il capitale.")
    elif not s['simbolo']:
        asset = verifica_asset(m.text)
        if asset: salva_stato_db(cid, s['capitale'], asset, 0); bot.reply_to(m, f"✅ Asset `{asset}` accettato! Scrivi /avvio.")
        else: bot.reply_to(m, "❌ Asset non trovato. Riprova con un formato chiaro (es: BTCUSDT).")

if __name__ == "__main__":
    threading.Thread(target=avvia_porta_render, daemon=True).start()
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    bot.remove_webhook()
    print("Bot avviato correttamente.")
    bot.infinity_polling(skip_pending=True)