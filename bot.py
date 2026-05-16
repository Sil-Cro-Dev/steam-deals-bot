"""
Steam Deals Telegram Bot
- Invio automatico ogni mattina (via GitHub Actions)
- Comandi interattivi (via polling, quando avviato manualmente)
"""

import os
import sys
import json
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

def get_top_deals(min_savings=50, page_size=30):
    params = {
        "storeID": "1",
        "pageSize": page_size,
        "sortBy": "Savings",
        "desc": "1",
        "lowerPrice": "0.01",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    print(f"   CheapShark status: {r.status_code}, bytes: {len(r.content)}")
    if r.status_code != 200:
        print(f"   Risposta: {r.text[:200]}")
        return []
    deals = r.json()
    print(f"   API ha ritornato {len(deals)} deals totali")
    if deals:
        savings_vals = [float(d.get("savings", 0)) for d in deals]
        print(f"   Saving range: {min(savings_vals):.0f}% - {max(savings_vals):.0f}%")
    filtered = [d for d in deals if float(d.get("savings", 0)) >= min_savings]
    return filtered


def get_free_games():
    params = {
        "storeID": "1",
        "upperPrice": "0",
        "pageSize": "10",
        "sortBy": "Savings",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_extreme_deals():
    """Giochi scontati 90%+."""
    return get_top_deals(min_savings=90, page_size=15)


def get_under_5_euro():
    """Offerte Steam con prezzo finale < 5€."""
    params = {
        "storeID": "1",
        "pageSize": "20",
        "sortBy": "Price",
        "upperPrice": "5",
        "lowerPrice": "0.01",
    }
    r = requests.get(CHEAPSHARK_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()[:8]


# ---------------------------------------------------------------------------
# Formattatori messaggi (HTML — molto più robusto di MarkdownV2)
# ---------------------------------------------------------------------------

def h(text):
    """Escape caratteri speciali HTML."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def steam_url(d):
    steam_id = d.get("steamAppID", "")
    return f"https://store.steampowered.com/app/{steam_id}" if steam_id else "https://store.steampowered.com"


def deal_line(d):
    title = h(d["title"])
    normal = float(d["normalPrice"])
    sale = float(d["salePrice"])
    savings = int(float(d["savings"]))
    url = steam_url(d)

    if savings >= 90:
        badge = "🔴"
    elif savings >= 75:
        badge = "🟠"
    elif savings >= 50:
        badge = "🟡"
    else:
        badge = "🟢"

    return (
        f'{badge} <a href="{url}">{title}</a>\n'
        f'   <s>€{normal:.2f}</s> → <b>€{sale:.2f}</b> (-{savings}%)\n'
    )


def build_daily_message(deals, free_games):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"🎮 <b>Steam Deals — {today}</b>\n"]

    if free_games:
        lines.append("🎁 <b>GRATIS OGGI</b>")
        for g in free_games[:3]:
            title = h(g["title"])
            normal = float(g["normalPrice"])
            url = steam_url(g)
            lines.append(f'• <a href="{url}">{title}</a> <s>€{normal:.2f}</s> → <b>GRATIS</b>')
        lines.append("")

    top = [d for d in deals if float(d.get("savings", 0)) >= 70]
    mid = [d for d in deals if 50 <= float(d.get("savings", 0)) < 70]

    if top:
        lines.append("🔥 <b>SCONTI 70%+</b>")
        for d in top[:8]:
            lines.append(deal_line(d))
        lines.append("")

    if mid:
        lines.append("⚡ <b>SCONTI 50–69%</b>")
        for d in mid[:6]:
            lines.append(deal_line(d))

    lines.append(f"<i>Aggiornato alle {datetime.now().strftime('%H:%M')}</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def send_message(chat_id, text, parse_mode="HTML"):
    # Telegram max 4096 caratteri — tronca se necessario
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
    # Rimuovi parse_mode se None
    if parse_mode is None:
        del payload["parse_mode"]

    r = requests.post(url, json=payload, timeout=10)

    # Se fallisce con HTML, riprova senza formattazione
    if r.status_code == 400 and parse_mode == "HTML":
        print(f"⚠️ Errore HTML parsing, riprovo in plain text...")
        print(f"   Risposta Telegram: {r.text}")
        plain = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        plain = plain.replace("<s>", "").replace("</s>", "").replace("<u>", "").replace("</u>", "")
        # Rimuovi tag <a href="...">...</a> mantenendo il testo
        import re
        plain = re.sub(r'<a href="[^"]*">([^<]*)</a>', r'\1', plain)
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
        "👋 <b>Ciao! Sono il tuo Steam Deals Bot</b> 🎮\n\n"
        "Ogni mattina ti mando le migliori offerte Steam.\n"
        "Puoi anche chiederle tu quando vuoi!\n\n"
        "📋 <b>Comandi disponibili:</b>\n"
        "/deals — Top offerte del giorno\n"
        "/free — Giochi gratuiti\n"
        "/extreme — Sconti 90%+\n"
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
        lines = ["🎁 <b>GIOCHI GRATIS SU STEAM</b>\n"]
        for g in games:
            title = h(g["title"])
            normal = float(g["normalPrice"])
            url = steam_url(g)
            lines.append(f'• <a href="{url}">{title}</a> <s>€{normal:.2f}</s> → <b>GRATIS</b>')
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
        lines = ["🔴 <b>SCONTI 90%+</b>\n"]
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
        lines = ["💸 <b>OFFERTE SOTTO 5€</b>\n"]
        for d in deals:
            lines.append(deal_line(d))
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_plain(chat_id, f"❌ Errore: {e}")


def handle_help(chat_id):
    msg = (
        "📋 <b>Comandi disponibili</b>\n\n"
        "/deals — Top offerte del giorno (scontate 70%+)\n"
        "/free — Giochi temporaneamente gratuiti\n"
        "/extreme — Solo sconti oltre il 90%\n"
        "/under5 — Tutto ciò che costa meno di 5€\n"
        "/help — Mostra questa lista\n\n"
        "💡 Il bot ti manda le offerte ogni mattina in automatico!"
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
# Gestione pulizia messaggi precedenti
# ---------------------------------------------------------------------------

def load_message_ids():
    """Carica gli ID dei messaggi salvati dal giorno prima."""
    if not os.path.exists(MESSAGE_IDS_FILE):
        return []
    try:
        with open(MESSAGE_IDS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_message_ids(ids):
    """Salva gli ID dei messaggi appena inviati."""
    with open(MESSAGE_IDS_FILE, "w") as f:
        json.dump(ids, f)


def delete_message(chat_id, message_id):
    """Cancella un singolo messaggio dal bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    r = requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=10)
    return r.status_code == 200


def delete_previous_messages():
    """Cancella tutti i messaggi inviati dal bot il giorno prima."""
    ids = load_message_ids()
    if not ids:
        print("📭 Nessun messaggio precedente da cancellare.")
        return
    print(f"🗑️ Cancello {len(ids)} messaggi precedenti...")
    deleted = 0
    for msg_id in ids:
        if delete_message(CHAT_ID, msg_id):
            deleted += 1
    print(f"✅ Cancellati {deleted}/{len(ids)} messaggi.")


# ---------------------------------------------------------------------------
# Modalità: daily (GitHub Actions) o polling (manuale)
# ---------------------------------------------------------------------------

def run_daily():
    """Invia il messaggio giornaliero. Usato da GitHub Actions."""
    print("📡 Modalità: invio giornaliero")

    # Cancella i messaggi del giorno prima
    delete_previous_messages()

    # Fetch e debug deals
    print("🔍 Chiamo get_top_deals()...")
    deals = get_top_deals()
    print(f"   → {len(deals)} deals trovati con saving>=50%")
    for d in deals[:3]:
        print(f"      {d['title']} | saving={float(d.get('savings',0)):.0f}%")

    print("🔍 Chiamo get_free_games()...")
    free = get_free_games()
    print(f"   → {len(free)} giochi gratuiti trovati")

    msg = build_daily_message(deals, free)
    print(f"📝 Messaggio generato ({len(msg)} caratteri):")
    print(msg[:300])
    print("...")

    result = send_message(CHAT_ID, msg)

    # Salva l'ID del messaggio appena inviato
    new_ids = []
    if result and result.get("ok"):
        new_ids.append(result["result"]["message_id"])
    save_message_ids(new_ids)
    print(f"✅ Messaggio inviato! ID salvato: {new_ids}")


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