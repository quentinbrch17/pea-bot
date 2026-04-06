import os
import logging
import requests
from datetime import datetime, time
import pytz
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID"))
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "-10"))
JSONBIN_KEY = os.environ.get("JSONBIN_KEY")
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID")
ETF_TICKER = "DCAM.PA"
PARIS_TZ = pytz.timezone("Europe/Paris")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

last_alert_level = None

# Quantités crypto fixes (Coinbase)
CRYPTO_HOLDINGS = {
    "bitcoin": 0.00094,
    "ethereum": 0.01075,
    "solana": 0.07887,
    "bitcoin-cash": 0.008816,
    "stellar": 19.60,
    "litecoin": 0.046,
    "cardano": 9.08,
}

CRYPTO_SYMBOLS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "bitcoin-cash": "BCH",
    "stellar": "XLM",
    "litecoin": "LTC",
    "cardano": "ADA",
}


# ─── JSONBin ──────────────────────────────────────────────────────────────────

def default_data():
    return {
        "achats": [
            {"date": "06/04/2026", "parts": 92, "prix": 5.359, "montant": 493.03},
            {"date": "06/04/2026", "parts": 618, "prix": 5.359, "montant": 3311.86},
        ],
        "livreta": 10000.11
    }

def load_data():
    try:
        r = requests.get(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
            headers={"X-Master-Key": JSONBIN_KEY},
            timeout=10
        )
        data = r.json().get("record", default_data())
        if "livreta" not in data:
            data["livreta"] = 10000.11
        return data
    except Exception as e:
        logger.error(f"Erreur JSONBin load: {e}")
        return default_data()

def save_data(data):
    try:
        requests.put(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
            headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"},
            json=data,
            timeout=10
        )
    except Exception as e:
        logger.error(f"Erreur JSONBin save: {e}")

def calcul_portefeuille(data):
    achats = data.get("achats", [])
    if not achats:
        return 0, 0, 0
    total_parts = sum(a["parts"] for a in achats)
    total_investi = sum(a["montant"] for a in achats)
    pru = round(total_investi / total_parts, 4) if total_parts > 0 else 0
    return total_parts, total_investi, pru


# ─── Prix ETF ─────────────────────────────────────────────────────────────────

def get_etf_price():
    try:
        ticker = yf.Ticker(ETF_TICKER)
        hist = ticker.history(period="5d")
        if hist.empty:
            return None, None
        price = round(float(hist["Close"].iloc[-1]), 4)
        prev = round(float(hist["Close"].iloc[-2]), 4) if len(hist) > 1 else price
        change_1d = round(((price - prev) / prev) * 100, 2)
        return price, change_1d
    except Exception as e:
        logger.error(f"Erreur prix ETF: {e}")
        return None, None


# ─── Prix Crypto (CoinGecko) ──────────────────────────────────────────────────

def get_crypto_prices():
    try:
        ids = ",".join(CRYPTO_HOLDINGS.keys())
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=eur",
            timeout=10
        )
        return r.json()
    except Exception as e:
        logger.error(f"Erreur prix crypto: {e}")
        return {}

def calcul_crypto(prices):
    total = 0
    details = []
    for coin_id, qty in CRYPTO_HOLDINGS.items():
        price = prices.get(coin_id, {}).get("eur", 0)
        valeur = round(qty * price, 2)
        total += valeur
        if valeur >= 0.5:
            details.append({
                "symbol": CRYPTO_SYMBOLS[coin_id],
                "qty": qty,
                "price": price,
                "valeur": valeur
            })
    return round(total, 2), sorted(details, key=lambda x: x["valeur"], reverse=True)


# ─── Alertes ──────────────────────────────────────────────────────────────────

def get_alert_level(pct):
    if pct <= -20:
        return 4, "🔥 EXCELLENTE OPPORTUNITÉ", "Opportunité majeure — agir si liquidités disponibles"
    elif pct <= -15:
        return 3, "⚡ BONNE OPPORTUNITÉ", "Versement supplémentaire recommandé"
    elif pct <= -10:
        return 2, "🎯 OPPORTUNITÉ", "Envisager un versement supplémentaire"
    elif pct <= -5:
        return 1, "📉 Légère baisse", "Surveiller — pas d'urgence"
    return 0, None, None

def days_until_next_month():
    now = datetime.now(PARIS_TZ)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1)
    else:
        nxt = now.replace(month=now.month + 1, day=1)
    return (nxt - now).days


