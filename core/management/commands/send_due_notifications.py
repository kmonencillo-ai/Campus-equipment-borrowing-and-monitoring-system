from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from core.email_utils import (
    send_due_reminder_email,
    send_overdue_borrower_email,
    send_overdue_staff_alert_email,
)
from core.models import NotificationLog, SystemSettings, Transaction


DUE_SOON_EVENT = 'Due Date Reminder Email'
DUE_TODAY_EVENT = 'Due Today Reminder Email'
OVERDUE_BORROWER_EVENT = 'Overdue Borrower Email'
OVERDUE_STAFF_EVENT = 'Overdue Staff Alert Email'


class Command(BaseCommand):
    help = 'Send borrower due-date reminders and overdue email alerts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without changing statuses, sending email, or writing notification logs.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        settings_obj = SystemSettings.load()
        today = timezone.localdate()

        overdue_updated = 0
        if not dry_run:
            overdue_updated = self.mark_overdue_transactions(settings_obj)

        sent_count = 0
        skipped_count = 0

        reminder_days = int(settings_obj.reminder_days_before_due or 0)
        if reminder_days > 0:
            due_soon_count, due_soon_skipped = self.process_due_reminders(
                event_type=DUE_SOON_EVENT,
                target_date=today + timedelta(days=reminder_days),
                label=f'in {reminder_days} day(s)',
                dry_run=dry_run,
            )
            sent_count += due_soon_count
            skipped_count += due_soon_skipped

        due_today_count, due_today_skipped = self.process_due_reminders(
            event_type=DUE_TODAY_EVENT,
            target_date=today,
            label='today',
            dry_run=dry_run,
        )
        sent_count += due_today_count
        skipped_count += due_today_skipped

        overdue_count, overdue_skipped = self.process_overdue_alerts(dry_run=dry_run)
        sent_count += overdue_count
        skipped_count += overdue_skipped

        mode = 'DRY RUN: ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{mode}Due notification pass complete. '
                f'Overdue updated: {overdue_updated}. '
                f'Emails attempted: {sent_count}. '
                f'Duplicates skipped: {skipped_count}.'
            )
        )

    def mark_overdue_transactions(self, settings_obj):
        now = timezone.now()
        overdue_cutoff = now - timedelta(days=int(settings_obj.overdue_grace_period_days or 0))
        updated_count = 0

        with db_transaction.atomic():
            overdue_transactions = Transaction.objects.select_for_update().select_related('item').filter(
                status='Borrowed',
                due_time__isnull=False,
                due_time__lt=overdue_cutoff,
                borrower__is_archived=False,
                item__is_archived=False,
            )

            for transaction_record in overdue_transactions:
                transaction_record.status = 'Overdue'
                transaction_record.save(update_fields=['status', 'updated_at'])
                if transaction_record.item.status != 'Borrowed':
                    transaction_record.item.status = 'Borrowed'
                    transaction_record.item.save(update_fields=['status', 'updated_at'])
                updated_count += 1

        return updated_count

    def process_due_reminders(self, event_type, target_date, label, dry_run=False):
        start_dt, end_dt = self.day_bounds(target_date)
        transactions = Transaction.objects.select_related('borrower', 'item').filter(
            status='Borrowed',
            due_time__gte=start_dt,
            due_time__lte=end_dt,
            borrower__is_archived=False,
            item__is_archived=False,
        ).order_by('due_time')

        attempted = 0
        duplicate_skips = 0
        today = timezone.localdate()

        for transaction_record in transactions:
            if self.notification_already_logged(event_type, transaction_record, today):
                duplicate_skips += 1
                continue

            attempted += 1
            if dry_run:
                self.stdout.write(f'DRY RUN: would send {event_type} for transaction {transaction_record.pk}.')
                continue

            result = send_due_reminder_email(transaction_record, label)
            self.log_email_notification(event_type, result, transaction_record)

        return attempted, duplicate_skips

    def process_overdue_alerts(self, dry_run=False):
        transactions = Transaction.objects.select_related('borrower', 'item').filter(
            status='Overdue',
            borrower__is_archived=False,
            item__is_archived=False,
        ).order_by('due_time')

        staff_users_with_email = User.objects.filter(
            is_active=True,
            profile__role__in=['Admin', 'Staff'],
        ).exclude(email='')
        staff_recipients = list(
            staff_users_with_email.filter(profile__notify_by_email=True)
            .values_list('email', flat=True)
            .distinct()
        )
        staff_email_disabled = staff_users_with_email.exists() and not staff_recipients

        attempted = 0
        duplicate_skips = 0

        for transaction_record in transactions:
            if self.notification_already_logged(OVERDUE_BORROWER_EVENT, transaction_record):
                duplicate_skips += 1
            else:
                attempted += 1
                if dry_run:
                    self.stdout.write(
                        f'DRY RUN: would send {OVERDUE_BORROWER_EVENT} for transaction {transaction_record.pk}.'
                    )
                else:
                    result = send_overdue_borrower_email(transaction_record)
                    self.log_email_notification(OVERDUE_BORROWER_EVENT, result, transaction_record)

            if self.notification_already_logged(OVERDUE_STAFF_EVENT, transaction_record):
                duplicate_skips += 1
            else:
                attempted += 1
                if dry_run:
                    self.stdout.write(
                        f'DRY RUN: would send {OVERDUE_STAFF_EVENT} for transaction {transaction_record.pk}.'
                    )
                else:
                    result = send_overdue_staff_alert_email(transaction_record, staff_recipients)
                    if staff_email_disabled:
                        result['error'] = 'Staff/admin email notifications are disabled for every recipient.'
                    self.log_email_notification(OVERDUE_STAFF_EVENT, result, transaction_record)

        return attempted, duplicate_skips

    def notification_already_logged(self, event_type, transaction_record, created_date=None):
        existing_logs = NotificationLog.objects.filter(
            channel='Email',
            event_type=event_type,
            transaction=transaction_record,
            status__in=['Sent', 'Skipped'],
        )
        if created_date:
            existing_logs = existing_logs.filter(created_at__date=created_date)
        return existing_logs.exists()

    def log_email_notification(self, event_type, result, transaction_record):
        NotificationLog.objects.create(
            channel='Email',
            event_type=event_type,
            message=result.get('message', ''),
            status=result.get('status', 'failed').title(),
            recipient=result.get('recipient', '')[:255],
            transaction=transaction_record,
            error_message=result.get('error', ''),
        )

    def day_bounds(self, target_date):
        start_dt = timezone.make_aware(datetime.combine(target_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(target_date, time.max))
        return start_dt, end_dt
