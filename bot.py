"""
Steam Deals Telegram Bot
- Invio automatico ogni mattina (via GitHub Actions)
- Comandi interattivi (via polling, quando avviato manualmente)
"""

import os
import sys
import json
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CHEAPSHARK_URL = "https://www.cheapshark.com/api/1.0/deals"
MESSAGE_IDS_FILE = "message_ids.json"

# ---------------------------------------------------------------------------
# Steam / CheapShark API
# ---------------------------------------------------------------------------

def fetch_deals(page_size=60, upper_price=None, lower_price="0.01"):
    params = {
        "storeID": "1",
        "pageSize": page_size,
        "onSale": "1",
    }
    if upper_price is not None:
        params["upperPrice"] = upper_price
    if lower_price:
        params["lowerPrice"] = lower_price
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def score(d):
    """Risparmio in euro pesato per rating Steam. Premia giochi costosi e ben recensiti."""
    normal = float(d.get("normalPrice", 0))
    sale = float(d.get("salePrice", 0))
    saved = normal - sale
    rating = float(d.get("steamRatingPercent", 70)) / 100
    return saved * (0.5 + rating)


def get_all_on_sale(page_size=60):
    deals = fetch_deals(page_size=page_size)
    return [d for d in deals if float(d.get("savings", 0)) > 0]


def get_free_games():
    deals = fetch_deals(page_size=15, upper_price="0", lower_price=None)
    deals.sort(key=lambda d: float(d.get("normalPrice", 0)), reverse=True)
    return deals


def get_god_tier(min_original=20.0, min_savings_pct=60):
    """Giochi di peso (prezzo originale alto) con sconto significativo."""
    deals = get_all_on_sale(page_size=60)
    filtered = [
        d for d in deals
        if float(d.get("normalPrice", 0)) >= min_original
        and float(d.get("savings", 0)) >= min_savings_pct
    ]
    filtered.sort(key=score, reverse=True)
    return filtered


def get_best_value(min_savings_pct=50, exclude_god_tier=True):
    """Top offerte per score, esclusi i God Tier."""
    deals = get_all_on_sale(page_size=60)
    filtered = [d for d in deals if float(d.get("savings", 0)) >= min_savings_pct]
    if exclude_god_tier:
        filtered = [
            d for d in filtered
            if not (float(d.get("normalPrice", 0)) >= 20.0
                    and float(d.get("savings", 0)) >= 60)
        ]
    filtered.sort(key=score, reverse=True)
    return filtered


def get_hidden_gems(max_rating_count=500, min_savings_pct=50):
    """Indie poco noti con sconto alto e rating buono."""
    deals = get_all_on_sale(page_size=60)
    filtered = [
        d for d in deals
        if float(d.get("savings", 0)) >= min_savings_pct
        and int(d.get("steamRatingCount", 9999)) <= max_rating_count
        and int(d.get("steamRatingCount", 0)) > 10
        and float(d.get("steamRatingPercent", 0)) >= 70
    ]
    filtered.sort(key=score, reverse=True)
    return filtered


def get_cheap_gems(max_price=3.0):
    """Giochi ben recensiti sotto €3 che normalmente costano di più."""
    deals = get_all_on_sale(page_size=60)
    filtered = [
        d for d in deals
        if float(d.get("salePrice", 99)) <= max_price
        and float(d.get("steamRatingPercent", 0)) >= 75
        and float(d.get("normalPrice", 0)) >= 5
    ]
    filtered.sort(key=lambda d: float(d.get("steamRatingPercent", 0)), reverse=True)
    return filtered


def get_top_savings():
    """Top per risparmio assoluto in euro."""
    deals = get_all_on_sale(page_size=60)
    filtered = [d for d in deals if float(d.get("savings", 0)) >= 40]
    filtered.sort(
        key=lambda d: float(d.get("normalPrice", 0)) - float(d.get("salePrice", 0)),
        reverse=True
    )
    return filtered


# ---------------------------------------------------------------------------
# Formattatori
# ---------------------------------------------------------------------------

