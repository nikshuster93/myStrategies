#!/usr/bin/env python3
"""
Telegram userbot relay — monitors group for bot messages that tag @Stepashka_clawbot
and forwards them to Stepashka via the bot API.
"""
import asyncio
import aiohttp
from telethon import TelegramClient, events

API_ID = 31720807
API_HASH = "e0e196f35835f7c16266607b71f51780"
SESSION_FILE = "/root/.openclaw/scripts/tg-relay-session"

# Group to monitor
GROUP_ID = -5204693916

# Stepashka bot token + chat to deliver relayed messages to
def _load_token():
    import os
    t = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not t:
        try:
            for line in open("/root/.openclaw/telegram.env"):
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    t = line.split("=", 1)[1].strip().strip('"\'')
        except OSError:
            pass
    if not t:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set (env or /root/.openclaw/telegram.env)")
    return t

BOT_TOKEN = _load_token()
DELIVER_CHAT = 437052622  # Nikita's private chat with Stepashka

# Bot username to watch for mentions
WATCH_USERNAME = "Stepashka_clawbot"

async def send_to_stepashka(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, data={"chat_id": DELIVER_CHAT, "text": text})

async def main():
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()
    print("Userbot relay started.")

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        msg = event.message
        # Skip messages from real users (only relay bot messages)
        sender = await event.get_sender()
        if not getattr(sender, 'bot', False):
            return

        text = msg.text or ""
        # Check if Stepashka is mentioned
        if WATCH_USERNAME.lower() in text.lower() or "stepashka" in text.lower():
            sender_name = getattr(sender, 'username', None) or getattr(sender, 'first_name', 'unknown bot')
            relay_text = f"📨 Relay from @{sender_name} in Humans & Bots:\n\n{text}"
            await send_to_stepashka(relay_text)
            print(f"Relayed message from @{sender_name}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
