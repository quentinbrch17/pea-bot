import os
import logging
import requests
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID"))
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "-10"))
JSONBIN_KEY = os.environ.get("JSONBIN_KEY")
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID")
PARIS_TZ = pytz.timezone("Europe/Paris")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

last_alert_level_etf = None
last_btc_alert = None

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

BTC_ALERT_LEVELS = [
    {"price": 50000, "label": "📉 BTC sous 50 000€", "action": "Opportunité modérée — envisager 50€"},
    {"price": 40000, "label": "🔥 BTC sous 40 000€", "action": "Opportunité forte — envisager 100€"},
]


# ─── JSONBin ──────────────────────────────────────────────────────────────────

def default_data():
    return {
        "achats": [
            {"date": "06/04/2026", "parts": 710, "prix": 5.55, "montant": 3940.5}
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
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DCAM.PA"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, params={"interval": "1d", "range": "5d"}, timeout=10)
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if not closes:
            return None, None
        price = round(closes[-1], 4)
        prev = round(closes[-2], 4) if len(closes) > 1 else price
        change_1d = round(((price - prev) / prev) * 100, 2)
        return price, change_1d
    except Exception as e:
        logger.error(f"Erreur prix ETF: {e}")
        return None, None


# ─── Prix Crypto ──────────────────────────────────────────────────────────────

def get_crypto_prices():
    try:
        ids = ",".join(CRYPTO_HOLDINGS.keys())
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=eur",
            timeout=10
        )
        return r.json()
    except Exception as e:
        logger.error(f"Erreur crypto: {e}")
        return {}

def get_btc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur&include_24hr_change=true",
            timeout=10
        )
        data = r.json().get("bitcoin", {})
        return data.get("eur"), data.get("eur_24h_change")
    except Exception as e:
        logger.error(f"Erreur BTC: {e}")
        return None, None

def calcul_crypto(prices):
    total = 0
    details = []
    for coin_id, qty in CRYPTO_HOLDINGS.items():
        price = prices.get(coin_id, {}).get("eur", 0)
        valeur = round(qty * price, 2)
        total += valeur
        if valeur >= 0.5:
            details.append({"symbol": CRYPTO_SYMBOLS[coin_id], "valeur": valeur})
    return round(total, 2), sorted(details, key=lambda x: x["valeur"], reverse=True)


# ─── Alertes ──────────────────────────────────────────────────────────────────

def get_alert_level_etf(pct):
    if pct <= -20:
        return 4, "🔥 EXCELLENTE OPPORTUNITÉ", "Opportunité majeure — agir si liquidités disponibles"
    elif pct <= -15:
        return 3, "⚡ BONNE OPPORTUNITÉ", "Versement supplémentaire recommandé"
    elif pct <= -10:
        return 2, "🎯 OPPORTUNITÉ", "Envisager un versement supplémentaire"
    elif pct <= -5:
        return 1, "📉 Légère baisse", "Surveiller — pas d'urgence"
    return 0, None, None

def get_btc_alert_level(btc_price):
    triggered = None
    for level in BTC_ALERT_LEVELS:
        if btc_price <= level["price"]:
            triggered = level
    return triggered

def days_until_next_month():
    now = datetime.now(PARIS_TZ)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1)
    else:
        nxt = now.replace(month=now.month + 1, day=1)
    return (nxt - now).days


# ─── Flash info via RSS ───────────────────────────────────────────────────────

RSS_FEEDS = {
    "marches": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.lesechos.fr/rss/rss_marches.xml",
    ],
    "monde": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.reuters.com/Reuters/worldNews",
    ],
    "crypto": [
        "https://feeds.reuters.com/reuters/technologyNews",
        "https://www.lesechos.fr/rss/rss_finance.xml",
    ],
}

def fetch_rss(url, max_items=3):
    """Récupère les titres d'un flux RSS."""
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        titles = []
        for item in items[:max_items]:
            title = item.find("title")
            if title is not None and title.text:
                titles.append(title.text.strip())
        return titles
    except Exception as e:
        logger.error(f"Erreur RSS {url}: {e}")
        return []

