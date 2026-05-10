import csv
import base64
import hashlib
from datetime import datetime, time, timedelta
from functools import wraps
from io import BytesIO, StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderSVG

from .models import Borrower, Item, Transaction, ActivityLog, MaintenanceRecord, NotificationLog, SystemSettings, UserProfile
from .forms import (
    BorrowerForm,
    BorrowerSelfServiceLookupForm,
    ItemForm,
    MaintenanceRecordForm,
    ReturnTransactionForm,
    TransactionForm,
    CustomAuthenticationForm,
    CustomUserRegistrationForm,
    SystemSettingsForm,
    UserUpdateForm,
    SelfProfileForm,
)
from .email_utils import send_borrow_receipt_email
from .telegram_utils import send_telegram_message


ADMIN_ROLE = 'Admin'
STAFF_ROLE = 'Staff'


def build_qr_svg_data_uri(value, size=140):
    qr = QrCodeWidget(value)
    bounds = qr.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(qr)
    svg = renderSVG.drawToString(drawing)
    encoded_svg = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded_svg}'


def ensure_user_profile(user):
    if not user or not user.is_authenticated:
        return None
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def user_prefers_notification(user, channel):
    profile = ensure_user_profile(user)
    if profile is None:
        return True
    if channel == 'Email':
        return profile.notify_by_email
    if channel == 'Telegram':
        return profile.notify_by_telegram
    return True


def send_preferred_telegram_message(user, message):
    if user_prefers_notification(user, 'Telegram'):
        return send_telegram_message(message)
    return {
        'status': 'skipped',
        'recipient': '',
        'error': 'Telegram notifications are disabled for this user.',
    }


def user_has_role(user, allowed_roles):
    profile = ensure_user_profile(user)
    return profile is not None and profile.role in allowed_roles


def admin_exists():
    return UserProfile.objects.filter(role=ADMIN_ROLE).exists()


def role_required(*allowed_roles):
    def decorator(view_func):
        @login_required(login_url='/login/')
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not user_has_role(request.user, allowed_roles):
                messages.error(request, "You do not have permission to access that page.")
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def admin_required(view_func):
    return role_required(ADMIN_ROLE)(view_func)


def staff_required(view_func):
    return role_required(ADMIN_ROLE, STAFF_ROLE)(view_func)


def staff_or_admin_required(view_func):
    return role_required(ADMIN_ROLE, STAFF_ROLE)(view_func)


def log_activity(action, description, user=None):
    ActivityLog.objects.create(
        user=user,
        action=action,
        description=description
    )


def log_notification(channel, event_type, message, status, recipient='', user=None, transaction_record=None, error_message=''):
    NotificationLog.objects.create(
        channel=channel,
        event_type=event_type,
        message=message,
        status=status,
        recipient=recipient,
        triggered_by=user,
        transaction=transaction_record,
        error_message=error_message,
    )


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def get_login_rate_limit_key(request, username):
    identifier = f"{get_client_ip(request)}:{(username or '').strip().lower()}"
    digest = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    return f'login-rate-limit:{digest}'


def is_login_rate_limited(cache_key):
    attempt_limit = max(int(getattr(settings, 'LOGIN_RATE_LIMIT_ATTEMPTS', 5)), 0)
    return bool(attempt_limit and cache.get(cache_key, 0) >= attempt_limit)


def record_login_failure(cache_key):
    window_seconds = max(int(getattr(settings, 'LOGIN_RATE_LIMIT_WINDOW', 300)), 1)
    failed_attempts = cache.get(cache_key, 0) + 1
    cache.set(cache_key, failed_attempts, timeout=window_seconds)


def clear_login_failures(cache_key):
    cache.delete(cache_key)


def get_filtered_querystring(request):
    querydict = request.GET.copy()
    querydict.pop('page', None)
    return querydict.urlencode()


def get_export_querystring(request):
    querydict = request.GET.copy()
    querydict.pop('page', None)
    querydict.pop('export', None)
    return querydict.urlencode()


def paginate_queryset(request, queryset, per_page=10):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    return page_obj, paginator.count, get_filtered_querystring(request)


def get_system_settings():
    return SystemSettings.load()


def get_database_readiness():
    database_config = settings.DATABASES['default']
    engine = database_config.get('ENGINE', '')
    provider = 'Supabase' if getattr(settings, 'SUPABASE_DATABASE_URL', '') else 'SQLite'

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        status = 'Connected'
    except Exception:
        status = 'Unavailable'

    return {
        'provider': provider,
        'status': status,
        'engine': engine.rsplit('.', 1)[-1] if engine else 'unknown',
        'host': database_config.get('HOST') or 'local',
        'name': Path(str(database_config.get('NAME', ''))).name if provider == 'SQLite' else database_config.get('NAME', ''),
        'sslmode': database_config.get('OPTIONS', {}).get('sslmode', ''),
        'backup_dir': settings.BACKUP_DIR,
        'debug': settings.DEBUG,
        'lan_hosts_enabled': '*' in settings.ALLOWED_HOSTS,
    }


def get_recent_backups(limit=5):
    backup_dir = Path(settings.BACKUP_DIR)
    if not backup_dir.exists():
        return []

    backup_files = [
        path for path in backup_dir.glob('backup-*.json')
        if '.manifest.' not in path.name
    ]
    backup_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    return [
        {
            'name': path.name,
            'size_kb': max(1, int(path.stat().st_size / 1024)),
            'created_at': datetime.fromtimestamp(path.stat().st_mtime),
            'manifest_name': path.with_name(path.stem + '.manifest.json').name
            if path.with_name(path.stem + '.manifest.json').exists()
            else '',
        }
        for path in backup_files[:limit]
    ]


def get_notification_readiness():
    today = timezone.localdate()
    settings_obj = get_system_settings()
    reminder_days = int(settings_obj.reminder_days_before_due or 0)
    due_soon_date = today + timedelta(days=reminder_days) if reminder_days > 0 else today
    due_soon_start = timezone.make_aware(datetime.combine(due_soon_date, time.min))
    due_soon_end = timezone.make_aware(datetime.combine(due_soon_date, time.max))
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    today_end = timezone.make_aware(datetime.combine(today, time.max))
    active_transactions = Transaction.objects.filter(
        status__in=['Borrowed', 'Overdue'],
        borrower__is_archived=False,
        item__is_archived=False,
    )
    last_log = NotificationLog.objects.order_by('-created_at').first()

    return {
        'due_soon_count': active_transactions.filter(
            status='Borrowed',
            due_time__gte=due_soon_start,
            due_time__lte=due_soon_end,
        ).count() if reminder_days > 0 else 0,
        'due_today_count': active_transactions.filter(
            status='Borrowed',
            due_time__gte=today_start,
            due_time__lte=today_end,
        ).count(),
        'overdue_count': active_transactions.filter(status='Overdue').count(),
        'last_notification_at': last_log.created_at if last_log else None,
        'reminder_days_before_due': reminder_days,
    }


