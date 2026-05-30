import telebot, requests, pandas as pd, numpy as np, time, threading, os, mysql.connector
from flask import Flask

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

# --- MONITORAGGIO TP/SL ---
def monitora_operazioni():
    while True:
        try:
            conn = get_db(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM operazioni WHERE chiusa = 0")
            for op in cursor.fetchall():
                sym = "".join(filter(str.isalnum, op['simbolo'])).upper()
                fsym = sym[:-4] if len(sym) > 4 else "BTC"
                tsym = sym[-4:] if len(sym) > 4 else "USDT"
                url = f"https://min-api.cryptocompare.com/data/price?fsym={fsym}&tsym={tsym}"
                p_attuale = float(requests.get(url, timeout=10).json().get(tsym, 0))
                msg = None
                if op['tipo'] == "BUY":
                    if p_attuale >= op['tp']: msg = f"✅ *TP RAGGIUNTO!* ({op['simbolo']})"
                    elif p_attuale <= op['sl']: msg = f"❌ *SL COLPITO!* ({op['simbolo']})"
                else:
                    if p_attuale <= op['tp']: msg = f"✅ *TP RAGGIUNTO!* ({op['simbolo']})"
                    elif p_attuale >= op['sl']: msg = f"❌ *SL COLPITO!* ({op['simbolo']})"
                if msg:
                    bot.send_message(op['cid'], f"{msg}\nPrezzo: `{p_attuale:.2f}`", parse_mode="Markdown")
                    cursor.execute("UPDATE operazioni SET chiusa = 1 WHERE id = %s", (op['id'],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(60)

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
    if raw.endswith("USDT"): fsym, tsym = raw[:-4], "USDT"
    elif raw.endswith("USD"): fsym, tsym = raw[:-3], "USD"
    else: fsym, tsym = raw, "USDT"
    
    try:
        url = f"https://min-api.cryptocompare.com/data/price?fsym={fsym}&tsym={tsym}"
        test = requests.get(url, timeout=15).json()
        if "Response" in test and test["Response"] == "Error": raise Exception(test.get("Message"))
    except Exception as e:
        bot.send_message(cid, f"❌ *Errore:* `{e}`")
        return

    bot.send_message(cid, f"🔍 *Analisi su {fsym}/{tsym} avviata*", parse_mode="Markdown")
    while True:
        s = get_stato_utente(cid)
        if not s.get("ATTIVO"): break
        try:
            data = requests.get(f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym={tsym}&limit=30", timeout=15).json()
            if data.get("Response") == "Error": raise Exception("Dati non disponibili")
            df = pd.DataFrame(data["Data"]["Data"])
            ha = calcola_heikin_ashi(df)
            p = float(df['close'].iloc[-1]); sma = df['close'].rolling(window=20).mean().iloc[-1]
            tipo = "BUY" if (ha['close'].iloc[-1] > ha['open'].iloc[-1] and p > sma) else ("SELL" if (ha['close'].iloc[-1] < ha['open'].iloc[-1] and p < sma) else None)
            if tipo:
                sl = round(p * 0.99, 2) if tipo == "BUY" else round(p * 1.01, 2)
                tp = round(p * 1.02, 2) if tipo == "BUY" else round(p * 0.98, 2)
                def _ins():
                    try:
                        conn = get_db(); cursor = conn.cursor()
                        cursor.execute("INSERT INTO operazioni (cid, tipo, entrata, tp, sl, simbolo, chiusa) VALUES (%s, %s, %s, %s, %s, %s, 0)", (cid, tipo, p, tp, sl, s['SIMBOLO']))
                        conn.commit(); conn.close()
                    except: pass
                threading.Thread(target=_ins).start()
                bot.send_message(cid, f"{'🟢' if tipo=='BUY' else '🔴'} *SEGNALE {tipo}*\n💰 *Asset:* `{s['SIMBOLO']}`\n💵 *Entrata:* `{p:.2f}`\n🎯 *TP:* `{tp:.2f}`\n🛡️ *SL:* `{sl:.2f}`", parse_mode="Markdown")
                time.sleep(300)
        except: time.sleep(60)
        time.sleep(30)

@bot.message_handler(commands=['start', 'avvio', 'stop', 'cancella', 'reset'])
def cmd(m):
    if m.chat.id not in ID_AUTORIZZATI: return
    c = m.text.split()[0]
    if c == '/avvio':
        s = get_stato_utente(m.chat.id)
        if s["CAPITALE"] > 0 and s["SIMBOLO"]:
            s["ATTIVO"] = True; salva_stato_utente(m.chat.id, s)
            threading.Thread(target=avvia_scansione, args=(m.chat.id,), daemon=True).start()
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
    threading.Thread(target=monitora_operazioni, daemon=True).start()
    threading.Thread(target=lambda: Flask(__name__).run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))), daemon=True).start()
    bot.infinity_polling(none_stop=True, timeout=60, long_polling_timeout=60)