import functools
import hmac
from flask import session, redirect, url_for, request, abort, current_app


def current_centralauth_id() -> int | None:
    return session.get('centralauth_id')


def current_wiki_username() -> str | None:
    return session.get('wiki_username')


def is_superadmin() -> bool:
    return current_wiki_username() in current_app.config.get('SUPERADMIN_USERS', [])


def get_channel_role(channel_id: str) -> str | None:
    from src.models import ChannelMember
    uid = current_centralauth_id()
    if uid is None:
        return None
    member = ChannelMember.query.filter_by(channel_id=channel_id, centralauth_id=uid).first()
    return member.role if member else None


def verify_csrf() -> None:
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    expected = session.get('csrf_token', '')
    if not token or not hmac.compare_digest(str(token), str(expected)):
        abort(403)


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if current_centralauth_id() is None:
            if request.path.startswith('/api/'):
                abort(401)
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if current_centralauth_id() is None:
            return redirect(url_for('login'))
        if not is_superadmin():
            abort(403)
        return f(*args, **kwargs)
    return decorated


def channel_role_required(*roles):
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if current_centralauth_id() is None:
                if request.path.startswith('/api/'):
                    abort(401)
                return redirect(url_for('login'))
            if is_superadmin():
                return f(*args, **kwargs)
            channel_id = kwargs.get('channel_id')
            if get_channel_role(channel_id) not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