def public_item_availability(request):
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    category = request.GET.get('category', '').strip()

    items = Item.objects.filter(is_archived=False).order_by('category', 'item_name')
    categories = (
        Item.objects.filter(is_archived=False)
        .exclude(category='')
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    if search:
        items = items.filter(
            Q(item_name__icontains=search)
            | Q(category__icontains=search)
            | Q(description__icontains=search)
        )

    if status:
        items = items.filter(status=status)

    if category:
        items = items.filter(category=category)

    summary = {
        'total': items.count(),
        'available': items.filter(status='Available').count(),
        'borrowed': items.filter(status='Borrowed').count(),
        'maintenance': items.filter(status='Maintenance').count(),
    }
    items, item_total, querystring = paginate_queryset(request, items, per_page=12)

    return render(request, 'core/public_item_availability.html', {
        'items': items,
        'item_total': item_total,
        'querystring': querystring,
        'categories': categories,
        'summary': summary,
        'search_query': search,
        'selected_status': status,
        'selected_category': category,
    })


def public_item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk, is_archived=False)
    active_transaction = (
        Transaction.objects.filter(
            item=item,
            status__in=['Borrowed', 'Overdue'],
            borrower__is_archived=False,
        )
        .select_related('borrower')
        .order_by('due_time')
        .first()
    )

    return render(request, 'core/public_item_detail.html', {
        'item': item,
        'active_transaction': active_transaction,
    })


def public_borrower_lookup(request):
    form = BorrowerSelfServiceLookupForm(request.GET or None)
    borrower = None
    active_transactions = Transaction.objects.none()
    recent_transactions = Transaction.objects.none()
    lookup_attempted = bool(request.GET)

    if form.is_valid():
        borrower = Borrower.objects.filter(
            school_id__iexact=form.cleaned_data['school_id'],
            email__iexact=form.cleaned_data['email'],
            is_archived=False,
        ).first()
        if borrower:
            transactions = Transaction.objects.select_related('item').filter(
                borrower=borrower,
                item__is_archived=False,
            )
            active_transactions = transactions.filter(status__in=['Borrowed', 'Overdue']).order_by('due_time')
            recent_transactions = transactions.filter(status='Returned').order_by('-return_time')[:5]

    return render(request, 'core/public_borrower_lookup.html', {
        'form': form,
        'borrower': borrower,
        'active_transactions': active_transactions,
        'recent_transactions': recent_transactions,
        'lookup_attempted': lookup_attempted,
    })


def refresh_overdue_transactions():
    now = timezone.now()
    overdue_transactions = Transaction.objects.filter(
        status='Borrowed',
        due_time__isnull=False,
        due_time__lt=now,
    ).select_related('item')

    for transaction in overdue_transactions:
        transaction.status = 'Overdue'
        transaction.save(update_fields=['status'])
        if transaction.item.status != 'Borrowed':
            transaction.item.status = 'Borrowed'
            transaction.item.save(update_fields=['status'])


def build_report_queryset(request):
    refresh_overdue_transactions()

    transactions = Transaction.objects.select_related('borrower', 'item').filter(
        borrower__is_archived=False,
        item__is_archived=False,
    ).order_by('-borrow_time')
    borrowers = Borrower.objects.filter(is_archived=False).order_by('full_name')
    items = Item.objects.filter(is_archived=False).order_by('item_name')

    def normalize_filter(value):
        if value in {None, '', 'None', 'null'}:
            return ''
        return value

    status = normalize_filter(request.GET.get('status'))
    borrower = normalize_filter(request.GET.get('borrower'))
    item = normalize_filter(request.GET.get('item'))
    date_from = normalize_filter(request.GET.get('date_from'))
    date_to = normalize_filter(request.GET.get('date_to'))

    if status:
        transactions = transactions.filter(status=status)

    if borrower:
        transactions = transactions.filter(borrower_id=borrower)

    if item:
        transactions = transactions.filter(item_id=item)

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from:
        start_dt = timezone.make_aware(datetime.combine(parsed_date_from, time.min))
        transactions = transactions.filter(borrow_time__gte=start_dt)

    if parsed_date_to:
        end_dt = timezone.make_aware(datetime.combine(parsed_date_to, time.max))
        transactions = transactions.filter(borrow_time__lte=end_dt)

    summary = {
        'total_records': transactions.count(),
        'borrowed_count': transactions.filter(status='Borrowed').count(),
        'returned_count': transactions.filter(status='Returned').count(),
        'overdue_count': transactions.filter(status='Overdue').count(),
    }

    filters = {
        'borrowers': borrowers,
        'items': items,
        'selected_status': status,
        'selected_borrower': borrower,
        'selected_item': item,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
    }

    return transactions, summary, filters


def build_inventory_summary():
    categories = (
        Item.objects.filter(is_archived=False)
        .values('category')
        .annotate(
            total=Count('id'),
            available=Count('id', filter=Q(status='Available')),
            borrowed=Count('id', filter=Q(status='Borrowed')),
            maintenance=Count('id', filter=Q(status='Maintenance')),
        )
        .order_by('category')
    )

    return [
        {
            'category': entry['category'] or 'Uncategorized',
            'total': entry['total'],
            'available': entry['available'],
            'borrowed': entry['borrowed'],
            'maintenance': entry['maintenance'],
        }
        for entry in categories
    ]


def build_report_tabs(selected_report_type):
    tabs = [
        ('transactions', 'Transactions'),
        ('overdue', 'Overdue'),
        ('inventory', 'Inventory Summary'),
    ]
    return [
        {
            'key': key,
            'label': label,
            'active': key == selected_report_type,
        }
        for key, label in tabs
    ]


def build_dashboard_context():
    refresh_overdue_transactions()

    total_borrowers = Borrower.objects.filter(is_archived=False).count()
    total_items = Item.objects.filter(is_archived=False).count()
    maintenance_items = Item.objects.filter(is_archived=False, status='Maintenance').count()
    active_transactions = Transaction.objects.filter(
        borrower__is_archived=False,
        item__is_archived=False,
    )
    borrowed_items = active_transactions.filter(status='Borrowed').count()
    returned_items = active_transactions.filter(status='Returned').count()
    overdue_items = active_transactions.filter(status='Overdue').count()
    due_today_transactions = Transaction.objects.filter(
        status__in=['Borrowed', 'Overdue'],
        due_time__date=timezone.localdate(),
        borrower__is_archived=False,
        item__is_archived=False,
    )
    due_today_count = due_today_transactions.count()
    due_today_items = due_today_transactions.select_related('borrower', 'item')[:5]
    recent_transactions = active_transactions.select_related('borrower', 'item').order_by('-borrow_time')[:5]
    recent_logs = ActivityLog.objects.select_related('user').order_by('-timestamp')[:6]
    latest_backup = (get_recent_backups(limit=1) or [None])[0]

    category_usage = (
        Item.objects.filter(is_archived=False).values('category')
        .annotate(count=Count('transaction'))
        .order_by('-count', 'category')[:5]
    )
    top_items = (
        active_transactions.values('item__item_name')
        .annotate(count=Count('id'))
        .order_by('-count', 'item__item_name')[:5]
    )
    max_category_count = max([entry['count'] for entry in category_usage], default=1) or 1
    max_item_count = max([entry['count'] for entry in top_items], default=1) or 1

    return {
        'total_borrowers': total_borrowers,
        'total_items': total_items,
        'maintenance_items': maintenance_items,
        'borrowed_items': borrowed_items,
        'returned_items': returned_items,
        'overdue_items': overdue_items,
        'due_today_count': due_today_count,
        'due_today_items': due_today_items,
        'recent_transactions': recent_transactions,
        'recent_logs': recent_logs,
        'failed_notification_count': NotificationLog.objects.filter(status='Failed').count(),
        'latest_backup': latest_backup,
        'category_usage': [
            {
                'label': entry['category'] or 'Uncategorized',
                'count': entry['count'],
                'width': max(18, int((entry['count'] / max_category_count) * 100)),
            }
            for entry in category_usage
        ],
        'top_items': [
            {
                'label': entry['item__item_name'],
                'count': entry['count'],
                'width': max(18, int((entry['count'] / max_item_count) * 100)),
            }
            for entry in top_items
        ],
    }