def h(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def steam_url(d):
    sid = d.get("steamAppID", "")
    return f"https://store.steampowered.com/app/{sid}" if sid else "https://store.steampowered.com"


def deal_line(d):
    title = h(d["title"])
    normal = float(d["normalPrice"])
    sale = float(d["salePrice"])
    savings_pct = int(float(d["savings"]))
    saved_eur = normal - sale
    rating = d.get("steamRatingPercent", "?")
    url = steam_url(d)
    rating_str = f" · {rating}%" if rating != "?" else ""

    return (
        f'<a href="{url}">{title}</a>\n'
        f'<s>€{normal:.2f}</s> → <b>€{sale:.2f}</b>  <b>-{savings_pct}%</b>  risparmi €{saved_eur:.2f}{rating_str}\n'
    )


def build_daily_message(god_tier, free_games, best_value):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"🎮 <b>Steam Deals — {today}</b>\n"]

    if god_tier:
        lines.append("🏆 <b>GOD TIER</b> — occasioni da non perdere")
        lines.append("<i>Giochi &gt;€20 scontati &gt;60%, per risparmio reale</i>")
        for d in god_tier[:6]:
            lines.append(deal_line(d))
    else:
        lines.append("🏆 <b>GOD TIER</b> — nessuna occasione oggi\n")

    if free_games:
        lines.append("🎁 <b>GRATIS OGGI</b>")
        for g in free_games[:4]:
            title = h(g["title"])
            normal = float(g["normalPrice"])
            url = steam_url(g)
            lines.append(f'• <a href="{url}">{title}</a>  <s>€{normal:.2f}</s> → <b>GRATIS</b>')
        lines.append("")

    if best_value:
        lines.append("💎 <b>BEST VALUE</b> — miglior rapporto qualità/sconto")
        for d in best_value[:6]:
            lines.append(deal_line(d))

    lines.append(f"<i>Aggiornato alle {datetime.now().strftime('%H:%M')}</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def send_message(chat_id, text, parse_mode="HTML"):
    if len(text) > 4000:
        text = text[:3990] + "\n<i>... (lista troncata)</i>"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
        "link_preview_options": {"is_disabled": True},
    }
    if parse_mode is None:
        del payload["parse_mode"]

    r = requests.post(url, json=payload, timeout=10)

    if r.status_code == 400 and parse_mode == "HTML":
        print(f"⚠️ Errore HTML, riprovo plain. Risposta: {r.text}")
        plain = re.sub(r'<a href="[^"]*">([^<]*)</a>', r'\1', text)
        plain = re.sub(r'<[^>]+>', '', plain)
        payload2 = {"chat_id": chat_id, "text": plain, "disable_web_page_preview": True}
        r = requests.post(url, json=payload2, timeout=10)

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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "deals",   "description": "Digest giornaliero completo"},
        {"command": "godtier", "description": "Giochi costosi in super sconto"},
        {"command": "free",    "description": "Giochi gratuiti oggi"},
        {"command": "gems",    "description": "Indie nascosti da scoprire"},
        {"command": "cheap",   "description": "Giochi buoni sotto 3 euro"},
        {"command": "savings", "description": "Top risparmio assoluto in euro"},
        {"command": "help",    "description": "Lista comandi"},
    ]
    requests.post(url, json={"commands": commands}, timeout=10)


# ---------------------------------------------------------------------------
# Handler comandi
# ---------------------------------------------------------------------------

def handle_start(chat_id):
    msg = (
        "👋 <b>Ciao! Sono il tuo Steam Deals Bot</b> 🎮\n\n"
        "Ogni mattina ti mando le migliori offerte Steam, filtrate per <b>valore reale</b>.\n\n"
        "📋 <b>Comandi:</b>\n"
        "/deals — Digest completo del giorno\n"
        "/godtier — Giochi &gt;€20 con sconto &gt;60%\n"
        "/free — Giochi gratuiti oggi\n"
        "/gems — Indie nascosti con alto sconto\n"
        "/cheap — Giochi buoni sotto €3\n"
        "/savings — Top risparmio assoluto in €\n"
        "/help — Questa lista\n"
    )
    send_message(chat_id, msg)


