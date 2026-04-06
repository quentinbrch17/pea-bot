import os
import asyncio
import logging
from datetime import datetime, time
import pytz
import yfinance as yf
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID"))
ENTRY_PRICE = float(os.environ.get("ENTRY_PRICE", "5.359"))
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "-10"))
ETF_TICKER = "DCAM.PA"  # Amundi PEA Monde sur Yahoo Finance

PARIS_TZ = pytz.timezone("Europe/Paris")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# État global pour éviter les doublons d'alertes
last_alert_level = None


def get_etf_price():
    """Récupère le cours actuel de l'ETF via Yahoo Finance."""
    try:
        ticker = yf.Ticker(ETF_TICKER)
        hist = ticker.history(period="2d")
        if hist.empty:
            return None, None
        price = round(hist["Close"].iloc[-1], 4)
        prev_price = round(hist["Close"].iloc[-2], 4) if len(hist) > 1 else price
        change_1d = round(((price - prev_price) / prev_price) * 100, 2)
        return price, change_1d
    except Exception as e:
        logger.error(f"Erreur récupération prix: {e}")
        return None, None


def get_alert_level(pct_from_entry):
    """Détermine le niveau d'alerte selon la variation depuis l'entrée."""
    if pct_from_entry <= -20:
        return 4, "🔥 EXCELLENTE OPPORTUNITÉ", "Opportunité majeure — agir si liquidités disponibles"
    elif pct_from_entry <= -15:
        return 3, "⚡ BONNE OPPORTUNITÉ", "Versement supplémentaire recommandé"
    elif pct_from_entry <= -10:
        return 2, "🎯 OPPORTUNITÉ", "Envisager un versement supplémentaire"
    elif pct_from_entry <= -5:
        return 1, "📉 Légère baisse", "Surveiller — pas d'urgence"
    else:
        return 0, None, None


async def send_alert(bot, price, pct_from_entry, label, action):
    """Envoie une alerte Telegram."""
    seuil_price = round(ENTRY_PRICE * (1 + ALERT_THRESHOLD / 100), 4)
    msg = (
        f"{label}\n\n"
        f"📊 *Amundi PEA Monde* (FR001400U5Q4)\n"
        f"Prix actuel : *{price}€*\n"
        f"Prix d'entrée : {ENTRY_PRICE}€\n"
        f"Variation : *{pct_from_entry:+.2f}%*\n\n"
        f"💡 {action}\n\n"
        f"_Rappel : continue ton DCA mensuel quoi qu'il arrive._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")


async def check_price(context: ContextTypes.DEFAULT_TYPE):
    """Vérifie le prix et envoie une alerte si nécessaire."""
    global last_alert_level
    bot = context.bot

    price, change_1d = get_etf_price()
    if price is None:
        logger.warning("Impossible de récupérer le prix")
        return

    pct_from_entry = round(((price - ENTRY_PRICE) / ENTRY_PRICE) * 100, 2)
    level, label, action = get_alert_level(pct_from_entry)

    # N'envoie l'alerte que si on passe à un nouveau niveau plus bas
    if level > 0 and (last_alert_level is None or level > last_alert_level):
        await send_alert(context.bot, price, pct_from_entry, label, action)
        last_alert_level = level
        logger.info(f"Alerte envoyée niveau {level}: {price}€ ({pct_from_entry:+.2f}%)")
    elif level == 0 and last_alert_level is not None and last_alert_level > 0:
        # Rebond au-dessus du seuil — reset
        last_alert_level = None
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"✅ *Rebond détecté*\n\nAmundi PEA Monde : *{price}€*\nVariation depuis entrée : *{pct_from_entry:+.2f}%*\n\nLe cours est repassé au-dessus du seuil d'alerte.",
            parse_mode="Markdown"
        )

    logger.info(f"Prix vérifié: {price}€ ({pct_from_entry:+.2f}% depuis entrée)")


