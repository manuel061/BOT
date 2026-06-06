import telebot, pandas as pd, numpy as np, time, threading, os, mysql.connector, yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
asset_cache = {} 

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
        port=int(os.environ.get("DB_PORT")), ssl_disabled=False, connect_timeout=5
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
    # Pulisce l'input
    s = simbolo.strip().upper()
    
    # FORZATURA: Yahoo Finance richiede suffissi precisi. 
    # Se scrivi XAUUSD, deve essere XAUUSD=X
    # Se scrivi BTC, deve essere BTC-USD
    
    mappa = {
        "XAU": "XAUUSD=X", "XAUUSD": "XAUUSD=X",
        "GOLD": "XAUUSD=X",
        "BTC": "BTC-USD", "BITCOIN": "BTC-USD",
        "ETH": "ETH-USD", "ETHEREUM": "ETH-USD",
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X"
    }
    
    # Se l'asset è nella mappa, usalo. Altrimenti prova quello scritto dall'utente
    target = mappa.get(s, s)
    
    print(f"DEBUG: Cercando ticker: {target}")
    
    try:
        t = yf.Ticker(target)
        # Proviamo a leggere il prezzo attuale
        info = t.fast_info
        if info and 'last_price' in info:
            p = info['last_price']
            # Se il volume è 0, il mercato è chiuso
            if info.get('last_volume', 0) == 0:
                return "CHIUSO"
            return target
        return None
    except Exception as e:
        print(f"DEBUG: Errore critico su {target}: {e}")
        return None
def avvia_scansione(cid):
    bot.send_message(cid, "🔍 *Scansione attiva...*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s or not s['attivo']: break
        try:
            df = yf.Ticker(s['simbolo']).history(period="1h", interval="1m")
            if df.empty: time.sleep(60); continue
            p = df['Close'].iloc[-1]
            sma = df['Close'].rolling(20).mean().iloc[-1]
            if (p > sma): tipo = "BUY"
            elif (p < sma): tipo = "SELL"
            else: time.sleep(30); continue
            tp, sl = (p*1.01, p*0.995) if tipo == "BUY" else (p*0.99, p*1.005)
            
            msg = (f"✨ *SEGNALE {tipo}* (Scade in 3 min!)\n"
                   f"➖➖➖➖➖➖➖➖\n"
                   f"ASSET: `{s['simbolo']}`\n"
                   f"PREZZO: `{p:.4f}`\n"
                   f"TP: `{tp:.4f}`\n"
                   f"🛑 SL: `{sl:.4f}`\n"
                   f"➖➖➖➖➖➖➖➖")
            
            sent = bot.send_message(cid, msg, parse_mode="Markdown")
            time.sleep(180) 
            bot.edit_message_text(chat_id=cid, message_id=sent.message_id, text=f"{msg}\n\n❌ *SEGNALE SCADUTO*", parse_mode="Markdown")
            
            conn = get_db(); cursor = conn.cursor()
            cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo) VALUES (%s, %s, %s, %s, %s, %s)", (cid, tipo, p, tp, sl, s['simbolo']))
            conn.commit(); conn.close()
            time.sleep(120) 
        except Exception as e: time.sleep(60)

def monitora_tp_sl():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                p = yf.Ticker(op['simbolo']).fast_info.get('last_price', 0)
                if p > 0:
                    if (op['tipo'] == "BUY" and (p >= op['tp'] or p <= op['sl'])) or (op['tipo'] == "SELL" and (p <= op['tp'] or p >= op['sl'])):
                        esito = "✅ TP PRESO" if (p >= op['tp'] if op['tipo'] == "BUY" else p <= op['tp']) else "❌ SL PRESO"
                        bot.send_message(op['cid'], f"{esito}!\nAsset: `{op['simbolo']}`\nPrezzo: `{p:.4f}`")
                        cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
            conn.commit(); cursor.close(); conn.close()
        except Exception as e: print(f"Errore in monitora_tp_sl: {e}")
        time.sleep(60)

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
        if asset == "CHIUSO": bot.reply_to(m, "⚠️ Mercato chiuso per questo asset.")
        elif asset:
            salva_stato_db(cid, s['capitale'], asset, 0)
            bot.reply_to(m, f"✅ Asset `{asset}` accettato! Scrivi /avvio.")
        else: bot.reply_to(m, "❌ Non trovato. Prova es: 'BTC-USD', 'EURUSD=X'")

if __name__ == "__main__":
    # Avvia i thread in background
    threading.Thread(target=avvia_porta_render, daemon=True).start()
    threading.Thread(target=monitora_tp_sl, daemon=True).start()
    
    print("Avvio bot in modalità polling...")
    
    # Infinity polling con parametri di sicurezza
    # drop_pending_updates=True elimina tutto ciò che era in coda prima dell'avvio
    bot.infinity_polling(
        skip_pending=True, 
        logger_level=None, 
        timeout=30, 
        long_polling_timeout=30
    )