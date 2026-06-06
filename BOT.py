import telebot, pandas as pd, numpy as np, time, threading, os, mysql.connector, yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
asset_cache = {} # Cache per velocizzare la verifica

# --- SERVER HEALTH CHECK ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def do_HEAD(self): self.send_response(200); self.end_headers()

def avvia_porta_render():
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthCheck)
    server.serve_forever()

def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"), user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"), database=os.environ.get("DB_NAME"),
        port=int(os.environ.get("DB_PORT")), ssl_disabled=False 
    )

def salva_stato_db(uid, cap, sym, att):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("REPLACE INTO utenti (cid, capitale, simbolo, attivo) VALUES (%s, %s, %s, %s)", (uid, float(cap), sym, int(att)))
        conn.commit(); conn.close()
    except Exception as e: print(f"DB Error: {e}")

def get_stato_utente(uid):
    try:
        conn = get_db(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM utenti WHERE cid = %s", (uid,))
        res = cursor.fetchone(); conn.close()
        return res if res else {"cid": uid, "capitale": 0.0, "simbolo": "", "attivo": 0}
    except: return {"cid": uid, "capitale": 0.0, "simbolo": "", "attivo": 0}

def verifica_asset(simbolo):
    # Uso della cache per velocità
    if simbolo in asset_cache: return asset_cache[simbolo]
    
    # Tentativi intelligenti
    varianti = [simbolo.upper(), f"{simbolo.upper()}-USD", f"{simbolo.upper()}USD=X"]
    for s in varianti:
        try:
            t = yf.Ticker(s)
            if t.fast_info.get('last_price'):
                asset_cache[simbolo] = s
                return s
        except: continue
    return None

# --- LOGICA TRADING (Ottimizzata) ---
def avvia_scansione(cid):
    while True:
        s = get_stato_utente(cid)
        if not s['attivo']: break
        try:
            # Scarichiamo meno dati per andare più veloci (1h invece di 1d)
            df = yf.Ticker(s['simbolo']).history(period="1h", interval="1m")
            p = df['Close'].iloc[-1]
            sma = df['Close'].rolling(20).mean().iloc[-1]
            
            tipo = "BUY" if (p > sma) else "SELL"
            tp, sl = (p*1.01, p*0.995) if tipo == "BUY" else (p*0.99, p*1.005)
            
            conn = get_db(); cursor = conn.cursor()
            cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, s['simbolo']))
            conn.commit(); conn.close()
            bot.send_message(cid, f"✨ *{tipo}* {s['simbolo']}\n💰 {p:.2f}\n🎯 {tp:.2f}\n🛑 {sl:.2f}", parse_mode="Markdown")
            time.sleep(60) # Scansione ogni minuto
        except: time.sleep(60)

def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                p = yf.Ticker(op['simbolo']).fast_info.get('last_price', 0)
                if p and ((op['tipo'] == "BUY" and p >= op['tp']) or (op['tipo'] == "SELL" and p <= op['tp'])):
                    bot.send_message(op['cid'], f"✅ *TP!* {op['simbolo']} a `{p:.2f}`")
                    cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(30) # Monitoraggio più rapido

# --- COMANDI ---
@bot.message_handler(commands=['start', 'avvio', 'reset', 'stop'])
def cmd(m):
    cid = m.chat.id
    if m.text == '/start':
        salva_stato_db(cid, 0, "", 0)
        bot.reply_to(m, "🤖 Invia il CAPITALE (es: 1000)")
    elif m.text == '/avvio':
        salva_stato_db(cid, get_stato_utente(cid)['capitale'], get_stato_utente(cid)['simbolo'], 1)
        threading.Thread(target=avvia_scansione, args=(cid,), daemon=True).start()
        bot.reply_to(m, "🚀 Avviato.")
    elif m.text == '/reset':
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM utenti WHERE cid = %s", (cid,))
        conn.commit(); conn.close(); bot.reply_to(m, "🗑️ Resettato.")

@bot.message_handler(func=lambda m: True)
def h(m):
    cid = m.chat.id
    s = get_stato_utente(cid)
    if s['capitale'] <= 0:
        try:
            salva_stato_db(cid, float(m.text.replace(',', '.')), "", 0)
            bot.reply_to(m, "✅ Capitale salvato. Ora invia l'ASSET (es: BTC, EUR/USD)")
        except: bot.reply_to(m, "⚠️ Invia solo un numero.")
    elif not s['simbolo']:
        asset = verifica_asset(m.text)
        if asset:
            salva_stato_db(cid, s['capitale'], asset, 0)
            bot.reply_to(m, f"✅ Asset `{asset}` accettato! Scrivi /avvio.")
        else: bot.reply_to(m, "❌ Non trovato. Prova es: 'BTC-USD', 'EURUSD=X'")

if __name__ == "__main__":
    threading.Thread(target=avvia_porta_render, daemon=True).start()
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)