def generate_flash_info():
    try:
        from deep_translator import GoogleTranslator
        today = datetime.now(PARIS_TZ).strftime("%d/%m/%Y")
        translator = GoogleTranslator(source="auto", target="fr")

        def translate(text):
            try:
                return translator.translate(text[:400])
            except:
                return text

        # Récupère les news depuis les flux RSS
        marches_titles = []
        for url in RSS_FEEDS["marches"]:
            marches_titles += fetch_rss(url, 2)
            if len(marches_titles) >= 3:
                break

        monde_titles = []
        for url in RSS_FEEDS["monde"]:
            monde_titles += fetch_rss(url, 2)
            if len(monde_titles) >= 2:
                break

        crypto_titles = []
        for url in RSS_FEEDS["crypto"]:
            t = fetch_rss(url, 3)
            # Filtre sur les titres contenant crypto/bitcoin/finance
            filtered = [x for x in t if any(k in x.lower() for k in ["bitcoin", "crypto", "bourse", "marché", "finance", "wall street", "cac", "nasdaq"])]
            crypto_titles += filtered
            if len(crypto_titles) >= 2:
                break

        lines = [f"📰 *FLASH MARCHÉS — {today}*\n"]

        lines.append("📊 *Marchés & Économie*")
        for title in marches_titles[:2]:
            lines.append(f"• {translate(title)[:120]}")

        lines.append("\n🌍 *Actu mondiale*")
        for title in monde_titles[:2]:
            lines.append(f"• {translate(title)[:120]}")

        if crypto_titles:
            lines.append("\n₿ *Crypto & Finance*")
            for title in crypto_titles[:1]:
                lines.append(f"• {translate(title)[:120]}")

        lines.append("\n💡 *Rappel*")
        lines.append("_Les news du jour n'affectent pas ta stratégie DCA long terme._")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Erreur flash info: {e}")
        return None


# ─── Jobs automatiques ────────────────────────────────────────────────────────

async def check_price(context: ContextTypes.DEFAULT_TYPE):
    global last_alert_level_etf, last_btc_alert

    data = load_data()
    total_parts, _, pru = calcul_portefeuille(data)
    if total_parts > 0:
        price, _ = get_etf_price()
        if price is not None:
            pct = round(((price - pru) / pru) * 100, 2)
            level, label, action = get_alert_level_etf(pct)
            if level > 0 and (last_alert_level_etf is None or level > last_alert_level_etf):
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"{label}\n\n📊 *Amundi PEA Monde*\nPrix : *{price}€*\nPRU : {pru}€\nVariation : *{pct:+.2f}%*\n\n💡 {action}\n\n_Continue ton DCA quoi qu'il arrive._",
                    parse_mode="Markdown"
                )
                last_alert_level_etf = level
            elif level == 0 and last_alert_level_etf and last_alert_level_etf > 0:
                last_alert_level_etf = None
                await context.bot.send_message(chat_id=CHAT_ID, text=f"✅ *ETF rebond*\nPrix : *{price}€* | Variation : *{pct:+.2f}%*", parse_mode="Markdown")

    btc_price, btc_change = get_btc_price()
    if btc_price is not None:
        alert = get_btc_alert_level(btc_price)
        alert_key = alert["price"] if alert else None
        if alert and (last_btc_alert is None or alert_key < last_btc_alert):
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"*{alert['label']}*\n\nPrix BTC : *{btc_price:,.0f}€*\nVariation 24h : {btc_change:+.2f}%\n\n💡 {alert['action']}\n\n_N'investis que ce que tu peux perdre._",
                parse_mode="Markdown"
            )
            last_btc_alert = alert_key
        elif alert is None and last_btc_alert is not None:
            last_btc_alert = None
            await context.bot.send_message(chat_id=CHAT_ID, text=f"✅ *BTC rebond*\nPrix : *{btc_price:,.0f}€*", parse_mode="Markdown")

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
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=(
            f"📋 *Résumé hebdomadaire — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
            f"{emoji} *PEA : {valeur_pea}€* ({pct_pea:+.2f}%)\nPV latente : *{pv_pea:+.2f}€*\n\n"
            f"🏦 *Livret A : {livreta}€*\n\n"
            f"₿ *Cryptos : {crypto_total}€*\n\n"
            f"━━━━━━━━━━━━━━━━━\n💰 *TOTAL : {total_patrimoine}€*\n\n"
            f"_Prochain versement dans ~{days_until_next_month()} jours_"
        ),
        parse_mode="Markdown"
    )

async def daily_flash(context: ContextTypes.DEFAULT_TYPE):
    flash = generate_flash_info()
    if flash:
        await context.bot.send_message(chat_id=CHAT_ID, text=flash, parse_mode="Markdown")


# ─── Commandes ────────────────────────────────────────────────────────────────

