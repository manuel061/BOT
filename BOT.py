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

# --- MOTORE DI SCANSIONE ---
def calcola_heikin_ashi(df):
    ha = pd.DataFrame(index=df.index, columns=['open', 'high', 'low', 'close'])
    ha['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha.iloc[0,0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)): ha.iloc[i,0] = (ha.iloc[i-1,0] + ha.iloc[i-1,3]) / 2
    ha['high'] = df[['high','open','close']].max(axis=1)
    ha['low'] = df[['low','open','close']].min(axis=1)
    return ha

def avvia_scansione(cid):
    s = get_stato_utente(cid)
    raw = "".join(filter(str.isalnum, s['SIMBOLO'])).upper()
    fsym, tsym = (raw[:-4], raw[-4:]) if len(raw) > 4 else ("BTC", "USDT")
    bot.send_message(cid, f"🔍 *Ricerca su {fsym}/{tsym}*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30", timeout=15).json()
            df = pd.DataFrame(data["Data"]["Data"])
            ha = calcola_heikin_ashi(df)
            p = float(df['close'].iloc[-1]); sma = df['close'].rolling(window=20).mean().iloc[-1]
            tipo = "BUY" if (ha['close'].iloc[-1] > ha['open'].iloc[-1] and p > sma) else ("SELL" if (ha['close'].iloc[-1] < ha['open'].iloc[-1] and p < sma) else None)
            if tipo:
                bot.send_message(cid, f"{'🟢' if tipo=='BUY' else '🔴'} *SEGNALE {tipo}* ({s['SIMBOLO']}) - Prezzo: `{p:.2f}`", parse_mode="Markdown")
                time.sleep(300)
        except: time.sleep(60)
        time.sleep(30)

# --- COMANDI ---
@bot.message_handler(commands=['start'])
def cmd_start(m):
    bot.reply_to(m, "🤖 *BENVENUTO*\nInvia il CAPITALE.", parse_mode="Markdown")

@bot.message_handler(commands=['avvio', 'stop', 'cancella', 'reset'])
def cmd(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    c = m.text.split()[0]
    if c == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"]:
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s)
            threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
            bot.reply_to(m, "🚀 *Motore Avviato*")
        else: bot.reply_to(m, "⚠️ Configurazione incompleta.")
    elif c in ['/cancella', '/reset']:
        salva_stato_utente(m.chat.id, {"CAPITALE":0.0, "SIMBOLO":"", "ATTIVO":False}); bot.reply_to(m, "🗑️ *Resettato.*")

@bot.message_handler(func=lambda m: True)
def h(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    s = get_stato_utente(m.chat.id)
    if s["CAPITALE"] <= 0:
        try: s["CAPITALE"] = float(m.text.replace(',', '.')); salva_stato_utente(m.chat.id, s); bot.reply_to(m, "✅ Capitale preso. Invia ASSET:")
        except: bot.reply_to(m, "⚠️ Invia un numero.")
    elif s["SIMBOLO"] == "":
        s["SIMBOLO"] = m.text.strip().upper(); salva_stato_utente(m.chat.id, s); bot.reply_to(m, f"✅ `{s['SIMBOLO']}` salvato. Invia /avvio.")

if __name__ == "__main__":
    bot.remove_webhook()
    print("Bot avviato...")
    bot.infinity_polling(none_stop=True, timeout=60, long_polling_timeout=60)