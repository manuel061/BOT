import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector
from flask import Flask

# Configurazione Token
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
ID_AUTORIZZATI = [5628147908, 987654321]

# CACHE VELOCE: Mantiene in RAM i dati degli utenti per non interrogare il DB ogni volta
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

def get_stato_utente(uid):
    if uid in cache_utenti: return cache_utenti[uid] # Ritorno immediato dalla RAM
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM utenti WHERE cid = %s", (uid,))
        res = cursor.fetchone()
        conn.close()
        stato = {"CAPITALE": float(res['capitale']), "SIMBOLO": res['simbolo'], "ATTIVO": bool(res['attivo'])} if res else {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}
        cache_utenti[uid] = stato
        return stato
    except Exception as e: print(f"Errore DB lettura: {e}")
    return {"CAPITALE": 0.0, "SIMBOLO": "", "ATTIVO": False}

def salva_stato_utente(uid, s):
    cache_utenti[uid] = s # Aggiornamento istantaneo in RAM
    def _salva(): # Scrittura DB in thread separato per non bloccare il bot
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("REPLACE INTO utenti (cid, capitale, simbolo, attivo) VALUES (%s, %s, %s, %s)",
                           (uid, s["CAPITALE"], s["SIMBOLO"], int(s["ATTIVO"])))
            conn.commit()
            conn.close()
        except Exception as e: print(f"Errore DB scrittura: {e}")
    threading.Thread(target=_salva).start()

# --- CALCOLI (Invariati) ---
def calcola_heikin_ashi(df):
    ha = pd.DataFrame(index=df.index, columns=['open', 'high', 'low', 'close'])
    ha['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha.iloc[0,0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)): ha.iloc[i,0] = (ha.iloc[i-1,0] + ha.iloc[i-1,3]) / 2
    ha['high'] = df[['high','open','close']].max(axis=1)
    ha['low'] = df[['low','open','close']].min(axis=1)
    return ha

# --- MOTORE DI SCANSIONE ---
def avvia_scansione(cid):
    bot.send_message(cid, "🔍 *RICERCA OPERAZIONI ATTIVA*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            fsym, tsym = s['SIMBOLO'].split('-')
            url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()["Data"]["Data"]
                df = pd.DataFrame(data)
                ha = calcola_heikin_ashi(df)
                p = float(df['close'].iloc[-1])
                sma = df['close'].rolling(window=20).mean().iloc[-1]
                
                tipo = None
                if ha['close'].iloc[-1] > ha['open'].iloc[-1] and p > sma: tipo = "BUY"
                elif ha['close'].iloc[-1] < ha['open'].iloc[-1] and p < sma: tipo = "SELL"
                
                if tipo:
                    sl = round(p * 0.99, 2) if tipo == "BUY" else round(p * 1.01, 2)
                    tp = round(p * 1.02, 2) if tipo == "BUY" else round(p * 0.98, 2)
                    lotti = max(0.01, round((s["CAPITALE"] * 0.02) / 100, 2))
                    
                    # Scrittura DB asincrona per velocità
                    def _insert():
                        conn = get_db()
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl) VALUES (%s, %s, %s, %s, %s)", 
                                       (cid, tipo, p, tp, sl))
                        conn.commit()
                        conn.close()
                    threading.Thread(target=_insert).start()
                    
                    em = "🟢" if tipo == "BUY" else "🔴"
                    bot.send_message(cid, f"{em} *SEGNALE {tipo}*\n💰 *Asset:* `{s['SIMBOLO']}`\n💵 *Prezzo:* `{p:.2f}`\n🎯 *TP:* `{tp:.2f}`\n🛡️ *SL:* `{sl:.2f}`\n📊 *Lotti:* `{lotti}`", parse_mode="Markdown")
                    time.sleep(300)
        except Exception as e: print(f"Errore loop: {e}")
        time.sleep(30)

# --- COMANDI E LOGICA (Invariati) ---
@bot.message_handler(commands=['start', 'avvio', 'stop', 'cancella', 'reset'])
def cmd(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    c = m.text.split()[0]
    if c == '/start': bot.reply_to(m, "🤖 *BENVENUTO*\nInvia il CAPITALE (es: 100).", parse_mode="Markdown")
    elif c == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"] != "":
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s)
            threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
    elif c == '/stop':
        s = get_stato_utente(m.chat.id); s["ATTIVO"] = False; salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, "🔴 *Motore Fermo*")
    elif c == '/cancella' or c == '/reset':
        salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False})
        bot.reply_to(m, "🗑️ *Resettato.*")

@bot.message_handler(func=lambda m: True)
def h(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0:
        try: 
            s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s)
            bot.reply_to(m, "✅ Capitale ricevuto. Ora invia l'ASSET (es: BTC-USD):")
        except: bot.reply_to(m, "⚠️ Errore: Invia un numero valido per il capitale.")
    elif s["SIMBOLO"] == "":
        s["SIMBOLO"] = m.text.strip().upper(); salva_stato_utente(m.chat.id, s)
        bot.reply_to(m, f"✅ Asset `{s['SIMBOLO']}` acquisito. Invia /avvio.", parse_mode="Markdown")
    else: bot.reply_to(m, "ℹ️ Hai già configurato tutto. Invia /avvio.")

if __name__ == "__main__":
    threading.Thread(target=lambda: Flask(__name__).run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))), daemon=True).start()
    bot.remove_webhook()
    bot.infinity_polling(none_stop=True)