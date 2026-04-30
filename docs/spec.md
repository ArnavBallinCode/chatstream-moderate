# ChatStream Moderate — Full Specification

## Eventyay terminology reference

| Eventyay term | Meaning | Our term |
|---------------|---------|----------|
| **Channel** | A chat stream within a room | maps to our `room` (one channel = one moderated room) |
| **Room** | A session space (type: Stage, Chat, or BBB) that contains a channel | our rooms correspond to Eventyay Chat-type rooms |
| **`channel.message`** | Eventyay event type for a text message | our `message_type: text` |
| **`event.reaction`** | Eventyay event type for an emoji reaction | our `message_type: emoji` |
| **`sender`** | Eventyay field for the user sending a message | maps to our `sender_id`; `centralauth_id` is optional and only present if Eventyay has resolved the Wikimedia identity |
| **`content`** | Eventyay message body object `{ type, body }` | maps to our `message` field |
| **Live** | Eventyay module containing all real-time features (`features/live`) | — |
| **`channel`** | Eventyay field identifying which channel a message belongs to | maps to our `channel` field in the payload |

> **TODO:** Verify what `sender` actually contains in Eventyay's `chat.py` — is it a username string, an internal integer user ID, or something else? Check `features/live/modules/chat.py` and the user model it references before finalising the `sender_id` field definition.

> **Integration note:** Eventyay has no existing webhook or external API for the chat module. No issues or roadmap items exist for this. Our webhook endpoint is the proposed integration point; Eventyay would need to add a signal/HTTP call inside `features/live/modules/chat.py`'s send handler to POST `channel.message` and `event.reaction` events to us. The Q&A module (`features/live/modules/question.py`) is a planned future extension using the same payload format with `message_type: qa`.

---

## Input

Webhook endpoint: `POST /webhook/channel/<channel_id>`

**Authentication:** HMAC-SHA256 signature verification (same pattern as GitHub/Stripe webhooks)
- Eventyay computes `HMAC-SHA256(raw_request_body, shared_secret)` and sends it as `X-Eventyay-Signature: sha256=<hex_digest>`
- We verify using `hmac.compare_digest()` (constant-time, prevents timing attacks)
- Shared secret is per-channel, set by superadmin, stored as a Kubernetes secret

**Replay protection:**
- `timestamp` field in payload is included in the signed body
- Requests where `now - timestamp > 5 minutes` are rejected

**Challenge verification on registration:**
- When an endpoint URL is first registered, Eventyay sends `GET /webhook/channel/<channel_id>?challenge=<token>`
- We respond with `{ "challenge": "<token>" }` to prove we own the endpoint

```json
{
  "message_id":     "uuid",                                    // required
  "channel":        "eventyay-channel-identifier",             // required
  "timestamp":      "ISO8601",                                 // required
  "screen_name":    "string",                                  // required — how the sender wants to appear
  "message":        "string",                                  // required
  "message_type":   "text | emoji | qa",                       // required
  "sender_id":      "eventyay-internal-user-id | null",        // optional — may be withheld for privacy
  "centralauth_id": "wikimedia-centralauth-integer-id | null", // optional — only if Eventyay has resolved Wikimedia identity
  "profile_img":    "url | null",                              // optional
  "user_language":  "BCP 47 code | null",                      // optional
  "meta":           {}                                         // optional, type-specific extras
}
```

**`meta` by message type:**

| `message_type` | Eventyay source | `meta` fields |
|----------------|-----------------|---------------|
| `text` | `channel.message` | `{}` |
| `emoji` | `event.reaction` | `{ "target_message_id": "uuid" }` |
| `qa` *(future)* | `question.py` module | `{ "vote_count": 0, "is_pinned": false, "anonymous": false }` |

Mock generator: `POST /dev/inject/<channel_id>` — debug only, simulates incoming messages.

---

## Role hierarchy

| Role | Scope | Managed by |
|------|-------|------------|
| Superadmin | Global | Hardcoded in config |
| Channel admin | Per channel | Superadmin |
| Channel moderator | Per channel | Channel admin |
| Viewer | Per channel | — (unauthenticated) |

