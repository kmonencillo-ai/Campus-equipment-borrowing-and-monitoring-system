from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from core.models import NotificationLog
from core.telegram_utils import send_telegram_message


class Command(BaseCommand):
    help = 'Send a test Telegram notification using the configured bot token and chat ID.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--message',
            default='',
            help='Optional custom message body for the Telegram test.',
        )

    def handle(self, *args, **options):
        message = options['message'].strip() or (
            "🧪 <b>Telegram Test</b>\n\n"
            "Your Campus Equipment Borrowing & Monitoring System Telegram integration is working.\n"
            f"Time: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()
        chat_id = str(getattr(settings, 'TELEGRAM_CHAT_ID', '')).strip()

        if not token or not chat_id:
            raise CommandError('TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.')

        result = send_telegram_message(message)
        NotificationLog.objects.create(
            channel='Telegram',
            event_type='Manual Telegram Test',
            message=message,
            status=result.get('status', 'failed').title(),
            recipient=result.get('recipient', chat_id),
            error_message=result.get('error', ''),
        )

        if result.get('ok'):
            self.stdout.write(self.style.SUCCESS(f"Telegram test sent successfully to chat {chat_id}."))
            return

        raise CommandError(f"Telegram test failed: {result.get('error', 'Unknown error')}")
