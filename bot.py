"""
Steam Deals Telegram Bot
- Invio automatico ogni mattina (via GitHub Actions)
- Comandi interattivi (via polling, quando avviato manualmente)
"""

import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CHEAPSHARK_URL = "https://www.cheapshark.com/api/1.0/deals"

# ---------------------------------------------------------------------------
# Steam / CheapShark API
# ---------------------------------------------------------------------------

def get_top_deals(min_savings=70, min_rating=70, page_size=8):
    params = {
        "storeID": "1",
        "pageSize": page_size,
        "sortBy": "Savings",
        "desc": "1",
        "steamRating": min_rating,
        "lowerPrice": "0.01",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    deals = r.json()
    return [d for d in deals if float(d.get("savings", 0)) >= min_savings]


def get_free_games():
    params = {
        "storeID": "1",
        "upperPrice": "0",
        "pageSize": "5",
        "sortBy": "Savings",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_extreme_deals():
    """Giochi scontati 90%+."""
    return get_top_deals(min_savings=90, min_rating=60, page_size=10)


def get_under_5_euro():
    """Offerte Steam con prezzo finale < 5€."""
    params = {
        "storeID": "1",
        "pageSize": "15",
        "sortBy": "Price",
        "upperPrice": "5",
        "lowerPrice": "0.01",
        "steamRating": "70",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()[:8]


# ---------------------------------------------------------------------------
# Formattatori messaggi
# ---------------------------------------------------------------------------

def escape(text):
    """Escape caratteri speciali per MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def deal_line(d, show_rating=False):
    title = escape(d["title"])
    normal = float(d["normalPrice"])
    sale = float(d["salePrice"])
    savings = int(float(d["savings"]))
    steam_id = d.get("steamAppID", "")
    url = f"https://store.steampowered.com/app/{steam_id}" if steam_id else "https://store.steampowered.com"

    if savings >= 90:
        badge = "🔴"
    elif savings >= 75:
        badge = "🟠"
    elif savings >= 50:
        badge = "🟡"
    else:
        badge = "🟢"

    rating_str = f" ⭐{d['steamRatingText']}" if show_rating and d.get("steamRatingText") else ""
    return (
        f"{badge} [{title}]({url})\n"
        f"   ~~€{escape(f'{normal:.2f}')}~~ → *€{escape(f'{sale:.2f}')}* \\(\\-{savings}%\\){escape(rating_str)}\n"
    )


def build_daily_message(deals, free_games):
    today = escape(datetime.now().strftime("%d/%m/%Y"))
    lines = [f"🎮 *Steam Deals — {today}*\n"]

    if free_games:
        lines.append("🎁 *GRATIS OGGI*")
        for g in free_games[:3]:
            title = escape(g["title"])
            normal = float(g["normalPrice"])
            steam_id = g.get("steamAppID", "")
            url = f"https://store.steampowered.com/app/{steam_id}" if steam_id else "https://store.steampowered.com"
            lines.append(f"• [{title}]({url}) ~~€{escape(f'{normal:.2f}')}~~ → *GRATIS*")
        lines.append("")

    if deals:
        lines.append("🔥 *TOP OFFERTE DEL GIORNO*")
        for d in deals[:8]:
            lines.append(deal_line(d))

    lines.append(f"_Aggiornato alle {escape(datetime.now().strftime('%H:%M'))}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def send_message(chat_id, text, parse_mode="MarkdownV2"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def send_plain(chat_id, text):
    send_message(chat_id, text, parse_mode=None)


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    r = requests.get(url, params=params, timeout=40)
    r.raise_for_status()
    return r.json().get("result", [])


def set_commands():
    """Registra i comandi nel menu Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "start",    "description": "Benvenuto e lista comandi"},
        {"command": "deals",    "description": "Top offerte del giorno"},
        {"command": "free",     "description": "Giochi gratuiti su Steam"},
        {"command": "extreme",  "description": "Sconti oltre il 90%"},
        {"command": "under5",   "description": "Offerte sotto i 5€"},
        {"command": "help",     "description": "Mostra tutti i comandi"},
    ]
    requests.post(url, json={"commands": commands}, timeout=10)


# ---------------------------------------------------------------------------
# Handler comandi
# ---------------------------------------------------------------------------

def handle_start(chat_id):
    msg = (
        "👋 *Ciao\\! Sono il tuo Steam Deals Bot* 🎮\n\n"
        "Ogni mattina ti mando le migliori offerte Steam\\.\n"
        "Puoi anche chiederle tu quando vuoi\\!\n\n"
        "📋 *Comandi disponibili:*\n"
        "/deals — Top offerte del giorno\n"
        "/free — Giochi gratuiti\n"
        "/extreme — Sconti 90%\\+\n"
        "/under5 — Tutto sotto 5€\n"
        "/help — Questa lista\n"
    )
    send_message(chat_id, msg)


def handle_deals(chat_id):
    send_plain(chat_id, "🔍 Cerco le offerte...")
    try:
        deals = get_top_deals()
        free = get_free_games()
        msg = build_daily_message(deals, free)
        send_message(chat_id, msg)
    except Exception as e:
        send_plain(chat_id, f"❌ Errore nel recupero offerte: {e}")


def handle_free(chat_id):
    send_plain(chat_id, "🎁 Cerco giochi gratuiti...")
    try:
        games = get_free_games()
        if not games:
            send_plain(chat_id, "😅 Nessun gioco gratuito trovato al momento.")
            return
        lines = ["🎁 *GIOCHI GRATIS SU STEAM*\n"]
        for g in games:
            title = escape(g["title"])
            normal = float(g["normalPrice"])
            steam_id = g.get("steamAppID", "")
            url = f"https://store.steampowered.com/app/{steam_id}" if steam_id else "https://store.steampowered.com"
            lines.append(f"• [{title}]({url}) ~~€{escape(f'{normal:.2f}')}~~ → *GRATIS*")
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_extreme(chat_id):
    send_plain(chat_id, "🔴 Cerco sconti oltre il 90%...")
    try:
        deals = get_extreme_deals()
        if not deals:
            send_plain(chat_id, "😅 Nessuno sconto sopra il 90% al momento.")
            return
        lines = ["🔴 *SCONTI 90%\\+*\n"]
        for d in deals:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_under5(chat_id):
    send_plain(chat_id, "💸 Cerco offerte sotto 5€...")
    try:
        deals = get_under_5_euro()
        if not deals:
            send_plain(chat_id, "😅 Nessuna offerta sotto 5€ al momento.")
            return
        lines = ["💸 *OFFERTE SOTTO 5€*\n"]
        for d in deals:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_help(chat_id):
    msg = (
        "📋 *Comandi disponibili*\n\n"
        "/deals — Top offerte del giorno \\(scontate 70%\\+\\)\n"
        "/free — Giochi temporaneamente gratuiti\n"
        "/extreme — Solo sconti oltre il 90%\n"
        "/under5 — Tutto ciò che costa meno di 5€\n"
        "/help — Mostra questa lista\n\n"
        "💡 Il bot ti manda le offerte ogni mattina in automatico\\!"
    )
    send_message(chat_id, msg)


HANDLERS = {
    "/start":   handle_start,
    "/deals":   handle_deals,
    "/free":    handle_free,
    "/extreme": handle_extreme,
    "/under5":  handle_under5,
    "/help":    handle_help,
}


# ---------------------------------------------------------------------------
# Modalità: daily (GitHub Actions) o polling (manuale)
# ---------------------------------------------------------------------------

def run_daily():
    """Invia il messaggio giornaliero. Usato da GitHub Actions."""
    print("📡 Modalità: invio giornaliero")
    deals = get_top_deals()
    free = get_free_games()
    msg = build_daily_message(deals, free)
    send_message(CHAT_ID, msg)
    print("✅ Messaggio inviato!")


def run_polling():
    """Ascolta i comandi Telegram in tempo reale."""
    print("🤖 Bot avviato in modalità polling. Ctrl+C per fermare.")
    set_commands()
    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")
                text = message.get("text", "").strip().split("@")[0]  # rimuove @botname

                if not chat_id or not text:
                    continue

                print(f"📩 Comando ricevuto: {text} da {chat_id}")
                handler = HANDLERS.get(text)
                if handler:
                    handler(chat_id)
                else:
                    send_plain(chat_id, "❓ Comando non riconosciuto. Usa /help per vedere i comandi.")

        except KeyboardInterrupt:
            print("\n👋 Bot fermato.")
            break
        except Exception as e:
            print(f"⚠️ Errore: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "polling"
    if mode == "daily":
        run_daily()
    else:
        run_polling()
