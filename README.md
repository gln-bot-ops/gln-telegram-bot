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

## Deploy: always-on options

### Railway (easiest, ~$5/mo hobby after trial)
1. Push this folder to a private GitHub repo.
2. Railway -> New Project -> Deploy from GitHub repo.
3. Add variables `GLN_BOT_TOKEN` and `ADMIN_IDS` under Variables.
4. Add a Railway Volume mounted at `/data` and set `GLN_DB_PATH=/data/gln_bot.db`
   so the database survives redeploys.
5. Set the start command to `python bot.py` (Railway detects Python automatically).

### Render (free tier)
1. Same GitHub repo. Render -> New -> Background Worker.
2. Build command: `pip install -r requirements.txt`; Start command: `python bot.py`.
3. Add the same environment variables. Attach a persistent disk and point
   `GLN_DB_PATH` at it (free-tier disks are paid; without one the DB resets on redeploy).

### Small VPS (Hetzner/Contabo ~$4/mo)
```bash
git clone <repo> && cd gln-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # fill in values
```
Then a systemd unit `/etc/systemd/system/gln-bot.service`:

```
[Unit]
Description=GLN Mining Bot
After=network.target

[Service]
WorkingDirectory=/opt/gln-bot
ExecStart=/opt/gln-bot/.venv/bin/python bot.py
Restart=always
EnvironmentFile=/opt/gln-bot/.env

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now gln-bot`

## Notes for TGE phase

- `users.total_earned` is the lifetime points each user mined - the natural input
  for a future airdrop allocation.
- Export it any time with: `sqlite3 gln_bot.db "SELECT id, total_earned FROM users"`
- Keep the token secret. Rotate it in @BotFather if it ever leaks.
