import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, render_template, abort, current_app
from sqlalchemy import or_
from src.models import db, Channel, Message, Blacklist, GlobalBlacklist, BlockedPattern, Whitelist
from src.utils import levenshtein, parse_likely_languages

webhook_bp = Blueprint('webhook', __name__)


def _verify_hmac(secret: str, body: bytes, signature: str) -> bool:
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@webhook_bp.get('/webhook/channel/<channel_id>')
def webhook_challenge(channel_id: str):
    Channel.query.get_or_404(channel_id)
    challenge = request.args.get('challenge', '')
    if not challenge:
        abort(400)
    return jsonify({'challenge': challenge})


@webhook_bp.post('/webhook/channel/<channel_id>')
def webhook_receive(channel_id: str):
    channel = Channel.query.get(channel_id)
    if not channel or not channel.is_active:
        abort(404)
    body = request.get_data()
    sig = request.headers.get('X-Eventyay-Signature', '')
    if not _verify_hmac(channel.webhook_hmac_secret, body, sig):
        abort(403)
    try:
        data = json.loads(body)
    except ValueError:
        abort(400)
    ts_str = data.get('timestamp', '')
    if ts_str:
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 300:
                return jsonify({'ok': False, 'error': 'timestamp too old'}), 400
        except ValueError:
            pass
    _process_message(channel, data)
    return jsonify({'ok': True})


@webhook_bp.get('/dev/mock/<channel_id>')
def dev_mock_page(channel_id: str):
    if not current_app.debug:
        abort(404)
    channel = Channel.query.get_or_404(channel_id)
    return render_template('dev_mock.html', channel=channel)


@webhook_bp.post('/dev/inject/<channel_id>')
def dev_inject(channel_id: str):
    if not current_app.debug:
        abort(404)
    channel = Channel.query.get_or_404(channel_id)
    data = request.get_json(force=True) or {}
    data.setdefault('message_id', str(uuid.uuid4()))
    data.setdefault('timestamp', datetime.now(timezone.utc).isoformat())
    data.setdefault('screen_name', 'TestUser')
    data.setdefault('message', 'Test message')
    data.setdefault('message_type', 'text')
    _process_message(channel, data)
    return jsonify({'ok': True})


def _is_blocked(channel: Channel, screen_name: str, sender_id: str | None, centralauth_id: int | None) -> bool:
    conditions: list = [GlobalBlacklist.screen_name == screen_name]
    if centralauth_id:
        conditions.append(GlobalBlacklist.centralauth_id == centralauth_id)
    if sender_id:
        conditions.append(GlobalBlacklist.sender_id == sender_id)
    if GlobalBlacklist.query.filter(or_(*conditions)).first():
        return True
    conditions2: list = [Blacklist.screen_name == screen_name, Blacklist.channel_id == channel.id]
    extra: list = []
    if centralauth_id:
        extra.append(Blacklist.centralauth_id == centralauth_id)
    if sender_id:
        extra.append(Blacklist.sender_id == sender_id)
    base = Blacklist.query.filter(Blacklist.channel_id == channel.id)
    id_conditions = [Blacklist.screen_name == screen_name] + extra
    if base.filter(or_(*id_conditions)).first():
        return True
    return False


def _is_whitelisted(channel: Channel, screen_name: str, sender_id: str | None, centralauth_id: int | None) -> bool:
    conditions: list = []
    if sender_id:
        conditions.append(Whitelist.sender_id == sender_id)
    if centralauth_id:
        conditions.append(Whitelist.centralauth_id == centralauth_id)
    if screen_name:
        conditions.append(Whitelist.screen_name == screen_name)
    if not conditions:
        return False
    return bool(
        Whitelist.query
        .filter(Whitelist.channel_id == channel.id)
        .filter(or_(*conditions))
        .first()
    )


def _matches_blocked_pattern(channel_id: str, text: str) -> bool:
    patterns = BlockedPattern.query.filter_by(channel_id=channel_id).all()
    return any(levenshtein(text, p.pattern_text) <= 2 for p in patterns)


def _detect_language(channel: Channel, text: str, user_language: str | None) -> str:
    if not channel.language_detection_enabled:
        return user_language or channel.default_language
    try:
        from lingua import LanguageDetectorBuilder, Language  # type: ignore[import]
        likely = parse_likely_languages(channel.likely_languages)
        langs = [Language[c.upper()] for c in likely if hasattr(Language, c.upper())] or list(Language)
        detector = LanguageDetectorBuilder.from_languages(*langs).build()
        results = detector.compute_language_confidence_values(text)
        if results and results[0].value >= 0.75:
            return results[0].language.iso_code_639_1.name.lower()
    except Exception:
        pass
    return user_language or channel.default_language


def _process_message(channel: Channel, data: dict) -> None:
    sender_id    = str(data['sender_id']) if data.get('sender_id') else None
    raw_name     = (data.get('screen_name') or '').strip()
    if raw_name:
        screen_name = raw_name
    else:
        # No screen name: assign a persistent "Anonymous #N" label for this channel
        channel.anonymous_counter += 1
        screen_name = f'{channel.anonymous_label} #{channel.anonymous_counter}'
        db.session.flush()  # write the incremented counter before commit
    centralauth_id = int(data['centralauth_id']) if data.get('centralauth_id') else None
    message_text = (data.get('message') or '').strip()
    message_type = data.get('message_type', 'text')
    eventyay_id  = data.get('message_id')

    if eventyay_id and Message.query.filter_by(
        channel_id=channel.id, eventyay_message_id=eventyay_id
    ).first():
        return

    if _is_blocked(channel, screen_name, sender_id, centralauth_id):
        return

    if message_type == 'text' and _matches_blocked_pattern(channel.id, message_text):
        return

    status = 'queued'
    if _is_whitelisted(channel, screen_name, sender_id, centralauth_id):
        status = 'approved'
    elif message_type == 'emoji' and channel.emoji_auto_approve:
        cutoff = datetime.utcnow() - timedelta(seconds=10)
        if Message.query.filter(
            Message.channel_id == channel.id,
            Message.message == message_text,
            Message.message_type == 'emoji',
            Message.status.in_(['approved', 'highlighted']),
            Message.processed_at >= cutoff,
        ).first():
            status = 'approved'

    detected_language = None
    if message_type == 'text':
        detected_language = _detect_language(channel, message_text, data.get('user_language'))

    msg = Message(
        eventyay_message_id=eventyay_id,
        channel_id=channel.id,
        screen_name=screen_name,
        sender_id=sender_id,
        centralauth_id=centralauth_id,
        message=message_text,
        message_type=message_type,
        meta=json.dumps(data.get('meta') or {}),
        profile_img=data.get('profile_img'),
        user_language=data.get('user_language'),
        detected_language=detected_language,
        status=status,
        arrived_at=datetime.utcnow(),
        processed_at=datetime.utcnow() if status == 'approved' else None,
    )
    db.session.add(msg)
    db.session.commit()
