import hmac
from flask import Blueprint, request, Response, abort
from src.models import Channel, Message

display_bp = Blueprint('display', __name__)
RSS_LIMIT = 50


def _check_token(channel: Channel) -> None:
    if not channel.is_public:
        token = request.args.get('token', '')
        if not hmac.compare_digest(token, channel.display_token):
            abort(403)


def _build_rss(channel: Channel, highlights_only: bool) -> Response:
    _check_token(channel)
    statuses = ['highlighted'] if highlights_only else ['approved', 'highlighted']
    messages = (
        Message.query
        .filter(Message.channel_id == channel.id, Message.status.in_(statuses))
        .order_by(Message.processed_at.desc())
        .limit(RSS_LIMIT)
        .all()
    )

    def rfc2822(dt):
        return dt.strftime('%a, %d %b %Y %H:%M:%S +0000') if dt else ''

    items = []
    for msg in messages:
        items.append(
            f'    <item>\n'
            f'      <title>{_xml(msg.screen_name)}</title>\n'
            f'      <description>{_xml(msg.message)}</description>\n'
            f'      <pubDate>{rfc2822(msg.processed_at)}</pubDate>\n'
            f'      <guid isPermaLink="false">{msg.id}</guid>\n'
            f'    </item>'
        )

    suffix = ' — Highlights' if highlights_only else ''
    last_build = rfc2822(messages[0].processed_at) if messages else ''
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        f'    <title>{_xml(channel.name + suffix)}</title>\n'
        f'    <description>{_xml(channel.description or "")}</description>\n'
        f'    <link>{_xml(request.url)}</link>\n'
        f'    <lastBuildDate>{last_build}</lastBuildDate>\n'
        + '\n'.join(items) + '\n'
        '  </channel>\n'
        '</rss>\n'
    )
    return Response(xml, content_type='application/rss+xml; charset=utf-8')


def _xml(text: str) -> str:
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


@display_bp.get('/rss/<channel_id>')
def rss_all(channel_id: str):
    return _build_rss(Channel.query.get_or_404(channel_id), highlights_only=False)


@display_bp.get('/rss/<channel_id>/highlights')
def rss_highlights(channel_id: str):
    return _build_rss(Channel.query.get_or_404(channel_id), highlights_only=True)
