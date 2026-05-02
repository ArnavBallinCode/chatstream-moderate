# Tests

Integration tests using Flask's test client and an in-memory SQLite database.
No running server or external services required.

```
.venv/bin/python tests/test_webhook.py
.venv/bin/python tests/test_multiuser.py
```

## test_webhook.py (20 tests)

Covers the webhook intake pipeline end-to-end:

- **HMAC auth** — wrong/missing/bad-secret signatures → 403
- **Timestamp replay** — messages older or newer than 5 minutes → 400
- **Malformed timestamp** — non-ISO strings now → 400 (was silently ignored)
- **Dedup** — duplicate `message_id` is dropped
- **Emoji remove** — `action: remove` reactions are not stored
- **Normal flow** — message arrives with `status=queued`
- **Blacklist** — message from blocked sender is not stored
- **Whitelist** — message from trusted sender arrives as `approved`
- **Inactive channel** — webhook returns 404

## test_multiuser.py (16 tests)

Simulates two moderators acting on the same queued message, verifying the
`DECISION_RANK` "most restrictive wins" rule:

| Mod1 → Mod2    | Expected outcome |
|----------------|-----------------|
| approve → approve | superseded, 1 log entry |
| approve → reject  | reject wins |
| reject → approve  | approve blocked |
| highlight → approve | approve wins |
| highlight → reject  | reject wins |
| approve → highlight | highlight blocked |
