# chatstream-moderate

Real-time chat moderation for [Eventyay](https://eventyay.com) conference streams, hosted on [Toolforge](https://wikitech.wikimedia.org/wiki/Portal:Toolforge).

Incoming chat messages are held in a moderation queue. Moderators approve, reject, or highlight messages before they appear in the output feeds. Multiple moderators can work the same queue simultaneously — competing decisions are resolved by most-restrictive-wins.

---

## How it works

1. Eventyay posts `channel.message` and `event.reaction` events to `/webhook/channel/<id>` via HMAC-signed HTTP
2. Messages enter the moderation queue (unless the sender is blacklisted, matches a blocked pattern, or is whitelisted)
3. Moderators log in with their Wikimedia account and work the queue: approve / reject / highlight / ban / allow
4. Approved and highlighted messages are published via an RSS feed consumed by display tools

---

## Local development

### Prerequisites

- [UV](https://docs.astral.sh/uv/) for Python dependency management
- Python 3.11

### Setup

```bash
git clone https://github.com/lgelauff/chatstream-moderate
cd chatstream-moderate
uv sync
```

Create a `.env` file (never commit this):

```
OAUTH_CLIENT_ID=your_client_id
OAUTH_CLIENT_SECRET=your_client_secret
OAUTH_REDIRECT_URI=http://127.0.0.1:5000/oauth-callback
SECRET_KEY=any-random-string-for-local-dev
```

### Running

```bash
FLASK_DEBUG=1 uv run python app.py
```

Visit `http://127.0.0.1:5000` (not `localhost` — AirPlay Receiver can intercept port 5000 on macOS).

### Dev login (bypass OAuth)

With `FLASK_DEBUG=1`, skip OAuth entirely:

```
http://127.0.0.1:5000/dev-login?username=YourWikimediaName
```

### Superadmin access

Edit the `SUPERADMIN_USERS` list in `app.py`:

```python
SUPERADMIN_USERS: list[str] = ["YourWikimediaName"]
```

### Simulating a message stream

1. Log in as superadmin
2. Visit `/admin/` → activate the simulation channel
3. Open the simulation channel's queue — a floating panel lets you start/stop a message stream at up to 240 msg/min

### Database

SQLite is used automatically for local dev (`instance/dev.db`). No setup needed.

---

## Configuration

All secrets are read from `/etc/passwords/<name>` (Toolforge Kubernetes secrets) with environment variable fallback. For local dev, set them via `.env`.

| Secret name | Env var | Description |
|-------------|---------|-------------|
| `oauth-client-id` | `OAUTH_CLIENT_ID` | Wikimedia OAuth consumer key |
| `oauth-client-secret` | `OAUTH_CLIENT_SECRET` | Wikimedia OAuth consumer secret |
| `oauth-redirect-uri` | `OAUTH_REDIRECT_URI` | OAuth callback URL |
| `secret-key` | `SECRET_KEY` | Flask session secret |
| `db-host` | `DB_HOST` | MariaDB host (default: `tools.db.svc.wikimedia.cloud`) |
| `db-user` | `DB_USER` | MariaDB user |
| `db-password` | `DB_PASSWORD` | MariaDB password |
| `db-name` | `DB_NAME` | MariaDB database name |

---

## Deployment (Toolforge)

This is a one-time setup. For routine updates see [Updating](#updating).

### 1. Register the tool

Register at https://toolsadmin.wikimedia.org with tool name `chatstream-moderate`.

### 2. Register OAuth consumer

Register at https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration with:
- Callback URL: `https://chatstream-moderate.toolforge.org/oauth-callback`
- Grant: **User identity verification only** (confidential client, authorization code only)

Public consumers require admin approval — plan for several days wait. Owner-only consumers are active immediately.

### 3. SSH into Toolforge

```bash
ssh USERID@login.toolforge.org
become chatstream-moderate
```

> **Reference**: `../wikimedia-coding-agent-lessons/toolforge/lessons.md` has ground-truth Toolforge deployment notes.

### 4. Clone the repository

```bash
git clone https://github.com/lgelauff/chatstream-moderate ~/chatstream-moderate
```

### 5. Create the database

Read your credentials:

```bash
cat ~/replica.my.cnf
```

Connect and create the database — the name **must** start with your tools prefix:

```bash
mariadb --defaults-file=$HOME/replica.my.cnf -h tools.db.svc.wikimedia.cloud
```

```sql
CREATE DATABASE `s12345__chatstream`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
EXIT;
```

### 6. Set secrets

Use **single quotes** to avoid shell interpretation:

```bash
toolforge envvars create OAUTH_CLIENT_ID     'YOUR_CLIENT_ID'
toolforge envvars create OAUTH_CLIENT_SECRET 'YOUR_CLIENT_SECRET'
toolforge envvars create OAUTH_REDIRECT_URI  'https://chatstream-moderate.toolforge.org/oauth-callback'
toolforge envvars create SECRET_KEY          "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
toolforge envvars create DB_USER             's12345'
toolforge envvars create DB_PASSWORD         'YOUR_DB_PASSWORD'
toolforge envvars create DB_NAME             's12345__chatstream'
```

`toolforge envvars list` masks values after creation — keep a local record.

### 7. Set up the web service directory

`~/www/python` must be a **real directory**, not a symlink:

```bash
mkdir -p ~/www/python
ln -s ~/chatstream-moderate ~/www/python/src
```

Open a webservice shell to create the venv — **must be done inside the container**, not on the bastion. The bastion runs Python 3.13; the webservice runs 3.11. Running pip from the bastion corrupts the venv.

```bash
toolforge webservice --backend=kubernetes python3.11 shell
```

Inside the shell, create the venv and install packages. Use `get-pip.py` piped directly — `ensurepip` and `python3 -m venv` (without `--without-pip`) hang due to subprocess restrictions in the shell pod:

```bash
python3 -m venv ~/www/python/venv --without-pip
curl -sS https://bootstrap.pypa.io/get-pip.py | ~/www/python/venv/bin/python3
~/www/python/venv/bin/python3 -m pip install -e ~/chatstream-moderate
exit
```

### 8. Start the web service

Run from your **home directory**:

```bash
cd ~
toolforge webservice --backend=kubernetes python3.11 start
```

Check logs:

```bash
toolforge webservice logs
```

`lseek: Illegal seek` lines in the logs are harmless uWSGI noise — filter with `grep -v lseek`.

The database schema is created automatically on first startup.

### Updating

For code changes (no new dependencies):

```bash
bash ~/chatstream-moderate/deploy.sh
```

For dependency changes (new packages added to `pyproject.toml`), you must reinstall inside the webservice shell:

```bash
toolforge webservice --backend=kubernetes python3.11 shell
~/www/python/venv/bin/python3 -m pip install -e ~/chatstream-moderate
exit
cd ~
toolforge webservice --backend=kubernetes python3.11 restart
```

### Troubleshooting

**`WARNING: Ignoring invalid distribution ~ip`** — corrupted pip leftover from a failed install. Fix from the bastion:
```bash
rm -rf ~/www/python/venv/lib/python3.11/site-packages/~ip*
```

**OAuth `invalid_scope` error** — the Wikimedia OAuth 2.0 scope must be `basic`, not `openid`. Check `app.py`.

---

## Project structure

```
chatstream-moderate/
  app.py              — Flask app factory, OAuth flow, SUPERADMIN_USERS config
  wsgi.py             — WSGI entry point
  uwsgi.ini           — uWSGI config (buffer-size for long OAuth codes)
  deploy.sh           — Toolforge deploy script
  pyproject.toml      — Dependencies (managed with UV)
  src/
    models.py         — SQLAlchemy models
    webhook.py        — Webhook receiver, message intake, blacklist/whitelist checks
    queue_bp.py       — Moderation queue UI and API actions
    admin_bp.py       — Channel admin and superadmin management
    display_bp.py     — RSS feed output
    auth.py           — Auth helpers, role checks
    utils.py          — Levenshtein, token generation
  templates/
    base.html         — Header, flash messages
    queue.html        — Moderation queue (JSON polling, keyboard shortcuts)
    queue/log.html    — Moderation decision log
    admin/            — Channel settings, blacklist, whitelist, simulation
  static/css/
    app.css           — Light wiki-polis theme
```

---

## Webhook payload format

```json
{
  "message_id":     "uuid",
  "channel":        "eventyay-channel-id",
  "timestamp":      "ISO8601",
  "screen_name":    "display name",
  "message":        "text content",
  "message_type":   "text | emoji | qa",
  "sender_id":      "eventyay-user-id | null",
  "centralauth_id": "wikimedia-centralauth-id | null",
  "profile_img":    "url | null",
  "user_language":  "BCP47 | null",
  "meta":           {}
}
```

Authentication: `X-Eventyay-Signature: sha256=<hmac-hex>` over the raw request body. Shared secret is per-channel.