All authenticated users log in via Wikimedia OAuth 2.0 (PKCE). Unique identifier is `centralauth_id` (Wikimedia CentralAuth `gu_id`, integer; returned as `sub` in the OAuth profile and as `centralids.CentralAuth` via the MediaWiki API). `wiki_username` is stored as last-known display label and updated on each login.

---

## Channels (our moderated rooms)

- Created and deleted by superadmin; each corresponds to one Eventyay Chat-type room
- Each channel has: ID (human-readable slug), name, description, active/inactive status
- Channel admin is assigned per channel by superadmin
- Superadmin can add/remove channel admins

---

## Moderation queue

- All incoming messages are held in queue — nothing auto-displays
- Moderator sees oldest-first list
- Per-message actions: **Approve**, **Reject**, **Highlight**
- **Block user**: stores whatever identifiers are available (`centralauth_id`, `sender_id`, `screen_name`) in the blacklist entry; future messages matched with best available: `centralauth_id` → `sender_id` → `screen_name`
- **Block similar**: stores message text as a pattern; auto-rejects any currently queued or future message within Levenshtein distance ≤ 2 (normalized: lowercase, stripped whitespace)
- **Emoji auto-approve**: if an identical emoji (`message_type: emoji`, same `message` content) was approved within the last 10 seconds in the same channel, the incoming duplicate is auto-approved without entering the queue; configurable per channel (default: on)
- Moderators can filter queue view by detected language (checkboxes per language; hides messages from view but does not reject them; state is per-session, not persisted)
- Language detection only runs on `message_type: text`; `emoji` and `qa` skip detection

---

## Output formats

### RSS feed *(priority — implement first)*

| URL | Content |
|-----|---------|
| `/rss/<channel_id>` | All approved + highlighted messages |
| `/rss/<channel_id>/highlights` | Highlighted messages only |

- Standard RSS 2.0 feed (`Content-Type: application/rss+xml`)
- Each approved/highlighted message is one `<item>`
- `<title>` — screen_name
- `<description>` — message text
- `<pubDate>` — processed_at timestamp (RFC 2822)
- `<guid>` — message ID (permanent, `isPermaLink="false"`)
- `<channel>` metadata: channel name, description, last build date
- **Public channel**: open URL, no auth required
- **Private channel**: URL requires `?token=<secret>`
- Items ordered newest-first (standard RSS convention)
- Cap at last 50 approved messages to keep feed size bounded

### Display screen *(deferred)*

Browser overlay for OBS/vMix/Wirecast — lower-third, transparent background, CSS-customisable. Details in spec but not in current build scope.

### SSE stream *(deferred)*

Programmatic JSON stream at `/stream/<channel_id>` for tool consumers. Details in spec but not in current build scope.

---

## Blacklists

- **Channel blacklist**: stores all available identifiers (`centralauth_id`, `sender_id`, `screen_name`); all three are nullable except `screen_name` which is always present; match logic: `centralauth_id` → `sender_id` → `screen_name`; managed by channel admin and moderators
- **Global blacklist**: same structure; blocked across all channels; channel admins can export entries to it; superadmin manages it
- Moderators can remove entries from the channel blacklist

**Incoming message processing order:**
1. Verify `X-Eventyay-Signature` HMAC → reject with 403 if invalid
2. Reject if `now - timestamp > 5 minutes` → reject with 400
3. Check global blacklist → silently drop if match
4. Check channel blacklist → silently drop if match
5. Check blocked patterns (Levenshtein ≤ 2) → silently drop if match
6. Run language detection (if enabled, `message_type: text` only) → assign language
7. Add to moderation queue

---

## Language detection

- Configured per channel by channel admin
- Library: `lingua-language-detector` (local, no external API, ~2–5ms/message)
- Only runs on `message_type: text`

**Channel config fields:**
- `language_detection_enabled`: boolean
- `default_language`: BCP 47 fallback code (e.g. `en`)
- `likely_languages`: ordered list of expected BCP 47 codes (e.g. `["en", "fr", "nl"]`)

**Detection logic:**
1. Run lingua-py against `likely_languages`
2. If confidence ≥ 0.75 → use detected language
3. If confidence < 0.75 and `user_language` present → use `user_language`
4. Otherwise → use channel `default_language`

**`user_language` field** (from Eventyay input):
- Treated as user's declared language
- Used as fallback when lingua-py confidence is below threshold
- Overrides channel default when lingua-py is uncertain