def handle_deals(chat_id):
    send_plain(chat_id, "🔍 Cerco le offerte del giorno...")
    try:
        god = get_god_tier()
        free = get_free_games()
        best = get_best_value()
        msg = build_daily_message(god, free, best)
        send_message(chat_id, msg)
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_godtier(chat_id):
    send_plain(chat_id, "🏆 Cerco le occasioni God Tier...")
    try:
        deals = get_god_tier()
        if not deals:
            send_plain(chat_id, "😅 Nessun gioco God Tier oggi. Riprova domani.")
            return
        lines = ["🏆 <b>GOD TIER</b> — giochi &gt;€20 con sconto &gt;60%\n"]
        for d in deals[:8]:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_free(chat_id):
    send_plain(chat_id, "🎁 Cerco giochi gratuiti...")
    try:
        games = get_free_games()
        if not games:
            send_plain(chat_id, "😅 Nessun gioco gratuito trovato al momento.")
            return
        lines = ["🎁 <b>GIOCHI GRATIS SU STEAM</b>\n"]
        for g in games[:8]:
            title = h(g["title"])
            normal = float(g["normalPrice"])
            url = steam_url(g)
            lines.append(f'• <a href="{url}">{title}</a>  <s>€{normal:.2f}</s> → <b>GRATIS</b>')
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_gems(chat_id):
    send_plain(chat_id, "💎 Cerco indie nascosti...")
    try:
        deals = get_hidden_gems()
        if not deals:
            send_plain(chat_id, "😅 Nessuna hidden gem trovata oggi.")
            return
        lines = ["💎 <b>HIDDEN GEMS</b> — indie poco noti, molto scontati\n"]
        for d in deals[:8]:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_cheap(chat_id):
    send_plain(chat_id, "🪙 Cerco giochi buoni sotto €3...")
    try:
        deals = get_cheap_gems()
        if not deals:
            send_plain(chat_id, "😅 Nessun gioco trovato sotto €3 con buon rating.")
            return
        lines = ["🪙 <b>CHEAP &amp; GOOD</b> — ottimi giochi sotto €3\n"]
        for d in deals[:8]:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_savings(chat_id):
    send_plain(chat_id, "💸 Cerco i massimi risparmi assoluti...")
    try:
        deals = get_top_savings()
        if not deals:
            send_plain(chat_id, "😅 Nessuna offerta trovata.")
            return
        lines = ["💸 <b>TOP RISPARMIO</b> — massimo risparmio in €\n"]
        for d in deals[:8]:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_help(chat_id):
    msg = (
        "📋 <b>Comandi disponibili</b>\n\n"
        "/deals — Digest completo (God Tier + Gratis + Best Value)\n"
        "/godtier — Giochi &gt;€20 con sconto &gt;60%, per risparmio reale\n"
        "/free — Giochi temporaneamente gratuiti, dal più costoso\n"
        "/gems — Indie poco noti, sconto alto, rating buono\n"
        "/cheap — Giochi ben recensiti sotto €3\n"
        "/savings — Top per risparmio assoluto in €\n"
        "/help — Questa lista\n\n"
        "💡 Il bot ti manda il digest ogni mattina in automatico!"
    )
    send_message(chat_id, msg)


HANDLERS = {
    "/start":   handle_start,
    "/deals":   handle_deals,
    "/godtier": handle_godtier,
    "/free":    handle_free,
    "/gems":    handle_gems,
    "/cheap":   handle_cheap,
    "/savings": handle_savings,
    "/help":    handle_help,
}


# ---------------------------------------------------------------------------
# Gestione pulizia messaggi precedenti
# ---------------------------------------------------------------------------

def load_message_ids():
    if not os.path.exists(MESSAGE_IDS_FILE):
        return []
    try:
        with open(MESSAGE_IDS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_message_ids(ids):
    with open(MESSAGE_IDS_FILE, "w") as f:
        json.dump(ids, f)


def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    r = requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=10)
    return r.status_code == 200


def delete_previous_messages():
    ids = load_message_ids()
    if not ids:
        print("📭 Nessun messaggio precedente da cancellare.")
        return
    print(f"🗑️ Cancello {len(ids)} messaggi precedenti...")
    deleted = sum(1 for mid in ids if delete_message(CHAT_ID, mid))
    print(f"✅ Cancellati {deleted}/{len(ids)} messaggi.")


# ---------------------------------------------------------------------------
# Modalità: daily (GitHub Actions) o polling (manuale)
# ---------------------------------------------------------------------------

def run_daily():
    print("📡 Modalità: invio giornaliero")
    delete_previous_messages()

    god = get_god_tier()
    free = get_free_games()
    best = get_best_value()
    print(f"✅ God Tier: {len(god)}, Gratis: {len(free)}, Best Value: {len(best)}")

    msg = build_daily_message(god, free, best)
    result = send_message(CHAT_ID, msg)

    new_ids = []
    if result and result.get("ok"):
        new_ids.append(result["result"]["message_id"])
    save_message_ids(new_ids)
    print(f"✅ Inviato! ID: {new_ids}")


def run_polling():
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
                text = message.get("text", "").strip().split("@")[0]

                if not chat_id or not text:
                    continue

                print(f"📩 Comando: {text} da {chat_id}")
                handler = HANDLERS.get(text)
                if handler:
                    handler(chat_id)
                else:
                    send_plain(chat_id, "❓ Comando non riconosciuto. Usa /help per vedere i comandi.")

        except KeyboardInterrupt:
            print("\n👋 Bot fermato.")
            break
        except Exception as e:
            print(f"⚠️ Errore polling: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "polling"
    if mode == "daily":
        run_daily()
    else:
        run_polling()