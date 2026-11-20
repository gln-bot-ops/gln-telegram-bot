# GLN Mining Bot

Telegram mining-simulation bot for the GLN coin community. Users mine points on a
timer, invite friends for bonuses, and spend points on upgrades. Points convert to
GLN tokens at TGE - there is no on-chain integration in this phase.

Built with Python + aiogram 3 + SQLite. Long-polling, no webhook or public URL needed.

## Features

- `/start` registers the user, hands out a welcome bonus and a personal referral code
- Mining: start a session, it matures after a cooldown (default 4h), claim within an
  8-hour grace window or it expires
- Referrals: inviter earns 250 points when a friend joins via their `t.me` link and
  500 more on the friend's first claim
- Upgrades: spend points to raise the mining rate (+25%/level) or shorten the
  cooldown (-15 min/level, floor 1 hour)
- Leaderboard: top 10 by lifetime earned points
- Anti-abuse: one account per Telegram user id, one active session per user,
  1-action/second throttle, claimable only inside the readiness window
- Admin: `/stats` (users, sessions, claims, points issued) and `/broadcast <text>`

All game-balance numbers live in `app/game.py`. Bot copy (Arabic) lives in `app/texts.py`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: GLN_BOT_TOKEN (from @BotFather) and ADMIN_IDS (your Telegram user id,
# find it via @userinfobot)
python bot.py
```

Run the tests (no Telegram needed):

```bash
python tests/test_logic.py
```

## Deploy: Render free Web Service + Neon free Postgres (all free, no card)

Production shape: Render **free Web Service** runs the bot (background workers have
no free tier, and free Render Postgres expires after 30 days, so we use Neon). The bot
binds `$PORT` with a tiny health endpoint. Data lives in **Neon** free Postgres
(permanent, no card, 1 GB, scales to zero between messages) via `DATABASE_URL`.

1. Create a free Neon project (or claim the existing one via its claim link) and copy
   the pooled connection string.
2. Push this repo to any public Git host and create a Render Web Service from it
   ("Public Git repository" works without connecting a Git provider), or use the
   included `render.yaml` blueprint. Build: `pip install -r requirements.txt`,
   start: `python bot.py`, plan: Free.
3. Environment variables: `GLN_BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`.
4. Free Web Services spin down after 15 idle minutes. Add a free external pinger
   (e.g. cron-job.org every 10 minutes) hitting `https://<service>.onrender.com/`
   so it stays awake; 750 free instance-hours/month cover 24/7. Telegram queues
   messages for ~24h, so even a sleeping bot answers late, never loses data (Neon).

## Notes for TGE phase

- `users.total_earned` is the lifetime points each user mined - the natural input
  for a future airdrop allocation.
- Export it any time with: `sqlite3 gln_bot.db "SELECT id, total_earned FROM users"`
- Keep the token secret. Rotate it in @BotFather if it ever leaks.