async def weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """Résumé hebdomadaire chaque lundi matin."""
    price, change_1d = get_etf_price()
    if price is None:
        return

    pct_from_entry = round(((price - ENTRY_PRICE) / ENTRY_PRICE) * 100, 2)
    nb_parts = 710
    valeur_totale = round(price * nb_parts, 2)
    investi = round(ENTRY_PRICE * nb_parts, 2)
    plus_value = round(valeur_totale - investi, 2)

    emoji = "📈" if pct_from_entry >= 0 else "📉"
    msg = (
        f"📋 *Résumé hebdomadaire PEA*\n\n"
        f"{emoji} *Amundi PEA Monde*\n"
        f"Prix actuel : *{price}€*\n"
        f"Variation hier : {change_1d:+.2f}%\n"
        f"Variation depuis entrée : *{pct_from_entry:+.2f}%*\n\n"
        f"💼 *Ton portefeuille*\n"
        f"Parts : 710\n"
        f"Valeur totale : *{valeur_totale}€*\n"
        f"Investi : {investi}€\n"
        f"Plus-value latente : *{plus_value:+.2f}€*\n\n"
        f"_Prochain versement mensuel : dans ~{days_until_next_month()} jours_"
    )
    await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")


def days_until_next_month():
    """Calcule les jours jusqu'au début du mois prochain."""
    now = datetime.now(PARIS_TZ)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_month = now.replace(month=now.month + 1, day=1)
    return (next_month - now).days


# Commandes Telegram
async def cmd_cours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cours — affiche le prix actuel"""
    price, change_1d = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Impossible de récupérer le cours pour l'instant.")
        return

    pct_from_entry = round(((price - ENTRY_PRICE) / ENTRY_PRICE) * 100, 2)
    niveau = get_alert_level(pct_from_entry)
    emoji = "📈" if pct_from_entry >= 0 else "📉"

    msg = (
        f"{emoji} *Amundi PEA Monde*\n\n"
        f"Prix : *{price}€*\n"
        f"Variation 1j : {change_1d:+.2f}%\n"
        f"Depuis entrée ({ENTRY_PRICE}€) : *{pct_from_entry:+.2f}%*\n\n"
    )
    if niveau[1]:
        msg += f"{niveau[1]}\n{niveau[2]}"
    else:
        msg += "✅ Pas d'opportunité — DCA mensuel suffit"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — résumé du portefeuille"""
    price, change_1d = get_etf_price()
    if price is None:
        await update.message.reply_text("❌ Impossible de récupérer le cours.")
        return

    nb_parts = 710
    valeur = round(price * nb_parts, 2)
    investi = round(ENTRY_PRICE * nb_parts, 2)
    pv = round(valeur - investi, 2)
    pct = round(((price - ENTRY_PRICE) / ENTRY_PRICE) * 100, 2)

    msg = (
        f"💼 *Ton PEA*\n\n"
        f"ETF : Amundi PEA Monde\n"
        f"Parts : 710\n"
        f"Prix actuel : *{price}€*\n"
        f"Prix entrée : {ENTRY_PRICE}€\n"
        f"Variation : *{pct:+.2f}%*\n\n"
        f"Valeur totale : *{valeur}€*\n"
        f"Investi : {investi}€\n"
        f"Plus-value latente : *{pv:+.2f}€*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — liste des commandes"""
    msg = (
        "🤖 *PEA Tracker Bot*\n\n"
        "Commandes disponibles :\n\n"
        "/cours — Prix actuel + alerte si opportunité\n"
        "/status — Résumé de ton portefeuille\n"
        "/help — Cette aide\n\n"
        f"_Seuil d'alerte : {ALERT_THRESHOLD}% depuis l'entrée_\n"
        f"_Vérification automatique toutes les heures_\n"
        f"_Résumé hebdomadaire chaque lundi à 8h_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("cours", cmd_cours))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    # Jobs récurrents
    job_queue = app.job_queue

    # Vérification toutes les heures (jours ouvrés 9h-18h Paris)
    job_queue.run_repeating(check_price, interval=3600, first=10)

    # Résumé hebdomadaire lundi à 8h
    job_queue.run_daily(
        weekly_summary,
        time=time(8, 0, tzinfo=PARIS_TZ),
        days=(0,)  # Lundi
    )

    logger.info("Bot démarré ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
