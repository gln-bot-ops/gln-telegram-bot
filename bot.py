"""GLN mining-simulation bot entry point. Run: python bot.py"""
import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