---

## Tech stack

- **Language**: Python 3.11
- **Framework**: Flask 3.1, SQLAlchemy 2.0, Flask-Migrate (Alembic)
- **Database**: MariaDB via PyMySQL (Toolforge); SQLite fallback for local dev
- **Sessions**: Flask-Session with MariaDB backend
- **Auth**: Wikimedia OAuth 2.0 PKCE (same pattern as wall-of-faces repo)
- **Server**: uWSGI, 1 process, 16 threads
- **Real-time**: 2s polling for moderator queue and browser display; SSE (`/stream/`) for programmatic consumers
- **Queue UI**: HTMX (polling + actions without custom JS)
- **Display UI**: Custom JS (animation queue logic)
- **Language detection**: `lingua-language-detector`
- **Secrets**: Kubernetes secret files at `/etc/passwords/<name>`
- **Deployment**: Toolforge Kubernetes webservice

---

## URL structure

```
# Auth
GET  /login
GET  /oauth-callback
POST /logout
GET  /dev-login                                  # debug only

# Home
GET  /                                           # channel list for logged-in users

# Webhook
GET  /webhook/channel/<channel_id>              # challenge verification on registration
POST /webhook/channel/<channel_id>              # Eventyay input (channel.message, event.reaction)
POST /dev/inject/<channel_id>                   # mock message injection (debug only)

# RSS feed (priority output)
GET  /rss/<channel_id>                          # all approved + highlighted
GET  /rss/<channel_id>/highlights               # highlighted only

# Display screen (deferred)
# GET  /display/<channel_id>
# GET  /display/<channel_id>/highlights

# SSE stream (deferred)
# GET  /stream/<channel_id>
# GET  /stream/<channel_id>/highlights
# GET  /api/channel/<channel_id>/feed

# Moderation queue
GET  /channel/<channel_id>/queue
GET  /channel/<channel_id>/queue/messages       # HTMX fragment, polled every 2s
POST /api/channel/<channel_id>/message/<id>/approve
POST /api/channel/<channel_id>/message/<id>/reject
POST /api/channel/<channel_id>/message/<id>/highlight
POST /api/channel/<channel_id>/block-user
POST /api/channel/<channel_id>/block-similar

# Channel admin
GET  /channel/<channel_id>/settings
POST /channel/<channel_id>/settings
POST /channel/<channel_id>/moderators/add
POST /channel/<channel_id>/moderators/remove
GET  /channel/<channel_id>/blacklist
POST /channel/<channel_id>/blacklist/remove
POST /channel/<channel_id>/blacklist/export     # export entry to global blacklist
POST /channel/<channel_id>/token/regenerate

# Superadmin
GET  /admin/
GET  /admin/channels
POST /admin/channels/create
GET  /admin/channels/<channel_id>/edit
POST /admin/channels/<channel_id>/edit
POST /admin/channels/<channel_id>/delete
POST /admin/channels/<channel_id>/admins/add
POST /admin/channels/<channel_id>/admins/remove
GET  /admin/global-blacklist
POST /admin/global-blacklist/remove
```

---

## Data model (summary)

- **Channel**: id (slug), name, description, is_active, is_public, display_token, webhook_hmac_secret, custom_css, language_detection_enabled, default_language, likely_languages, emoji_auto_approve (bool, default true), created_at
- **ChannelMember**: channel_id, centralauth_id, wiki_username (last-known), role (admin|moderator), added_at
- **Message**: id, eventyay_message_id, channel_id, screen_name, sender_id (nullable), centralauth_id (nullable), message, message_type (text|emoji|qa), meta (JSON), profile_img, user_language, detected_language, status (queued|approved|highlighted|rejected), arrived_at, processed_at, processed_by_centralauth_id
- **Blacklist**: id, channel_id, screen_name, sender_id (nullable), centralauth_id (nullable), added_by_centralauth_id, added_by_wiki_username, added_at
- **GlobalBlacklist**: id, screen_name, sender_id (nullable), centralauth_id (nullable), added_by_centralauth_id, added_by_wiki_username, added_at
- **BlockedPattern**: id, channel_id, pattern_text, original_message_id, added_by_wiki_id, added_at
