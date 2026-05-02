#!/usr/bin/env python3
"""
Sequential multi-moderator integration tests.

Tests that _set_status() correctly handles two moderators acting on the same
message: the DECISION_RANK "most restrictive wins" rule and log integrity.

Usage:  python test_multiuser.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hashlib
import hmac
import json
import uuid

from app import create_app
from src.models import db as _db, Channel, ChannelMember, Message, ModerationLog

CHANNEL_ID  = 'test-multi'
HMAC_SECRET = 'multi-test-secret'  # pragma: allowlist secret
CSRF        = 'fixed-csrf-for-tests'

# ── App + fixtures ─────────────────────────────────────────────────────────────

def _make_app():
    return create_app({
        'TESTING':                    True,
        'SQLALCHEMY_DATABASE_URI':    'sqlite:///:memory:',
        'SECRET_KEY':                 'test-only',  # pragma: allowlist secret
        'SUPERADMIN_USERS':           [],
        'OAUTH_CLIENT_ID':            None,
        # Keep server-side SQLAlchemy sessions — same as production
        'SESSION_TYPE':               'sqlalchemy',
    })


def _setup(app):
    with app.app_context():
        _db.session.add(Channel(
            id=CHANNEL_ID, name='Multi Test', is_active=True,
            display_token='tok', webhook_hmac_secret=HMAC_SECRET,
        ))
        for i, name in enumerate(['Mod1', 'Mod2'], start=1):
            _db.session.add(ChannelMember(
                channel_id=CHANNEL_ID, centralauth_id=1000 + i,
                wiki_username=name, role='moderator',
            ))
        _db.session.commit()


def _login(client, centralauth_id, username):
    with client.session_transaction() as s:
        s['centralauth_id'] = centralauth_id
        s['wiki_username']  = username
        s['csrf_token']     = CSRF


def _inject(client, text='Hello', sender_id=None):
    body = json.dumps({
        'message_id':   str(uuid.uuid4()),
        'sender_id':    sender_id or str(uuid.uuid4()),
        'screen_name':  'User',
        'message':      text,
        'message_type': 'text',
    }).encode()
    sig = 'sha256=' + hmac.new(HMAC_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = client.post(
        f'/webhook/channel/{CHANNEL_ID}',
        data=body,
        headers={'X-Eventyay-Signature': sig, 'Content-Type': 'application/json'},
    )
    assert r.status_code == 200, f'inject failed {r.status_code}: {r.data}'


def _last_id(app):
    with app.app_context():
        m = Message.query.filter_by(channel_id=CHANNEL_ID).order_by(Message.id.desc()).first()
        return m.id


def _status(app, mid):
    with app.app_context():
        return Message.query.get(mid).status


def _logs(app, mid):
    with app.app_context():
        return ModerationLog.query.filter_by(message_id=mid).count()


def _act(client, mid, action):
    return client.post(
        f'/api/channel/{CHANNEL_ID}/message/{mid}/{action}',
        headers={'X-CSRF-Token': CSRF},
    ).get_json()


# ── Test runner ────────────────────────────────────────────────────────────────

_passed = _failed = 0


def check(name, cond, detail=''):
    global _passed, _failed
    if cond:
        print(f'  PASS  {name}')
        _passed += 1
    else:
        print(f'  FAIL  {name}' + (f'  ({detail})' if detail else ''))
        _failed += 1


def run(app, c1, c2):
    _login(c1, 1001, 'Mod1')
    _login(c2, 1002, 'Mod2')

    # [1] Both approve the same message — second is superseded
    print('\n[1] Both approve — second superseded, single log entry')
    _inject(c1)
    mid = _last_id(app)
    r1 = _act(c1, mid, 'approve')
    r2 = _act(c2, mid, 'approve')
    check('first approve ok',              r1.get('ok') is True,         str(r1))
    check('second approve superseded',     r2.get('superseded') is True,  str(r2))
    check('status = approved',             _status(app, mid) == 'approved', _status(app, mid))
    check('exactly 1 log entry',           _logs(app, mid) == 1,          _logs(app, mid))

    # [2] Approve then reject — reject wins (rank 3 > rank 2)
    print('\n[2] Approve then reject — reject wins')
    _inject(c1, 'Reject me')
    mid = _last_id(app)
    _act(c1, mid, 'approve')
    r2 = _act(c2, mid, 'reject')
    check('reject ok',       r2.get('ok') is True,          str(r2))
    check('status=rejected', _status(app, mid) == 'rejected', _status(app, mid))
    check('2 log entries',   _logs(app, mid) == 2,            _logs(app, mid))

    # [3] Reject then approve — approve blocked (rank 2 <= rank 3)
    print('\n[3] Reject then approve — approve blocked')
    _inject(c1, 'Already rejected')
    mid = _last_id(app)
    _act(c1, mid, 'reject')
    r2 = _act(c2, mid, 'approve')
    check('approve superseded',      r2.get('superseded') is True,  str(r2))
    check('status stays rejected',   _status(app, mid) == 'rejected', _status(app, mid))
    check('still 1 log entry',       _logs(app, mid) == 1,           _logs(app, mid))

    # [4] Highlight then approve — approve wins (rank 2 > rank 1)
    print('\n[4] Highlight then approve — approve wins')
    _inject(c1, 'Highlight first')
    mid = _last_id(app)
    _act(c1, mid, 'highlight')
    r2 = _act(c2, mid, 'approve')
    check('approve ok',      r2.get('ok') is True,          str(r2))
    check('status=approved', _status(app, mid) == 'approved', _status(app, mid))
    check('2 log entries',   _logs(app, mid) == 2,            _logs(app, mid))

    # [5] Highlight then reject — reject wins (rank 3 > rank 1)
    print('\n[5] Highlight then reject — reject wins')
    _inject(c1, 'Highlight then reject')
    mid = _last_id(app)
    _act(c1, mid, 'highlight')
    _act(c2, mid, 'reject')
    check('status=rejected', _status(app, mid) == 'rejected', _status(app, mid))

    # [6] Approve then highlight — highlight blocked (rank 1 <= rank 2)
    print('\n[6] Approve then highlight — highlight blocked')
    _inject(c1, 'Approve first')
    mid = _last_id(app)
    _act(c1, mid, 'approve')
    r2 = _act(c2, mid, 'highlight')
    check('highlight superseded',  r2.get('superseded') is True,  str(r2))
    check('status stays approved', _status(app, mid) == 'approved', _status(app, mid))


def main():
    app = _make_app()
    _setup(app)
    c1 = app.test_client()
    c2 = app.test_client()
    run(app, c1, c2)
    print(f'\n{"─" * 40}')
    print(f'{_passed} passed   {_failed} failed')
    sys.exit(0 if _failed == 0 else 1)


if __name__ == '__main__':
    main()