# ─── Jobs automatiques ────────────────────────────────────────────────────────

async def check_price(context: ContextTypes.DEFAULT_TYPE):
    global last_alert_level
    data = load_data()
    total_parts, _, pru = calcul_portefeuille(data)
    if total_parts == 0:
        return
    price, _ = get_etf_price()
    if price is None:
        return
    pct = round(((price - pru) / pru) * 100, 2)
    level, label, action = get_alert_level(pct)
    if level > 0 and (last_alert_level is None or level > last_alert_level):
        msg = (
            f"{label}\n\n"
            f"📊 *Amundi PEA Monde*\n"
            f"Prix actuel : *{price}€*\n"
            f"Prix de revient : {pru}€\n"
            f"Variation : *{pct:+.2f}%*\n\n"
            f"💡 {action}\n\n"
            f"_Continue ton DCA mensuel quoi qu'il arrive._"
        )
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        last_alert_level = level
    elif level == 0 and last_alert_level and last_alert_level > 0:
        last_alert_level = None
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"✅ *Rebond détecté*\n\nPrix : *{price}€*\nVariation : *{pct:+.2f}%*\nRepassé au-dessus du seuil.",
            parse_mode="Markdown"
        )

async def weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_parts, total_investi, pru = calcul_portefeuille(data)
    price, change_1d = get_etf_price()
    crypto_prices = get_crypto_prices()
    crypto_total, _ = calcul_crypto(crypto_prices)
    livreta = data.get("livreta", 0)

    if price is None or total_parts == 0:
        return

    valeur_pea = round(price * total_parts, 2)
    pv_pea = round(valeur_pea - total_investi, 2)
    pct_pea = round(((price - pru) / pru) * 100, 2)
    total_patrimoine = round(valeur_pea + livreta + crypto_total, 2)
    emoji = "📈" if pct_pea >= 0 else "📉"

    msg = (
        f"📋 *Résumé hebdomadaire — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"{emoji} *PEA : {valeur_pea}€*\n"
        f"Variation PRU : *{pct_pea:+.2f}%* | PV : *{pv_pea:+.2f}€*\n\n"
        f"🏦 *Livret A : {livreta}€*\n\n"
        f"₿ *Cryptos : {crypto_total}€*\n\n"
        f"─────────────────\n"
        f"💰 *TOTAL : {total_patrimoine}€*\n\n"
        f"_Prochain versement PEA dans ~{days_until_next_month()} jours_"
    )
    await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")


# ─── Commandes ────────────────────────────────────────────────────────────────