def export_transactions_csv(transactions):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transaction-report.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Borrower',
        'School ID',
        'Item',
        'Item Code',
        'Status',
        'Borrow Time',
        'Due Time',
        'Return Time',
    ])

    for transaction in transactions:
        writer.writerow([
            transaction.borrower.full_name,
            transaction.borrower.school_id,
            transaction.item.item_name,
            transaction.item.item_code,
            transaction.status,
            timezone.localtime(transaction.borrow_time).strftime('%Y-%m-%d %H:%M'),
            timezone.localtime(transaction.due_time).strftime('%Y-%m-%d %H:%M') if transaction.due_time else '',
            timezone.localtime(transaction.return_time).strftime('%Y-%m-%d %H:%M') if transaction.return_time else '',
        ])

    return response


def export_inventory_summary_csv(inventory_summary):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory-summary-report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Category', 'Total', 'Available', 'Borrowed', 'Maintenance'])
    for row in inventory_summary:
        writer.writerow([
            row['category'],
            row['total'],
            row['available'],
            row['borrowed'],
            row['maintenance'],
        ])

    return response


def export_activity_logs_csv(logs):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="activity-log-export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Timestamp',
        'User',
        'Action',
        'Description',
    ])

    for log in logs:
        user_label = log.user.get_full_name() or log.user.username if log.user else 'System'
        writer.writerow([
            timezone.localtime(log.timestamp).strftime('%Y-%m-%d %H:%M'),
            user_label,
            log.action,
            log.description,
        ])

    return response


def export_inventory_summary_pdf(inventory_summary):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF export requires the 'reportlab' package to be installed.") from exc

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    table_data = [['Category', 'Total', 'Available', 'Borrowed', 'Maintenance']]
    table_data.extend([
        [
            row['category'],
            row['total'],
            row['available'],
            row['borrowed'],
            row['maintenance'],
        ]
        for row in inventory_summary
    ])
    story = [
        Paragraph("Campus Equipment Inventory Summary", styles['Title']),
        Spacer(1, 12),
        Table(table_data, repeatRows=1),
    ]
    story[-1].setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))

    document.build(story)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="inventory-summary-report.pdf"'
    response.write(buffer.getvalue())
    buffer.close()
    return response