async def cmd_cours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    _, _, pru = calcul_portefeuille(data)
    price, change_1d = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Cours indisponible (marché fermé ou API indisponible).")
        return
    pct = round(((price - pru) / pru) * 100, 2) if pru else 0
    level, label, action = get_alert_level_etf(pct)
    emoji = "📈" if pct >= 0 else "📉"
    msg = f"{emoji} *Amundi PEA Monde*\n\nPrix : *{price}€*\nVariation 1j : {change_1d:+.2f}%\nDepuis PRU ({pru}€) : *{pct:+.2f}%*\n\n"
    msg += f"{label}\n{action}" if label else "✅ Pas d'opportunité — DCA mensuel suffit"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_parts, total_investi, pru = calcul_portefeuille(data)
    price, _ = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Cours indisponible.")
        return
    valeur = round(price * total_parts, 2)
    pv = round(valeur - total_investi, 2)
    pct = round(((price - pru) / pru) * 100, 2) if pru else 0
    emoji = "📈" if pct >= 0 else "📉"
    await update.message.reply_text(
        f"💼 *Ton PEA — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"Parts : *{total_parts}*\nPrix actuel : *{price}€*\nPRU : {pru}€\nVariation : {emoji} *{pct:+.2f}%*\n\n"
        f"Investi : {round(total_investi, 2)}€\nValeur : *{valeur}€*\nPV latente : *{pv:+.2f}€*",
        parse_mode="Markdown"
    )

async def cmd_patrimoine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Récupération des prix...")
    data = load_data()
    total_parts, total_investi, pru = calcul_portefeuille(data)
    price, _ = get_etf_price()
    crypto_prices = get_crypto_prices()
    crypto_total, crypto_details = calcul_crypto(crypto_prices)
    livreta = data.get("livreta", 0)
    if price is None:
        await update.message.reply_text("❌ Cours ETF indisponible.")
        return
    valeur_pea = round(price * total_parts, 2)
    pv_pea = round(valeur_pea - total_investi, 2)
    pct_pea = round(((price - pru) / pru) * 100, 2) if pru else 0
    total_patrimoine = round(valeur_pea + livreta + crypto_total, 2)
    emoji_pea = "📈" if pct_pea >= 0 else "📉"
    crypto_lines = "".join(f"  • {c['symbol']} : {c['valeur']}€\n" for c in crypto_details)
    await update.message.reply_text(
        f"💰 *TON PATRIMOINE — {datetime.now(PARIS_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"📈 *PEA Boursorama*\nAmundi PEA Monde — {total_parts} parts\n"
        f"Valeur : *{valeur_pea}€* {emoji_pea} {pct_pea:+.2f}%\nPV latente : *{pv_pea:+.2f}€*\n\n"
        f"🏦 *Livret A*\nSolde : *{livreta}€*\n\n"
        f"₿ *Cryptos Coinbase*\nTotal : *{crypto_total}€*\n{crypto_lines}\n"
        f"━━━━━━━━━━━━━━━━━\n💼 *TOTAL PATRIMOINE*\n*{total_patrimoine}€*",
        parse_mode="Markdown"
    )

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
    lines.append(f"\n*Total : {total_parts} parts — {round(total_investi, 2)}€*\n*PRU : {pru}€*")
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
            f"✅ *Achat enregistré*\n\n{parts} parts @ {prix}€ = {montant}€\n\n"
            f"Total parts : {total_parts}\nTotal investi : {round(total_investi, 2)}€\nNouv. PRU : {pru}€",
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
        await update.message.reply_text(f"✅ *Livret A mis à jour*\n\nSolde : *{montant}€*", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_flash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Récupération des news...")
    flash = generate_flash_info()
    if flash:
        await update.message.reply_text(flash, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Flash info indisponible pour l'instant.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *PEA Tracker Bot*\n\n"
        "📊 *Suivi*\n"
        "/patrimoine — Vue complète du patrimoine\n"
        "/cours — Prix ETF + signal\n"
        "/status — Détail PEA\n"
        "/historique — Tous les achats\n\n"
        "✏️ *Mettre à jour*\n"
        "/achat <parts> <prix>\n"
        "/livreta <montant>\n\n"
        "📰 *Flash info*\n"
        "/flash — Flash marchés à la demande\n"
        "_Flash auto lun-ven à 8h30_\n\n"
        "🔔 *Alertes auto toutes les heures*\n"
        f"ETF : baisse ≥ {ALERT_THRESHOLD}% du PRU\n"
        "BTC : prix < 50k€ ou < 40k€\n\n"
        "_Résumé patrimoine chaque lundi à 8h_",
        parse_mode="Markdown"
    )


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
    app.add_handler(CommandHandler("flash", cmd_flash))
    jq = app.job_queue
    jq.run_repeating(check_price, interval=3600, first=30)
    jq.run_daily(weekly_summary, time=time(8, 0, tzinfo=PARIS_TZ), days=(0,))
    jq.run_daily(daily_flash, time=time(8, 30, tzinfo=PARIS_TZ), days=(0, 1, 2, 3, 4))
    logger.info("Bot démarré ✅")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
