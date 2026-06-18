"""
XAUUSD Asian Range Signal Bot
Telegram bot — deploy on Railway.app
Token via env variable TELEGRAM_TOKEN
"""
import os, logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import yfinance as yf

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

PIP        = 0.10
SPREAD     = 0.30
SLIPPAGE   = 0.05
SL_PIPS    = 3
RR         = (1.0, 2.0, 3.0)
ZONE_BUF   = 2.0

# ─── DONNÉES ──────────────────────────────────────────────────────────────────
def fetch_xauusd_m5(days=3):
    try:
        df = yf.download("GC=F", period=f"{days}d", interval="5m",
                         progress=False, auto_adjust=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        return df[['open','high','low','close']].dropna()
    except Exception as e:
        log.error(f"yfinance error: {e}")
        return None

# ─── ASIAN RANGE ──────────────────────────────────────────────────────────────
def get_asian_range(m5, trade_date=None):
    if trade_date is None:
        trade_date = datetime.utcnow().date()
    ts       = pd.Timestamp(trade_date)
    asian_s  = ts - pd.Timedelta(hours=2)   # 22:00 UTC veille
    asian_e  = ts + pd.Timedelta(hours=6)   # 06:00 UTC du jour
    mask     = (m5.index >= asian_s) & (m5.index < asian_e)
    if mask.sum() < 6:
        return None, None
    return float(m5['high'][mask].max()), float(m5['low'][mask].min())

# ─── SESSION ACTUELLE ─────────────────────────────────────────────────────────
def current_session():
    now_utc = datetime.utcnow()
    h = now_utc.hour + now_utc.minute / 60
    if 6 <= h < 10:
        return "London", True
    if 13 <= h < 17:
        return "NY", True
    if 10 <= h < 13:
        return "Inter-sessions", False
    if 17 <= h < 22:
        return "Fermé", False
    return "Asian", False

# ─── PRIX ACTUEL ──────────────────────────────────────────────────────────────
def get_current_price(m5):
    if m5 is None or len(m5) == 0:
        return None
    return float(m5['close'].iloc[-1])

# ─── FORMATAGE SIGNAL ─────────────────────────────────────────────────────────
def format_signal(a_hi, a_lo, price, session_name, session_active):
    entry   = round(a_lo + PIP * 0.5 + SPREAD, 2)
    sl      = round(a_lo - SL_PIPS * PIP - SLIPPAGE, 2)
    sl_dist = entry - sl
    tp1     = round(entry + sl_dist * 1.0, 2)
    tp2     = round(entry + sl_dist * 2.0, 2)
    tp3     = round(entry + sl_dist * 3.0, 2)
    dist    = round((price - entry) / PIP, 1) if price else None
    rng     = round((a_hi - a_lo) / PIP, 1)

    if session_active:
        if dist is not None and abs(dist) <= 5:
            status = "⚡ EN ZONE — SURVEILLER"
        else:
            status = f"⏳ EN ATTENTE ({dist:+.1f} pips)" if dist else "⏳ EN ATTENTE"
    else:
        status = f"🔒 {session_name} — hors fenêtre"

    now_paris = datetime.utcnow() + timedelta(hours=2)
    lines = [
        f"📊 *XAUUSD — Asian Range Long*",
        f"🕐 {now_paris.strftime('%d/%m %H:%M')} Paris | {session_name}",
        f"",
        f"*Statut :* {status}",
        f"",
        f"*Asian Range*",
        f"  High : `{a_hi:.2f}` | Low : `{a_lo:.2f}` | Range : `{rng} pips`",
        f"  Prix actuel : `{price:.2f}`",
        f"",
        f"*Niveaux*",
        f"  🟢 Entrée : `{entry:.2f}`",
        f"  🎯 TP1 : `{tp1:.2f}` (1:1)",
        f"  🎯 TP2 : `{tp2:.2f}` (1:2)",
        f"  🎯 TP3 : `{tp3:.2f}` (1:3)",
        f"  🔴 SL  : `{sl:.2f}`",
        f"",
        f"*Stats backtest* (5 ans)",
        f"  WR : 58.3% | EV : +0.66R | 5/5 ans ✅",
    ]
    return "\n".join(lines)

# ─── COMMANDES ────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *XAUUSD Signal Bot*\n\n"
        "Commandes disponibles :\n"
        "  /signal — signal Asian Range du jour\n"
        "  /status — prix actuel + distance entrée\n"
        "  /help   — aide\n\n"
        "_Données : Gold Futures (GC=F) via yfinance_"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Calcul en cours...", parse_mode='Markdown')
    m5 = fetch_xauusd_m5(days=3)
    if m5 is None or len(m5) < 20:
        await update.message.reply_text("❌ Impossible de récupérer les données.")
        return
    a_hi, a_lo = get_asian_range(m5)
    if a_hi is None:
        await update.message.reply_text("❌ Asian Range introuvable (données insuffisantes).")
        return
    price = get_current_price(m5)
    session_name, session_active = current_session()
    msg = format_signal(a_hi, a_lo, price, session_name, session_active)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m5 = fetch_xauusd_m5(days=3)
    if m5 is None:
        await update.message.reply_text("❌ Données indisponibles.")
        return
    price    = get_current_price(m5)
    a_hi, a_lo = get_asian_range(m5)
    session_name, session_active = current_session()
    now_paris = datetime.utcnow() + timedelta(hours=2)

    if a_hi and a_lo:
        entry = round(a_lo + PIP * 0.5 + SPREAD, 2)
        dist  = round((price - entry) / PIP, 1)
        rng   = round((a_hi - a_lo) / PIP, 1)
        msg = (
            f"📍 *XAUUSD Status*\n"
            f"🕐 {now_paris.strftime('%H:%M')} Paris | {session_name}\n\n"
            f"Prix : `{price:.2f}`\n"
            f"Entrée : `{entry:.2f}` ({dist:+.1f} pips)\n"
            f"Asian Low : `{a_lo:.2f}` | High : `{a_hi:.2f}`\n"
            f"Range : `{rng} pips`\n"
            f"Session active : {'✅' if session_active else '❌'}"
        )
    else:
        msg = f"📍 Prix actuel : `{price:.2f}`\n🕐 {session_name}"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *Aide — XAUUSD Signal Bot*\n\n"
        "*/signal* — Signal complet :\n"
        "  Asian Range, niveaux entry/SL/TP, statut session\n\n"
        "*/status* — Résumé rapide :\n"
        "  Prix actuel + distance de la zone d'entrée\n\n"
        "_Stratégie : Long sur retest Asian Low en London (08h-12h Paris) ou NY (15h-19h Paris)_\n"
        "_WR backtest 5 ans : 58.3%_"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN manquant dans les variables d'environnement")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))
    log.info("Bot démarré — polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
