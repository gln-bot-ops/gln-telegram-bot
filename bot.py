"""GLN mining-simulation bot entry point. Run: python bot.py"""
import asyncio
import hmac
import json
import logging
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ChatMemberUpdated

from app.admin import router as admin_router
from app.config import BOT_TOKEN
from app.db import init_db
from app.handlers import router as user_router


def _start_health_server():
    """Tiny HTTP responder so a Render free Web Service has a port to bind.
    Does nothing when PORT is unset (local runs, background workers)."""
    port = os.getenv("PORT")
    if not port:
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"gln-bot ok")

        def do_POST(self):
            """Authenticated relay: POST /post {"text": ...} sends a Telegram
            message to GLN_DEALS_CHAT_ID via the Bot API. Used by the deals
            watcher; does not touch the mining game state."""
            log = logging.getLogger(__name__)

            def reply(status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            if self.path != "/post":
                reply(404, {"ok": False, "error": "unknown path"})
                return
            secret = os.getenv("GLN_POST_SECRET", "")
            key = self.headers.get("X-GLN-Key", "")
            if not secret or not hmac.compare_digest(key, secret):
                reply(401, {"ok": False, "error": "unauthorized"})
                return
            chat_id = os.getenv("GLN_DEALS_CHAT_ID", "")
            if not chat_id:
                reply(503, {"ok": False, "error": "GLN_DEALS_CHAT_ID not configured"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                text = str(payload.get("text", "")).strip()
            except Exception:
                text = ""
            if not text:
                reply(400, {"ok": False, "error": "missing text"})
                return
            # Telegram caps messages at 4096 chars; send long texts in chunks.
            ok, err = True, ""
            for i in range(0, len(text), 4000):
                chunk = text[i:i + 4000]
                body = json.dumps({"chat_id": chat_id, "text": chunk}).encode()
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data=body, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        result = json.loads(resp.read())
                    ok = ok and bool(result.get("ok"))
                except Exception as exc:
                    ok, err = False, str(exc)
                    log.warning("deals post failed: %s", exc)
                    break
            reply(200 if ok else 502, {"ok": ok, "error": err})

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", int(port)), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.getLogger(__name__).info("Health server listening on port %s", port)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger(__name__)
    # Bind Render's port FIRST so the port scanner sees us even if later steps fail.
    _start_health_server()
    if not BOT_TOKEN:
        raise SystemExit("GLN_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    # Neon free tier scales to zero; the first connect can take many seconds while
    # the database wakes. Retry instead of crash-looping (which also keeps the
    # health server alive so Render does not kill the deploy as port-less).
    for attempt in range(1, 7):
        try:
            init_db()
            break
        except Exception as exc:
            log.warning("init_db attempt %s/6 failed: %s", attempt, exc)
            if attempt == 6:
                raise
            await asyncio.sleep(5)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(user_router)

    @dp.my_chat_member()
    async def _log_chat_membership(event: ChatMemberUpdated):
        # Lets us discover the deals group chat_id from the Render logs once
        # the bot is added to a group. No user-facing behavior.
        logging.getLogger(__name__).info(
            "CHAT_MEMBER_UPDATE chat_id=%s title=%r status=%s",
            event.chat.id, event.chat.title, event.new_chat_member.status)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