def export_transactions_pdf(transactions, summary):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF export requires the 'reportlab' package to be installed.") from exc

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Campus Equipment Transaction Report", styles['Title']),
        Spacer(1, 12),
        Paragraph(
            (
                f"Total Records: {summary['total_records']} | "
                f"Borrowed: {summary['borrowed_count']} | "
                f"Returned: {summary['returned_count']} | "
                f"Overdue: {summary['overdue_count']}"
            ),
            styles['Normal'],
        ),
        Spacer(1, 12),
    ]

    table_data = [[
        'Borrower',
        'Item',
        'Status',
        'Borrow Time',
        'Due Time',
        'Return Time',
    ]]

    for transaction in transactions:
        table_data.append([
            transaction.borrower.full_name,
            transaction.item.item_name,
            transaction.status,
            timezone.localtime(transaction.borrow_time).strftime('%Y-%m-%d %H:%M'),
            timezone.localtime(transaction.due_time).strftime('%Y-%m-%d %H:%M') if transaction.due_time else '',
            timezone.localtime(transaction.return_time).strftime('%Y-%m-%d %H:%M') if transaction.return_time else '',
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    document.build(story)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="transaction-report.pdf"'
    response.write(buffer.getvalue())
    buffer.close()
    return response


def login_view(request):
    if request.user.is_authenticated and user_has_role(request.user, {ADMIN_ROLE, STAFF_ROLE}):
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = CustomAuthenticationForm(request, data=request.POST or None)
    allow_setup_registration = not admin_exists()
    next_url = request.GET.get('next') or request.POST.get('next') or request.session.get('login_next_url', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        request.session['login_next_url'] = next_url
    else:
        next_url = ''
        request.session.pop('login_next_url', None)

    if request.method == 'POST':
        login_cache_key = get_login_rate_limit_key(request, request.POST.get('username', ''))

        if is_login_rate_limited(login_cache_key):
            form.add_error(None, "Too many failed login attempts. Please wait a few minutes before trying again.")
        elif form.is_valid():
            user = form.get_user()
            profile = ensure_user_profile(user)
            selected_role = form.cleaned_data.get('login_role')

            if profile.role not in {ADMIN_ROLE, STAFF_ROLE}:
                record_login_failure(login_cache_key)
                messages.error(request, "Only staff and admin accounts can access the system.")
            elif not user.is_active:
                record_login_failure(login_cache_key)
                messages.error(request, "This account is inactive.")
            elif selected_role and profile.role != selected_role:
                record_login_failure(login_cache_key)
                form.add_error(None, f'This account is registered as {profile.role}. Please choose {profile.role} Access.')
            else:
                clear_login_failures(login_cache_key)
                login(request, user)
                if form.cleaned_data.get('remember_me'):
                    request.session.set_expiry(60 * 60 * 24 * 14)
                else:
                    request.session.set_expiry(0)
                log_activity('Login', f'User "{user.username}" signed in.', user)
                redirect_to = request.session.pop('login_next_url', None) or settings.LOGIN_REDIRECT_URL
                return redirect(redirect_to)
        else:
            record_login_failure(login_cache_key)

    return render(request, 'core/login.html', {
        'form': form,
        'allow_setup_registration': allow_setup_registration,
        'next_url': next_url,
    })


def register_view(request):
    setup_mode = not admin_exists()

    if not setup_mode:
        if not request.user.is_authenticated:
            messages.error(request, "Only admin users can create new accounts.")
            return redirect('/login/')
        if not user_has_role(request.user, {ADMIN_ROLE}):
            messages.error(request, "Only admin users can create new accounts.")
            return redirect('dashboard')

    form = CustomUserRegistrationForm(request.POST or None, include_role=not setup_mode)

    if form.is_valid():
        assigned_role = ADMIN_ROLE if setup_mode else form.cleaned_data['role']
        user = form.save(role=assigned_role)
        success_message = f'{assigned_role} account created successfully.'
        if setup_mode:
            messages.success(request, f"{success_message} You can now log in.")
            return redirect('/login/')

        log_activity('Create User', f'User "{user.username}" was created as {assigned_role}.', request.user)
        messages.success(request, success_message)
        return redirect('user_list')

    return render(request, 'core/register.html', {
        'form': form,
        'setup_mode': setup_mode,
    })


def staff_signup_view(request):
    if not admin_exists():
        messages.error(request, "Create the first administrator account before staff sign-up.")
        return redirect('register')

    if request.user.is_authenticated and user_has_role(request.user, {ADMIN_ROLE, STAFF_ROLE}):
        return redirect('dashboard')

    form = CustomUserRegistrationForm(request.POST or None, include_role=False)

    if form.is_valid():
        user = form.save(role=STAFF_ROLE)
        log_activity('Staff Sign Up', f'Staff account "{user.username}" was created from public sign-up.')
        messages.success(request, "Staff account created successfully. You can now log in.")
        return redirect('login')

    return render(request, 'core/register.html', {
        'form': form,
        'setup_mode': False,
        'staff_signup': True,
    })


@staff_or_admin_required
def dashboard(request):
    return render(request, 'core/dashboard.html', build_dashboard_context())


@staff_or_admin_required
def borrower_list(request):
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    borrowers = Borrower.objects.filter(is_archived=False).annotate(
        active_borrow_count=Count('transaction', filter=Q(transaction__status__in=['Borrowed', 'Overdue'])),
        overdue_borrow_count=Count('transaction', filter=Q(transaction__status='Overdue')),
    ).order_by('full_name')

    if search:
        borrowers = borrowers.filter(
            Q(full_name__icontains=search)
            | Q(school_id__icontains=search)
            | Q(email__icontains=search)
            | Q(program__icontains=search)
            | Q(section__icontains=search)
        )

    if status == 'active':
        borrowers = borrowers.filter(active_status=True)
    elif status == 'inactive':
        borrowers = borrowers.filter(active_status=False)
    elif status == 'has_active':
        borrowers = borrowers.filter(active_borrow_count__gt=0)
    elif status == 'overdue':
        borrowers = borrowers.filter(overdue_borrow_count__gt=0)

    borrowers, borrower_total, querystring = paginate_queryset(request, borrowers)

    return render(request, 'core/borrower_list.html', {
        'borrowers': borrowers,
        'borrower_total': borrower_total,
        'querystring': querystring,
        'search_query': search,
        'selected_status': status,
    })


@staff_or_admin_required
def borrower_detail(request, pk):
    borrower = get_object_or_404(Borrower, pk=pk, is_archived=False)
    status = request.GET.get('status', '').strip()
    transactions = Transaction.objects.select_related('item').filter(
        borrower=borrower,
        item__is_archived=False,
    ).order_by('-borrow_time')

    if status:
        transactions = transactions.filter(status=status)

    transactions, transaction_total, querystring = paginate_queryset(request, transactions)

    return render(request, 'core/borrower_detail.html', {
        'borrower': borrower,
        'transactions': transactions,
        'transaction_total': transaction_total,
        'querystring': querystring,
        'selected_status': status,
        'active_count': Transaction.objects.filter(borrower=borrower, status__in=['Borrowed', 'Overdue']).count(),
        'returned_count': Transaction.objects.filter(borrower=borrower, status='Returned').count(),
        'overdue_count': Transaction.objects.filter(borrower=borrower, status='Overdue').count(),
    })


@staff_or_admin_required
def borrower_archive_list(request):
    search = request.GET.get('search', '').strip()
    borrowers = Borrower.objects.filter(is_archived=True).order_by('-archived_at', 'full_name')

    if search:
        borrowers = borrowers.filter(
            Q(full_name__icontains=search)
            | Q(school_id__icontains=search)
            | Q(email__icontains=search)
            | Q(program__icontains=search)
            | Q(section__icontains=search)
        )

    borrowers, borrower_total, querystring = paginate_queryset(request, borrowers)
    return render(request, 'core/borrower_archive_list.html', {
        'borrowers': borrowers,
        'borrower_total': borrower_total,
        'querystring': querystring,
        'search_query': search,
    })


@staff_required
def borrower_create(request):
    form = BorrowerForm(request.POST or None)
    if form.is_valid():
        borrower = form.save()
        log_activity('Add Borrower', f'Borrower "{borrower.full_name}" was added.', request.user)
        messages.success(request, "Borrower added successfully.")
        return redirect('borrower_list')
    return render(request, 'core/borrower_form.html', {'form': form})


@staff_required
def borrower_edit(request, pk):
    borrower = get_object_or_404(Borrower, pk=pk, is_archived=False)
    form = BorrowerForm(request.POST or None, instance=borrower)
    if form.is_valid():
        borrower = form.save()
        log_activity('Edit Borrower', f'Borrower "{borrower.full_name}" was updated.', request.user)
        messages.success(request, "Borrower updated successfully.")
        return redirect('borrower_list')
    return render(request, 'core/borrower_form.html', {'form': form})


@staff_required
def borrower_delete(request, pk):
    borrower = get_object_or_404(Borrower, pk=pk, is_archived=False)

    active_transactions = Transaction.objects.filter(borrower=borrower, status__in=['Borrowed', 'Overdue']).exists()
    if active_transactions:
        messages.error(request, "Cannot archive borrower with active borrowed items.")
        return redirect('borrower_list')

    if request.method == 'POST':
        borrower_name = borrower.full_name
        borrower.is_archived = True
        borrower.active_status = False
        borrower.archived_at = timezone.now()
        borrower.save(update_fields=['is_archived', 'active_status', 'archived_at'])
        log_activity('Archive Borrower', f'Borrower "{borrower_name}" was archived.', request.user)
        messages.success(request, "Borrower archived.")
        return redirect('borrower_list')

    return render(request, 'core/confirm_delete.html', {
        'object_name': borrower.full_name,
        'object_type': 'Borrower',
        'action_label': 'Archive',
        'cancel_url': '/borrowers/',
    })


@staff_required
def borrower_restore(request, pk):
    if request.method != 'POST':
        messages.error(request, "Borrower restore requests must be submitted from the archive page.")
        return redirect('borrower_archive_list')

    borrower = get_object_or_404(Borrower, pk=pk, is_archived=True)
    borrower.is_archived = False
    borrower.active_status = True
    borrower.archived_at = None
    borrower.save(update_fields=['is_archived', 'active_status', 'archived_at'])
    log_activity('Restore Borrower', f'Borrower "{borrower.full_name}" was restored from archive.', request.user)
    messages.success(request, "Borrower restored successfully.")
    return redirect('borrower_archive_list')


@staff_required
def borrower_purge(request, pk):
    if request.method != 'POST':
        messages.error(request, "Borrower deletion requests must be submitted from the archive page.")
        return redirect('borrower_archive_list')

    borrower = get_object_or_404(Borrower, pk=pk, is_archived=True)

    borrower_name = borrower.full_name
    with transaction.atomic():
        deleted_transactions, _ = Transaction.objects.filter(borrower=borrower).delete()
        borrower.delete()

    log_activity(
        'Delete Borrower Permanently',
        f'Archived borrower "{borrower_name}" was permanently deleted with {deleted_transactions} related transaction(s).',
        request.user,
    )
    messages.success(request, "Archived borrower and related transactions deleted permanently.")
    return redirect('borrower_archive_list')


@staff_required
def item_list(request):
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    category = request.GET.get('category', '').strip()
    sort = request.GET.get('sort', 'name').strip()
    items = Item.objects.filter(is_archived=False).order_by('item_name')
    categories = (
        Item.objects.filter(is_archived=False)
        .exclude(category='')
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    if search:
        items = items.filter(
            Q(item_code__icontains=search)
            | Q(item_name__icontains=search)
            | Q(category__icontains=search)
            | Q(description__icontains=search)
        )

    if status:
        items = items.filter(status=status)

    if category:
        items = items.filter(category=category)

    sort_options = {
        'name': 'item_name',
        'category': 'category',
        'status': 'status',
        'date_added': '-created_at',
    }
    sort = sort if sort in sort_options else 'name'
    items = items.order_by(sort_options[sort], 'item_name')

    items, item_total, querystring = paginate_queryset(request, items)

    return render(request, 'core/item_list.html', {
        'items': items,
        'item_total': item_total,
        'querystring': querystring,
        'search_query': search,
        'selected_status': status,
        'selected_category': category,
        'selected_sort': sort,
        'categories': categories,
    })


@staff_required
def item_qr_labels(request):
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    category = request.GET.get('category', '').strip()
    items = Item.objects.filter(is_archived=False).order_by('category', 'item_name')
    categories = (
        Item.objects.filter(is_archived=False)
        .exclude(category='')
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    if search:
        items = items.filter(
            Q(item_code__icontains=search)
            | Q(item_name__icontains=search)
            | Q(category__icontains=search)
        )
    if status:
        items = items.filter(status=status)
    if category:
        items = items.filter(category=category)

    label_items = []
    for item in items[:120]:
        public_url = request.build_absolute_uri(reverse('public_item_detail', args=[item.pk]))
        label_items.append({
            'item': item,
            'public_url': public_url,
            'qr_data_uri': build_qr_svg_data_uri(public_url),
        })

    return render(request, 'core/item_qr_labels.html', {
        'label_items': label_items,
        'label_total': len(label_items),
        'search_query': search,
        'selected_status': status,
        'selected_category': category,
        'categories': categories,
    })


@staff_or_admin_required
def item_archive_list(request):
    search = request.GET.get('search', '').strip()
    items = Item.objects.filter(is_archived=True).order_by('-archived_at', 'item_name')

    if search:
        items = items.filter(
            Q(item_code__icontains=search)
            | Q(item_name__icontains=search)
            | Q(category__icontains=search)
            | Q(description__icontains=search)
        )

    items, item_total, querystring = paginate_queryset(request, items)
    return render(request, 'core/item_archive_list.html', {
        'items': items,
        'item_total': item_total,
        'querystring': querystring,
        'search_query': search,
    })


@staff_required
def item_create(request):
    form = ItemForm(request.POST or None)
    if form.is_valid():
        item = form.save()
        maintenance_notes = form.cleaned_data.get('maintenance_notes', '').strip()
        if item.status == 'Maintenance' and maintenance_notes:
            MaintenanceRecord.objects.create(
                item=item,
                reported_by=request.user,
                previous_status='New',
                new_status=item.status,
                notes=maintenance_notes,
            )
        log_activity('Add Item', f'Item "{item.item_name}" was added.', request.user)
        messages.success(request, "Item added successfully.")
        return redirect('item_list')
    return render(request, 'core/item_form.html', {'form': form})


@staff_required
def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk, is_archived=False)
    previous_status = item.status
    form = ItemForm(request.POST or None, instance=item)
    if form.is_valid():
        item = form.save()
        maintenance_notes = form.cleaned_data.get('maintenance_notes', '').strip()
        if item.status == 'Maintenance' and maintenance_notes:
            MaintenanceRecord.objects.create(
                item=item,
                reported_by=request.user,
                previous_status=previous_status,
                new_status=item.status,
                notes=maintenance_notes,
            )
        log_activity('Edit Item', f'Item "{item.item_name}" was updated.', request.user)
        messages.success(request, "Item updated successfully.")
        return redirect('item_list')
    return render(request, 'core/item_form.html', {'form': form})


@staff_required
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk, is_archived=False)

    if item.status == 'Borrowed':
        messages.error(request, "Cannot archive an item that is currently borrowed.")
        return redirect('item_list')

    if request.method == 'POST':
        item_name = item.item_name
        item.is_archived = True
        item.archived_at = timezone.now()
        item.save(update_fields=['is_archived', 'archived_at'])
        log_activity('Archive Item', f'Item "{item_name}" was archived.', request.user)
        messages.success(request, "Item archived.")
        return redirect('item_list')

    return render(request, 'core/confirm_delete.html', {
        'object_name': item.item_name,
        'object_type': 'Item',
        'action_label': 'Archive',
        'cancel_url': '/items/',
    })


@staff_required
def item_restore(request, pk):
    if request.method != 'POST':
        messages.error(request, "Item restore requests must be submitted from the archive page.")
        return redirect('item_archive_list')

    item = get_object_or_404(Item, pk=pk, is_archived=True)
    item.is_archived = False
    item.archived_at = None
    if item.status == 'Borrowed':
        item.status = 'Available'
        item.save(update_fields=['is_archived', 'archived_at', 'status'])
    else:
        item.save(update_fields=['is_archived', 'archived_at'])
    log_activity('Restore Item', f'Item "{item.item_name}" was restored from archive.', request.user)
    messages.success(request, "Item restored successfully.")
    return redirect('item_archive_list')


@staff_required
def item_purge(request, pk):
    if request.method != 'POST':
        messages.error(request, "Item deletion requests must be submitted from the archive page.")
        return redirect('item_archive_list')

    item = get_object_or_404(Item, pk=pk, is_archived=True)

    item_name = item.item_name
    with transaction.atomic():
        deleted_transactions, _ = Transaction.objects.filter(item=item).delete()
        deleted_maintenance_records, _ = MaintenanceRecord.objects.filter(item=item).delete()
        item.delete()

    log_activity(
        'Delete Item Permanently',
        f'Archived item "{item_name}" was permanently deleted with '
        f'{deleted_transactions} related transaction(s) and {deleted_maintenance_records} maintenance record(s).',
        request.user,
    )
    messages.success(request, "Archived item and related records deleted permanently.")
    return redirect('item_archive_list')


@staff_required
def borrow_item(request):
    form = TransactionForm(request.POST or None)

    if form.is_valid():
        try:
            with transaction.atomic():
                borrower = Borrower.objects.select_for_update().get(
                    pk=form.cleaned_data['borrower'].pk,
                    is_archived=False,
                )
                item = Item.objects.select_for_update().get(
                    pk=form.cleaned_data['item'].pk,
                    is_archived=False,
                )

                if not borrower.active_status:
                    form.add_error('borrower', "Inactive borrowers cannot borrow items.")
                    raise ValueError("inactive borrower")

                if item.status != 'Available':
                    form.add_error('item', "This item is no longer available for borrowing.")
                    raise ValueError("unavailable item")

                settings_obj = get_system_settings()
                active_borrow_count = Transaction.objects.filter(
                    borrower=borrower,
                    status__in=['Borrowed', 'Overdue'],
                ).count()
                if settings_obj.borrow_limit and active_borrow_count >= settings_obj.borrow_limit:
                    form.add_error(
                        'borrower',
                        f'This borrower already reached the maximum of {settings_obj.borrow_limit} active borrow(s).',
                    )
                    raise ValueError("borrow limit reached")

                new_transaction = form.save(commit=False)
                new_transaction.borrower = borrower
                new_transaction.item = item
                new_transaction.status = 'Borrowed'
                new_transaction.borrow_time = timezone.now()
                new_transaction.return_time = None
                new_transaction.save()

                item.status = 'Borrowed'
                item.save(update_fields=['status'])
                transaction_obj = new_transaction

        except IntegrityError:
            form.add_error('item', "This item was just borrowed by another transaction. Please choose another available item.")
            transaction_obj = None
        except (Borrower.DoesNotExist, Item.DoesNotExist):
            form.add_error(None, "The borrower or item is no longer available.")
            transaction_obj = None
        except ValueError:
            transaction_obj = None
        else:
            due_time_text = (
                timezone.localtime(transaction_obj.due_time).strftime("%Y-%m-%d %H:%M")
                if transaction_obj.due_time
                else "No due time"
            )
            telegram_message = (
                "📦 <b>New Borrow Transaction</b>\n\n"
                f"<b>Borrower:</b> {transaction_obj.borrower.full_name}\n"
                f"<b>School ID:</b> {transaction_obj.borrower.school_id}\n"
                f"<b>Item:</b> {transaction_obj.item.item_name}\n"
                f"<b>Item Code:</b> {transaction_obj.item.item_code}\n"
                f"<b>Status:</b> Borrowed\n"
                f"<b>Borrow Time:</b> {timezone.localtime(transaction_obj.borrow_time).strftime('%Y-%m-%d %H:%M')}\n"
                f"<b>Due Time:</b> {due_time_text}\n"
                f"<b>Processed By:</b> {request.user.username}"
            )

            log_activity(
                'Borrow Item',
                f'Borrower "{transaction_obj.borrower.full_name}" borrowed "{transaction_obj.item.item_name}".'
                f' Due on {due_time_text}.',
                request.user,
            )

            telegram_result = send_preferred_telegram_message(
                request.user,
                "📦 <b>New Borrow Transaction</b>\n\n"
                f"<b>Borrower:</b> {transaction_obj.borrower.full_name}\n"
                f"<b>School ID:</b> {transaction_obj.borrower.school_id}\n"
                f"<b>Item:</b> {transaction_obj.item.item_name}\n"
                f"<b>Item Code:</b> {transaction_obj.item.item_code}\n"
                f"<b>Status:</b> Borrowed\n"
                f"<b>Borrow Time:</b> {timezone.localtime(transaction_obj.borrow_time).strftime('%Y-%m-%d %H:%M')}\n"
                f"<b>Due Time:</b> {due_time_text}\n"
                f"<b>Processed By:</b> {request.user.username}"
            )
            log_notification(
                channel='Telegram',
                event_type='Borrow Transaction Alert',
                message=telegram_message,
                status=telegram_result.get('status', 'failed').title(),
                recipient=telegram_result.get('recipient', ''),
                user=request.user,
                transaction_record=transaction_obj,
                error_message=telegram_result.get('error', ''),
            )

            email_result = send_borrow_receipt_email(transaction_obj, request.user)
            log_notification(
                channel='Email',
                event_type='Borrow Receipt Email',
                message=email_result.get('message', ''),
                status=email_result.get('status', 'failed').title(),
                recipient=email_result.get('recipient', ''),
                user=request.user,
                transaction_record=transaction_obj,
                error_message=email_result.get('error', ''),
            )

            messages.success(request, "Borrow processed successfully. Review or print the receipt below.")
            return redirect('transaction_receipt', pk=transaction_obj.pk)

    return render(request, 'core/borrow_form.html', {'form': form})

@staff_required
def return_list(request):
    refresh_overdue_transactions()
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    borrowed_transactions = Transaction.objects.filter(
        status__in=['Borrowed', 'Overdue'],
        borrower__is_archived=False,
        item__is_archived=False,
    ).select_related('borrower', 'item').order_by('due_time', '-borrow_time')

    if search:
        borrowed_transactions = borrowed_transactions.filter(
            Q(borrower__full_name__icontains=search)
            | Q(borrower__school_id__icontains=search)
            | Q(item__item_name__icontains=search)
            | Q(item__item_code__icontains=search)
        )

    if status in {'Borrowed', 'Overdue'}:
        borrowed_transactions = borrowed_transactions.filter(status=status)

    borrowed_transactions, borrowed_total, querystring = paginate_queryset(request, borrowed_transactions)
    return render(request, 'core/return_list.html', {
        'borrowed_transactions': borrowed_transactions,
        'borrowed_total': borrowed_total,
        'querystring': querystring,
        'search_query': search,
        'selected_status': status,
    })


@staff_required
def return_item(request, pk):
    transaction_record = get_object_or_404(
        Transaction.objects.select_related('borrower', 'item'),
        pk=pk,
        borrower__is_archived=False,
        item__is_archived=False,
    )
    form = ReturnTransactionForm(request.POST or None, instance=transaction_record)

    if transaction_record.status == 'Returned':
        messages.error(request, "This item has already been returned.")
        return redirect('return_list')

    if transaction_record.status not in ['Borrowed', 'Overdue']:
        messages.error(request, "Invalid return transaction.")
        return redirect('return_list')

    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                locked_transaction = Transaction.objects.select_for_update().select_related('borrower', 'item').get(pk=pk)

                if locked_transaction.status == 'Returned':
                    messages.error(request, "This item has already been returned.")
                    return redirect('return_list')

                if locked_transaction.status not in ['Borrowed', 'Overdue']:
                    messages.error(request, "Invalid return transaction.")
                    return redirect('return_list')

                locked_item = Item.objects.select_for_update().get(pk=locked_transaction.item_id)
                locked_transaction.returned_condition = form.cleaned_data['returned_condition']
                locked_transaction.notes = form.cleaned_data['notes']
                locked_transaction.status = 'Returned'
                locked_transaction.return_time = timezone.now()
                locked_transaction.save(update_fields=['returned_condition', 'notes', 'status', 'return_time'])

                locked_item.status = 'Available'
                locked_item.save(update_fields=['status'])

                if locked_transaction.returned_condition == 'Damaged':
                    locked_item.status = 'Maintenance'
                    locked_item.save(update_fields=['status'])
                    MaintenanceRecord.objects.create(
                        item=locked_item,
                        reported_by=request.user,
                        previous_status='Borrowed',
                        new_status='Maintenance',
                        notes=locked_transaction.notes or 'Returned in damaged condition.',
                    )
        except Transaction.DoesNotExist:
            messages.error(request, "This transaction no longer exists.")
            return redirect('return_list')

        log_activity(
            'Return Item',
            f'Borrower "{transaction_record.borrower.full_name}" returned "{transaction_record.item.item_name}".',
            request.user,
        )

        return_time_text = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
        telegram_message = (
            "✅ <b>Item Returned</b>\n\n"
            f"<b>Borrower:</b> {transaction_record.borrower.full_name}\n"
            f"<b>School ID:</b> {transaction_record.borrower.school_id}\n"
            f"<b>Item:</b> {transaction_record.item.item_name}\n"
            f"<b>Item Code:</b> {transaction_record.item.item_code}\n"
            f"<b>Status:</b> Returned\n"
            f"<b>Condition:</b> {form.cleaned_data['returned_condition']}\n"
            f"<b>Return Time:</b> {return_time_text}\n"
            f"<b>Processed By:</b> {request.user.username}"
        )

        telegram_result = send_preferred_telegram_message(
            request.user,
            "✅ <b>Item Returned</b>\n\n"
            f"<b>Borrower:</b> {transaction_record.borrower.full_name}\n"
            f"<b>School ID:</b> {transaction_record.borrower.school_id}\n"
            f"<b>Item:</b> {transaction_record.item.item_name}\n"
            f"<b>Item Code:</b> {transaction_record.item.item_code}\n"
            f"<b>Status:</b> Returned\n"
            f"<b>Condition:</b> {form.cleaned_data['returned_condition']}\n"
            f"<b>Return Time:</b> {return_time_text}\n"
            f"<b>Processed By:</b> {request.user.username}"
        )
        log_notification(
            channel='Telegram',
            event_type='Return Transaction Alert',
            message=telegram_message,
            status=telegram_result.get('status', 'failed').title(),
            recipient=telegram_result.get('recipient', ''),
            user=request.user,
            transaction_record=transaction_record,
            error_message=telegram_result.get('error', ''),
        )

        messages.success(request, "Return completed successfully. Review or print the receipt below.")
        return redirect('transaction_receipt', pk=pk)

    return render(request, 'core/return_form.html', {
        'form': form,
        'transaction': transaction_record,
    })


@staff_or_admin_required
def transaction_receipt(request, pk):
    transaction_record = get_object_or_404(
        Transaction.objects.select_related('borrower', 'item'),
        pk=pk,
        borrower__is_archived=False,
        item__is_archived=False,
    )
    return render(request, 'core/transaction_receipt.html', {
        'transaction': transaction_record,
    })


@staff_required
def transaction_list(request):
    refresh_overdue_transactions()
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    transactions = Transaction.objects.select_related('borrower', 'item').filter(
        borrower__is_archived=False,
        item__is_archived=False,
    ).order_by('-borrow_time')

    if search:
        transactions = transactions.filter(
            Q(borrower__full_name__icontains=search)
            | Q(borrower__school_id__icontains=search)
            | Q(item__item_name__icontains=search)
            | Q(item__item_code__icontains=search)
            | Q(notes__icontains=search)
        )

    if status:
        transactions = transactions.filter(status=status)

    transactions, transaction_total, querystring = paginate_queryset(request, transactions)

    return render(request, 'core/transaction_list.html', {
        'transactions': transactions,
        'transaction_total': transaction_total,
        'querystring': querystring,
        'search_query': search,
        'selected_status': status,
    })


@staff_or_admin_required
def report_list(request):
    transactions, summary, filters = build_report_queryset(request)
    report_type = request.GET.get('type', 'transactions').strip() or 'transactions'
    if report_type not in {'transactions', 'overdue', 'inventory'}:
        report_type = 'transactions'
    inventory_summary = build_inventory_summary()

    if report_type == 'overdue':
        transactions = transactions.filter(status='Overdue')
        summary = {
            **summary,
            'total_records': transactions.count(),
            'borrowed_count': transactions.filter(status='Borrowed').count(),
            'returned_count': transactions.filter(status='Returned').count(),
            'overdue_count': transactions.filter(status='Overdue').count(),
        }

    if request.GET.get('export') == 'csv':
        if report_type == 'inventory':
            return export_inventory_summary_csv(inventory_summary)
        return export_transactions_csv(transactions)
    if request.GET.get('export') == 'pdf':
        try:
            if report_type == 'inventory':
                return export_inventory_summary_pdf(inventory_summary)
            return export_transactions_pdf(transactions, summary)
        except RuntimeError as exc:
            messages.error(request, str(exc))
            return redirect('report_list')

    transactions, transaction_total, querystring = paginate_queryset(request, transactions)

    context = {
        'transactions': transactions,
        'transaction_total': transaction_total,
        'querystring': querystring,
        'export_querystring': get_export_querystring(request),
        'summary': summary,
        'report_type': report_type,
        'report_tabs': build_report_tabs(report_type),
        'inventory_summary': inventory_summary,
        **filters,
    }

    return render(request, 'core/report_list.html', context)


@admin_required
def activity_log_list(request):
    logs = ActivityLog.objects.select_related('user').all().order_by('-timestamp')
    users = User.objects.filter(activitylog__isnull=False).distinct().order_by('username')
    actions = ActivityLog.objects.values_list('action', flat=True).distinct().order_by('action')

    search = (request.GET.get('search') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    user_id = (request.GET.get('user') or '').strip()
    action = (request.GET.get('action') or '').strip()

    if search:
        logs = logs.filter(
            Q(description__icontains=search)
            | Q(action__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
        )

    if user_id:
        logs = logs.filter(user_id=user_id)

    if action:
        logs = logs.filter(action=action)

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from:
        start_dt = timezone.make_aware(datetime.combine(parsed_date_from, time.min))
        logs = logs.filter(timestamp__gte=start_dt)

    if parsed_date_to:
        end_dt = timezone.make_aware(datetime.combine(parsed_date_to, time.max))
        logs = logs.filter(timestamp__lte=end_dt)

    if request.GET.get('export') == 'csv':
        return export_activity_logs_csv(logs)

    logs, log_total, querystring = paginate_queryset(request, logs)

    return render(request, 'core/activity_log_list.html', {
        'logs': logs,
        'log_total': log_total,
        'querystring': querystring,
        'export_querystring': get_export_querystring(request),
        'users': users,
        'actions': actions,
        'selected_search': search,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'selected_user': user_id,
        'selected_action': action,
    })


@admin_required
def user_list(request):
    search = request.GET.get('search', '').strip()
    role = request.GET.get('role', '').strip()
    status = request.GET.get('status', '').strip()
    users = User.objects.select_related('profile').all().order_by('username')

    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )

    if role in {ADMIN_ROLE, STAFF_ROLE}:
        users = users.filter(profile__role=role)

    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)

    users, user_total, querystring = paginate_queryset(request, users)
    return render(request, 'core/user_list.html', {
        'users': users,
        'user_total': user_total,
        'querystring': querystring,
        'search_query': search,
        'selected_role': role,
        'selected_status': status,
        'active_user_total': User.objects.filter(is_active=True).count(),
        'inactive_user_total': User.objects.filter(is_active=False).count(),
        'admin_user_total': UserProfile.objects.filter(role=ADMIN_ROLE, user__is_active=True).count(),
        'staff_user_total': UserProfile.objects.filter(role=STAFF_ROLE, user__is_active=True).count(),
    })


@admin_required
def user_edit(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    form = UserUpdateForm(request.POST or None, instance=user_obj)

    if form.is_valid():
        active_admin_count = UserProfile.objects.filter(role=ADMIN_ROLE, user__is_active=True).count()
        current_role = user_obj.profile.role
        next_role = form.cleaned_data.get('role')
        next_active = form.cleaned_data.get('is_active')
        if user_obj == request.user:
            if next_role != ADMIN_ROLE:
                form.add_error('role', "You cannot remove your own administrator access.")
            if not next_active:
                form.add_error('is_active', "You cannot deactivate your own account.")
        if current_role == ADMIN_ROLE and user_obj.is_active and active_admin_count <= 1:
            if next_role != ADMIN_ROLE:
                form.add_error('role', "At least one active administrator account is required.")
            if not next_active:
                form.add_error('is_active', "At least one active administrator account is required.")
        if form.errors:
            return render(request, 'core/user_form.html', {
                'form': form,
                'page_title': 'Edit User Account',
                'submit_label': 'Save User',
                'edited_user': user_obj,
            })

        updated_user = form.save()
        log_activity('Edit User', f'User "{updated_user.username}" account details were updated.', request.user)
        messages.success(request, "User account updated successfully.")
        return redirect('user_list')

    return render(request, 'core/user_form.html', {
        'form': form,
        'page_title': 'Edit User Account',
        'submit_label': 'Save User',
        'edited_user': user_obj,
    })


@admin_required
def system_settings_view(request):
    settings_obj = get_system_settings()
    form = SystemSettingsForm(request.POST or None, instance=settings_obj)

    if form.is_valid():
        form.save()
        log_activity('Update System Settings', 'System settings were updated.', request.user)
        messages.success(request, "System settings updated successfully.")
        return redirect('system_settings')

    return render(request, 'core/system_settings_form.html', {
        'form': form,
        'page_title': 'System Settings',
        'user_total': User.objects.count(),
        'active_user_total': User.objects.filter(is_active=True).count(),
        'inactive_user_total': User.objects.filter(is_active=False).count(),
        'notification_total': NotificationLog.objects.count(),
        'failed_notification_total': NotificationLog.objects.filter(status='Failed').count(),
        'skipped_notification_total': NotificationLog.objects.filter(status='Skipped').count(),
        'data_totals': {
            'borrowers': Borrower.objects.filter(is_archived=False).count(),
            'items': Item.objects.filter(is_archived=False).count(),
            'transactions': Transaction.objects.count(),
            'activity_logs': ActivityLog.objects.count(),
        },
        'session_timeout_minutes': max(int(settings.SESSION_IDLE_TIMEOUT / 60), 1),
        'login_attempt_limit': settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        'session_cookie_samesite': settings.SESSION_COOKIE_SAMESITE,
        'database_readiness': get_database_readiness(),
        'notification_readiness': get_notification_readiness(),
        'recent_backups': get_recent_backups(),
    })


@admin_required
def create_system_backup(request):
    if request.method != 'POST':
        messages.error(request, "Backup creation must be submitted from the settings page.")
        return redirect('system_settings')

    output = StringIO()
    try:
        call_command('backup_system_data', output_dir=str(settings.BACKUP_DIR), stdout=output)
    except Exception as exc:
        messages.error(request, f"Backup failed: {exc}")
        log_activity('Create Backup Failed', 'A system backup attempt failed.', request.user)
        return redirect('system_settings')

    latest_backup = get_recent_backups(limit=1)
    backup_name = latest_backup[0]['name'] if latest_backup else 'JSON backup'
    log_activity('Create Backup', f'Backup "{backup_name}" was created.', request.user)
    messages.success(request, f'Backup created successfully: {backup_name}')
    return redirect('system_settings')


@admin_required
def notification_list(request):
    search = request.GET.get('search', '').strip()
    channel = request.GET.get('channel', '').strip()
    status = request.GET.get('status', '').strip()
    event_type = request.GET.get('event_type', '').strip()

    logs = NotificationLog.objects.select_related('triggered_by', 'transaction')
    event_types = NotificationLog.objects.exclude(event_type='').values_list('event_type', flat=True).distinct().order_by('event_type')

    if search:
        logs = logs.filter(
            Q(recipient__icontains=search)
            | Q(message__icontains=search)
            | Q(error_message__icontains=search)
            | Q(transaction__borrower__full_name__icontains=search)
            | Q(transaction__item__item_name__icontains=search)
        )
    if channel:
        logs = logs.filter(channel=channel)
    if status:
        logs = logs.filter(status=status)
    if event_type:
        logs = logs.filter(event_type=event_type)

    logs, log_total, querystring = paginate_queryset(request, logs, per_page=15)

    return render(request, 'core/notification_list.html', {
        'logs': logs,
        'log_total': log_total,
        'querystring': querystring,
        'search_query': search,
        'selected_channel': channel,
        'selected_status': status,
        'selected_event_type': event_type,
        'event_types': event_types,
        'notification_readiness': get_notification_readiness(),
        'notification_summary': {
            'sent': NotificationLog.objects.filter(status='Sent').count(),
            'failed': NotificationLog.objects.filter(status='Failed').count(),
            'skipped': NotificationLog.objects.filter(status='Skipped').count(),
        },
    })


@admin_required
def run_notification_check(request):
    if request.method != 'POST':
        messages.error(request, "Notification checks must be started from the notification center.")
        return redirect('notification_list')

    dry_run = request.POST.get('dry_run') == 'on'
    output = StringIO()
    try:
        command_args = ['--dry-run'] if dry_run else []
        call_command('send_due_notifications', *command_args, stdout=output)
    except Exception as exc:
        log_activity('Notification Check Failed', 'A due notification check failed.', request.user)
        messages.error(request, f"Notification check failed: {exc}")
        return redirect('notification_list')

    mode = 'Dry run' if dry_run else 'Notification pass'
    log_activity('Run Notification Check', f'{mode} completed from the notification center.', request.user)
    messages.success(request, f'{mode} completed successfully.')
    return redirect('notification_list')


@staff_or_admin_required
def profile_view(request):
    form = SelfProfileForm(request.POST or None, instance=request.user)

    if form.is_valid():
        updated_user = form.save()
        log_activity('Update Profile', f'User "{updated_user.username}" updated their own profile.', request.user)
        messages.success(request, "Your profile was updated successfully.")
        return redirect('profile')

    return render(request, 'core/profile_form.html', {
        'form': form,
        'page_title': 'My Profile',
    })


@admin_required
def user_toggle_status(request, pk):
    if request.method != 'POST':
        messages.error(request, "Account status changes must be submitted from the user management page.")
        return redirect('user_list')

    user_obj = get_object_or_404(User, pk=pk)

    if user_obj == request.user and user_obj.is_active:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('user_list')

    if user_obj.is_active and user_obj.profile.role == ADMIN_ROLE:
        active_admin_count = UserProfile.objects.filter(role=ADMIN_ROLE, user__is_active=True).count()
        if active_admin_count <= 1:
            messages.error(request, "At least one active administrator account is required.")
            return redirect('user_list')

    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=['is_active'])

    status_label = 'activated' if user_obj.is_active else 'deactivated'
    log_activity('Toggle User Status', f'User "{user_obj.username}" was {status_label}.', request.user)
    messages.success(request, f'User {status_label} successfully.')
    return redirect('user_list')


@staff_required
def maintenance_list(request):
    search = request.GET.get('search', '').strip()
    maintenance_records = MaintenanceRecord.objects.select_related('item', 'reported_by').filter(
        item__is_archived=False,
    )

    if search:
        maintenance_records = maintenance_records.filter(
            Q(item__item_name__icontains=search)
            | Q(item__item_code__icontains=search)
            | Q(notes__icontains=search)
            | Q(reported_by__username__icontains=search)
        )

    maintenance_records, maintenance_total, querystring = paginate_queryset(request, maintenance_records)

    return render(request, 'core/maintenance_list.html', {
        'maintenance_records': maintenance_records,
        'maintenance_total': maintenance_total,
        'querystring': querystring,
        'search_query': search,
    })


def logout_view(request):
    if request.method != 'POST':
        messages.error(request, "Please use the sign out button to log out securely.")
        return redirect('dashboard' if request.user.is_authenticated else '/login/')

    if request.user.is_authenticated:
        log_activity('Logout', f'User "{request.user.username}" signed out.', request.user)
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect('/login/')


@admin_required
def user_reset_password(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(user_obj, request.POST or None)

    if request.method == 'POST' and form.is_valid():
        form.save()
        log_activity('Reset User Password', f'Password for "{user_obj.username}" was reset by an administrator.', request.user)
        messages.success(request, "User password reset successfully.")
        return redirect('user_list')

    return render(request, 'core/user_password_reset_form.html', {
        'form': form,
        'edited_user': user_obj,
    })


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        database_ok = True
    except Exception:
        database_ok = False

    status_code = 200 if database_ok else 503
    return JsonResponse({
        'status': 'ok' if database_ok else 'degraded',
        'database': 'ok' if database_ok else 'unavailable',
        'debug': settings.DEBUG,
        'timestamp': timezone.now().isoformat(),
    }, status=status_code)