async def cmd_cours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    _, _, pru = calcul_portefeuille(data)
    price, change_1d = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Impossible de récupérer le cours.")
        return
    pct = round(((price - pru) / pru) * 100, 2) if pru else 0
    level, label, action = get_alert_level(pct)
    emoji = "📈" if pct >= 0 else "📉"
    msg = (
        f"{emoji} *Amundi PEA Monde*\n\n"
        f"Prix : *{price}€*\n"
        f"Variation 1j : {change_1d:+.2f}%\n"
        f"Depuis PRU ({pru}€) : *{pct:+.2f}%*\n\n"
    )
    msg += f"{label}\n{action}" if label else "✅ Pas d'opportunité — DCA mensuel suffit"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_parts, total_investi, pru = calcul_portefeuille(data)
    price, _ = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Impossible de récupérer le cours.")
        return
    valeur = round(price * total_parts, 2)
    pv = round(valeur - total_investi, 2)
    pct = round(((price - pru) / pru) * 100, 2) if pru else 0
    emoji = "📈" if pct >= 0 else "📉"
    msg = (
        f"💼 *Ton PEA — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"Parts : *{total_parts}*\n"
        f"Prix actuel : *{price}€*\n"
        f"Prix de revient : {pru}€\n"
        f"Variation : {emoji} *{pct:+.2f}%*\n\n"
        f"Total investi : {round(total_investi, 2)}€\n"
        f"Valeur actuelle : *{valeur}€*\n"
        f"Plus-value latente : *{pv:+.2f}€*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_patrimoine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Récupération des prix en cours...")

    data = load_data()
    total_parts, total_investi, pru = calcul_portefeuille(data)
    price, change_1d = get_etf_price()
    crypto_prices = get_crypto_prices()
    crypto_total, crypto_details = calcul_crypto(crypto_prices)
    livreta = data.get("livreta", 0)

    if price is None:
        await update.message.reply_text("❌ Impossible de récupérer les prix.")
        return

    valeur_pea = round(price * total_parts, 2)
    pv_pea = round(valeur_pea - total_investi, 2)
    pct_pea = round(((price - pru) / pru) * 100, 2) if pru else 0
    total_patrimoine = round(valeur_pea + livreta + crypto_total, 2)
    emoji_pea = "📈" if pct_pea >= 0 else "📉"

    # Ligne cryptos
    crypto_lines = ""
    for c in crypto_details:
        crypto_lines += f"  • {c['symbol']} : {c['valeur']}€\n"

    msg = (
        f"💰 *TON PATRIMOINE — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"📈 *PEA Boursorama*\n"
        f"Amundi PEA Monde — {total_parts} parts\n"
        f"Valeur : *{valeur_pea}€* {emoji_pea} {pct_pea:+.2f}%\n"
        f"Plus-value latente : *{pv_pea:+.2f}€*\n\n"
        f"🏦 *Livret A*\n"
        f"Solde : *{livreta}€*\n\n"
        f"₿ *Cryptos Coinbase*\n"
        f"Total : *{crypto_total}€*\n"
        f"{crypto_lines}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💼 *TOTAL PATRIMOINE*\n"
        f"*{total_patrimoine}€*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_historique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    achats = data.get("achats", [])
    if not achats:
        await update.message.reply_text("Aucun achat enregistré.")
        return
    lines = ["📅 *Historique des achats PEA*\n"]
    for a in achats:
        lines.append(f"• {a['date']} — {a['parts']} parts @ {a['prix']}€ = {a['montant']}€")
    total_parts, total_investi, pru = calcul_portefeuille(data)
    lines.append(f"\n*Total : {total_parts} parts — {round(total_investi, 2)}€ investis*")
    lines.append(f"*PRU : {pru}€*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_achat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage : /achat <parts> <prix>\nEx: /achat 75 5.20")
            return
        parts = int(args[0])
        prix = float(args[1])
        montant = round(parts * prix, 2)
        date = datetime.now(PARIS_TZ).strftime("%d/%m/%Y")
        data = load_data()
        data["achats"].append({"date": date, "parts": parts, "prix": prix, "montant": montant})
        save_data(data)
        total_parts, total_investi, pru = calcul_portefeuille(data)
        await update.message.reply_text(
            f"✅ *Achat enregistré*\n\n"
            f"{parts} parts @ {prix}€ = {montant}€\n\n"
            f"*Portefeuille mis à jour :*\n"
            f"Total parts : {total_parts}\n"
            f"Total investi : {round(total_investi, 2)}€\n"
            f"Nouveau PRU : {pru}€",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_livreta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) != 1:
            await update.message.reply_text("Usage : /livreta <montant>\nEx: /livreta 10250")
            return
        montant = float(args[0])
        data = load_data()
        data["livreta"] = montant
        save_data(data)
        await update.message.reply_text(
            f"✅ *Livret A mis à jour*\n\nSolde : *{montant}€*",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *PEA Tracker Bot*\n\n"
        "📊 *Suivi*\n"
        "/patrimoine — Vue complète de tout ton patrimoine\n"
        "/cours — Prix ETF + signal opportunité\n"
        "/status — Détail du PEA\n"
        "/historique — Tous tes achats ETF\n\n"
        "✏️ *Mettre à jour*\n"
        "/achat <parts> <prix> — Enregistrer un achat ETF\n"
        "/livreta <montant> — Mettre à jour le Livret A\n\n"
        f"_Seuil d'alerte ETF : {ALERT_THRESHOLD}%_\n"
        "_Vérification auto : toutes les heures_\n"
        "_Résumé : chaque lundi à 8h_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cours", cmd_cours))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("patrimoine", cmd_patrimoine))
    app.add_handler(CommandHandler("historique", cmd_historique))
    app.add_handler(CommandHandler("achat", cmd_achat))
    app.add_handler(CommandHandler("livreta", cmd_livreta))
    jq = app.job_queue
    jq.run_repeating(check_price, interval=3600, first=30)
    jq.run_daily(weekly_summary, time=time(8, 0, tzinfo=PARIS_TZ), days=(0,))
    logger.info("Bot démarré ✅")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
