# File: Extractor/modules/madeeasy_handler.py
from pyrogram import filters
from Extractor import app
from Extractor.core.utils import forward_to_log
import requests
from .madeeasy import run_madeeasy_sync, clean_text, BASE_URL

@app.on_message(filters.command(["madeeasy"]))
async def madeeasy_cmd(app, message):
    try:
        q = await app.ask(message.chat.id, text="🔐 Paste your MadeEasy **Bearer token** (do NOT share password/OTP):")
        await forward_to_log(q, "MadeEasy Extractor")
        token = q.text.strip()
        if not token:
            return await message.reply_text("❌ No token provided.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0"
        }

        # fetch batches - endpoint may differ; update after sniffing
        r = requests.get(f"{BASE_URL}/batches/my-batches?page=1", headers=headers)
        if r.status_code != 200:
            return await message.reply_text("❌ Failed to fetch batches. Check token or endpoint.")
        batches = r.json().get("data", [])
        if not batches:
            return await message.reply_text("❌ No batches found on this account.")

        text = "📚 Your Batches:\n\n"
        mapping = {}
        for b in batches:
            bi = b.get("_id") or b.get("id")
            bn = b.get("name") or b.get("title") or "Unnamed"
            text += f"📖 `{bi}` → **{bn}**\n"
            mapping[str(bi)] = bn

        await app.send_message(message.chat.id, text + "\n\nEnter the Batch ID to extract:")
        chosen = await app.ask(message.chat.id, text="Batch ID:")
        batch_id = chosen.text.strip()
        if batch_id not in mapping:
            return await message.reply_text("❌ Invalid batch id.")

        await app.send_message(message.chat.id, f"🔄 Starting extraction for **{mapping[batch_id]}** — please wait.")
        out_file = run_madeeasy_sync(token, batch_id, output_file=f"{clean_text(mapping[batch_id])}.txt")
        await app.send_document(chat_id=message.chat.id, document=out_file, caption=f"Extraction complete for {mapping[batch_id]}")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)[:200]}")
