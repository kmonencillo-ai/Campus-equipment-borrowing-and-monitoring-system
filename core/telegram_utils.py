import json
from urllib import error, parse, request

from django.conf import settings


def send_telegram_message(message):
    """
    Send a message to Telegram using the Bot API.

    This helper is intentionally dependency-free so the app can still start
    even when Telegram is not configured in the environment.
    """

    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = str(getattr(settings, 'TELEGRAM_CHAT_ID', '')).strip()

    if not bot_token or not chat_id:
        return {
            'ok': False,
            'status': 'skipped',
            'recipient': chat_id,
            'error': 'Telegram bot token or chat ID is not configured.',
        }

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = parse.urlencode({
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
    }).encode()

    try:
        with request.urlopen(url, data=payload, timeout=10) as response:
            return {
                'ok': True,
                'status': 'sent',
                'recipient': chat_id,
                'response': json.loads(response.read().decode('utf-8')),
            }
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            'ok': False,
            'status': 'failed',
            'recipient': chat_id,
            'error': str(exc),
        }
