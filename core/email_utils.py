from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import SystemSettings


def send_system_email(subject, message, recipients):
    clean_recipients = [recipient.strip() for recipient in recipients if recipient and recipient.strip()]
    recipient_text = ', '.join(clean_recipients)

    if not clean_recipients:
        return {
            'status': 'skipped',
            'recipient': '',
            'message': message,
            'error': 'No email recipient is configured.',
        }

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=clean_recipients,
            fail_silently=False,
        )
    except Exception as exc:
        return {
            'status': 'failed',
            'recipient': recipient_text,
            'message': message,
            'error': str(exc),
        }

    return {
        'status': 'sent',
        'recipient': recipient_text,
        'message': message,
        'error': '',
    }


def send_borrow_receipt_email(transaction_record, processed_by=None):
    borrower = transaction_record.borrower
    item = transaction_record.item
    recipient = (borrower.email or '').strip()
    school_name = SystemSettings.load().school_name
    due_time = (
        timezone.localtime(transaction_record.due_time).strftime('%Y-%m-%d %H:%M')
        if transaction_record.due_time
        else 'No due time'
    )
    borrow_time = timezone.localtime(transaction_record.borrow_time).strftime('%Y-%m-%d %H:%M')
    processor = processed_by.username if processed_by else 'System'

    subject = f'{school_name} borrow receipt - {item.item_name}'
    message = (
        f'Hello {borrower.full_name},\n\n'
        f'This is your borrowing receipt from {school_name}.\n\n'
        f'Item: {item.item_name}\n'
        f'Item Code: {item.item_code}\n'
        f'Borrow Time: {borrow_time}\n'
        f'Due Time: {due_time}\n'
        f'Borrowed Condition: {transaction_record.borrowed_condition}\n'
        f'Processed By: {processor}\n\n'
        'Please return the item on or before the due time.'
    )

    if not recipient:
        result = send_system_email(subject, message, [])
        result['error'] = 'Borrower email is not set.'
        return result

    return send_system_email(subject, message, [recipient])


def send_due_reminder_email(transaction_record, label):
    borrower = transaction_record.borrower
    item = transaction_record.item
    recipient = (borrower.email or '').strip()
    school_name = SystemSettings.load().school_name
    due_time = timezone.localtime(transaction_record.due_time).strftime('%Y-%m-%d %H:%M')

    subject = f'{school_name} reminder - {item.item_name} is due {label}'
    message = (
        f'Hello {borrower.full_name},\n\n'
        f'This is a reminder from {school_name}.\n\n'
        f'Item: {item.item_name}\n'
        f'Item Code: {item.item_code}\n'
        f'Due Time: {due_time}\n'
        f'Current Status: {transaction_record.status}\n\n'
        'Please return the item on time or contact staff if you need help.'
    )

    if not recipient:
        result = send_system_email(subject, message, [])
        result['error'] = 'Borrower email is not set.'
        return result

    return send_system_email(subject, message, [recipient])


def send_overdue_borrower_email(transaction_record):
    borrower = transaction_record.borrower
    item = transaction_record.item
    recipient = (borrower.email or '').strip()
    school_name = SystemSettings.load().school_name
    due_time = timezone.localtime(transaction_record.due_time).strftime('%Y-%m-%d %H:%M')

    subject = f'{school_name} overdue notice - {item.item_name}'
    message = (
        f'Hello {borrower.full_name},\n\n'
        f'Our records show this borrowed item is overdue.\n\n'
        f'Item: {item.item_name}\n'
        f'Item Code: {item.item_code}\n'
        f'Due Time: {due_time}\n\n'
        'Please return it as soon as possible or coordinate with the equipment office.'
    )

    if not recipient:
        result = send_system_email(subject, message, [])
        result['error'] = 'Borrower email is not set.'
        return result

    return send_system_email(subject, message, [recipient])


def send_overdue_staff_alert_email(transaction_record, recipients):
    borrower = transaction_record.borrower
    item = transaction_record.item
    school_name = SystemSettings.load().school_name
    due_time = timezone.localtime(transaction_record.due_time).strftime('%Y-%m-%d %H:%M')

    subject = f'{school_name} admin alert - overdue item'
    message = (
        f'An item is overdue in {school_name}.\n\n'
        f'Borrower: {borrower.full_name}\n'
        f'School ID: {borrower.school_id}\n'
        f'Item: {item.item_name}\n'
        f'Item Code: {item.item_code}\n'
        f'Due Time: {due_time}\n'
        f'Transaction ID: {transaction_record.pk}\n\n'
        'Please follow up with the borrower.'
    )

    return send_system_email(subject, message, recipients)
