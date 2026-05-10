from datetime import datetime, time, timedelta
import shutil
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth.models import User
from django.conf import settings
from django.db import IntegrityError, transaction as db_transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ActivityLog, Borrower, Item, MaintenanceRecord, NotificationLog, SystemSettings, Transaction
from myproject.settings import build_allowed_hosts, supabase_config_from_url


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='')
class SystemFeatureTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='admin1',
            password='StrongPass123!',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
        )
        self.admin_user.profile.role = 'Admin'
        self.admin_user.profile.save()
        self.admin_user.is_staff = True
        self.admin_user.save()

        self.staff_user = User.objects.create_user(
            username='staff1',
            password='StrongPass123!',
            first_name='Staff',
            last_name='User',
            email='staff@example.com',
        )
        self.staff_user.profile.role = 'Staff'
        self.staff_user.profile.save()

        self.borrower = Borrower.objects.create(
            full_name='Jane Borrower',
            school_id='2026-0001',
            program='BSIT',
            section='A',
            active_status=True,
        )
        self.item = Item.objects.create(
            item_code='EQ-001',
            item_name='Laptop',
            category='Electronics',
            status='Available',
        )

    def test_first_account_registration_assigns_admin_role(self):
        User.objects.all().delete()

        response = self.client.post(reverse('register'), {
            'username': 'firstadmin',
            'first_name': 'First',
            'last_name': 'Admin',
            'email': 'first@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })

        self.assertRedirects(response, reverse('login'))
        first_user = User.objects.get(username='firstadmin')
        self.assertEqual(first_user.profile.role, 'Admin')

    def test_login_page_shows_admin_setup_link_when_no_admin_exists(self):
        self.admin_user.profile.role = 'Staff'
        self.admin_user.profile.save()
        self.admin_user.is_staff = True
        self.admin_user.save()

        response = self.client.get(reverse('login'))

        self.assertContains(response, 'No admin account exists yet')
        self.assertContains(response, 'Create the first administrator account')

    def test_login_page_makes_admin_access_visible(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'Campus Equipment Hub')
        self.assertContains(response, 'Who are you signing in as?')
        self.assertContains(response, 'Choose your role to continue')
        self.assertContains(response, 'Staff')
        self.assertContains(response, 'Borrow &amp; return')
        self.assertContains(response, 'Admin')
        self.assertContains(response, 'Full system access')
        self.assertContains(response, 'id="role-step"')
        self.assertContains(response, 'id="login-step" hidden')
        self.assertContains(response, 'id="continue-login" disabled')
        self.assertContains(response, 'Back to role selection')
        self.assertContains(response, 'Enter admin or staff username')
        self.assertContains(response, 'Sign up as staff')
        self.assertNotContains(response, 'Staff and Admin Login')
        self.assertNotContains(response, 'Sign in to manage student borrowing')
        self.assertNotContains(response, 'Full dashboard, settings, users, reports, and logs.')
        self.assertNotContains(response, 'Borrowers, items, borrowing, returns, and transactions.')
        self.assertContains(response, 'View public equipment availability')
        self.assertContains(response, 'Remember me')
        self.assertContains(response, 'data-password-toggle')
        self.assertContains(response, 'data-loading-label="Signing in..."')

    def test_login_redirects_to_safe_next_url(self):
        response = self.client.post(f"{reverse('login')}?next=/items/", {
            'login_role': 'Staff',
            'username': 'staff1',
            'password': 'StrongPass123!',
            'remember_me': 'on',
            'next': '/items/',
        })

        self.assertRedirects(response, '/items/', fetch_redirect_response=False)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_login_ignores_unsafe_next_url(self):
        response = self.client.post(f"{reverse('login')}?next=https://example.com/phish", {
            'login_role': 'Staff',
            'username': 'staff1',
            'password': 'StrongPass123!',
            'next': 'https://example.com/phish',
        })

        self.assertRedirects(response, reverse('dashboard'))

    def test_public_item_availability_is_accessible_without_login_and_hides_private_fields(self):
        archived_item = Item.objects.create(
            item_code='EQ-ARCHIVED',
            item_name='Archived Camera',
            category='AV',
            status='Available',
            is_archived=True,
        )

        response = self.client.get(reverse('public_item_availability'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check Available Campus Equipment')
        self.assertContains(response, 'Laptop')
        self.assertContains(response, 'Electronics')
        self.assertNotContains(response, self.item.item_code)
        self.assertNotContains(response, archived_item.item_name)
        self.assertNotContains(response, 'Students')
        self.assertNotContains(response, 'Activity Logs')

    def test_public_item_availability_filters_by_status_and_search(self):
        borrowed_item = Item.objects.create(
            item_code='EQ-002',
            item_name='Projector',
            category='AV',
            description='Presentation equipment',
            status='Borrowed',
        )

        response = self.client.get(reverse('public_item_availability'), {
            'status': 'Borrowed',
            'search': 'Projector',
        })

        self.assertContains(response, borrowed_item.item_name)
        self.assertContains(response, 'Borrowed')
        self.assertNotContains(response, 'Laptop')

    def test_public_item_detail_is_qr_ready(self):
        response = self.client.get(reverse('public_item_detail', args=[self.item.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.item_name)
        self.assertContains(response, 'QR-ready')

    def test_staff_can_print_item_qr_labels(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('item_qr_labels'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Print QR Labels')
        self.assertContains(response, 'data:image/svg+xml;base64')
        self.assertContains(response, self.item.item_name)

    def test_public_borrower_lookup_requires_registered_email(self):
        self.borrower.email = 'jane@example.com'
        self.borrower.save()
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )

        response = self.client.get(reverse('public_borrower_lookup'), {
            'school_id': self.borrower.school_id,
            'email': 'jane@example.com',
        })

        self.assertContains(response, self.borrower.full_name)
        self.assertContains(response, self.item.item_name)

        blocked = self.client.get(reverse('public_borrower_lookup'), {
            'school_id': self.borrower.school_id,
            'email': 'wrong@example.com',
        })
        self.assertNotContains(blocked, self.borrower.full_name)
        self.assertContains(blocked, 'No matching active borrower record was found')

    def test_base_template_includes_phase_one_accessibility_baseline(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'viewport-fit=cover')
        self.assertContains(response, 'Skip to content')
        self.assertContains(response, 'id="main-content"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, 'id="confirm-modal"')
        self.assertContains(response, 'aria-label="Breadcrumb"')
        self.assertContains(response, 'Primary mobile navigation')
        self.assertContains(response, "localStorage.setItem('sidebar-open'")

    def test_dashboard_shows_attention_queue(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'Attention queue')
        self.assertContains(response, 'Due Today')
        self.assertContains(response, 'Overdue Queue')
        self.assertContains(response, 'Maintenance')

    def test_admin_dashboard_shows_readiness_shortcuts(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'Admin Readiness')
        self.assertContains(response, 'Failed Notifications')
        self.assertContains(response, 'Latest Backup')
        self.assertContains(response, 'Maintenance Items')

    def test_staff_signup_creates_staff_account(self):
        response = self.client.post(reverse('staff_signup'), {
            'username': 'staffsignup',
            'first_name': 'New',
            'last_name': 'Staff',
            'email': 'staffsignup@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })

        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(username='staffsignup')
        self.assertEqual(user.profile.role, 'Staff')
        self.assertFalse(user.is_staff)

    def test_staff_signup_redirects_to_admin_setup_when_no_admin_exists(self):
        User.objects.all().delete()

        response = self.client.get(reverse('staff_signup'))

        self.assertRedirects(response, reverse('register'))

    def test_staff_login_requires_staff_choice(self):
        response = self.client.post(reverse('login'), {
            'login_role': 'Staff',
            'username': 'staff1',
            'password': 'StrongPass123!',
        })

        self.assertRedirects(response, reverse('dashboard'))

    def test_admin_login_requires_admin_choice(self):
        response = self.client.post(reverse('login'), {
            'login_role': 'Admin',
            'username': 'admin1',
            'password': 'StrongPass123!',
        })

        self.assertRedirects(response, reverse('dashboard'))

    def test_login_rejects_wrong_role_choice(self):
        response = self.client.post(reverse('login'), {
            'login_role': 'Admin',
            'username': 'staff1',
            'password': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This account is registered as Staff. Please choose Staff Access.')

    def test_profile_updates_notification_preferences(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.post(reverse('profile'), {
            'username': 'staff1',
            'first_name': 'Staff',
            'last_name': 'User',
            'email': 'staff@example.com',
            'notify_by_telegram': 'on',
        })

        self.assertRedirects(response, reverse('profile'))
        self.staff_user.profile.refresh_from_db()
        self.assertFalse(self.staff_user.profile.notify_by_email)
        self.assertTrue(self.staff_user.profile.notify_by_telegram)

    def test_admin_can_update_user_notification_preferences(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('user_edit', args=[self.staff_user.pk]), {
            'username': 'staff1',
            'first_name': 'Staff',
            'last_name': 'User',
            'email': 'staff@example.com',
            'role': 'Staff',
            'is_active': 'on',
            'notify_by_email': 'on',
        })

        self.assertRedirects(response, reverse('user_list'))
        self.staff_user.profile.refresh_from_db()
        self.assertTrue(self.staff_user.profile.notify_by_email)
        self.assertFalse(self.staff_user.profile.notify_by_telegram)

    def test_user_list_filters_and_shows_phase_seven_summary(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('user_list'), {
            'role': 'Staff',
            'status': 'active',
            'search': 'staff',
        })

        self.assertContains(response, 'Active Users')
        self.assertContains(response, 'Active Admins')
        self.assertContains(response, 'Search Users')
        self.assertContains(response, 'Staff')
        self.assertContains(response, 'staff1')
        self.assertNotContains(response, 'admin1</td>')

    def test_admin_cannot_remove_own_admin_access_from_user_edit(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('user_edit', args=[self.admin_user.pk]), {
            'username': 'admin1',
            'first_name': 'Admin',
            'last_name': 'User',
            'email': 'admin@example.com',
            'role': 'Staff',
            'is_active': 'on',
            'notify_by_email': 'on',
            'notify_by_telegram': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You cannot remove your own administrator access.')
        self.admin_user.profile.refresh_from_db()
        self.assertEqual(self.admin_user.profile.role, 'Admin')

    def test_last_active_admin_cannot_be_deactivated_by_toggle(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('user_toggle_status', args=[self.admin_user.pk]))

        self.assertRedirects(response, reverse('user_list'))
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)

    def test_user_password_reset_page_shows_account_context(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('user_reset_password', args=[self.staff_user.pk]))

        self.assertContains(response, 'Strong password required')
        self.assertContains(response, 'staff1')
        self.assertContains(response, 'Back to Users')

    def test_staff_cannot_access_admin_only_user_management(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('user_list'))

        self.assertRedirects(response, reverse('dashboard'))

    def test_admin_can_access_operational_workflows(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('borrower_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Student')
        self.assertContains(response, 'Archive')

    def test_overdue_transactions_are_updated_on_dashboard(self):
        transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            borrow_time=timezone.now() - timedelta(days=2),
            due_time=timezone.now() - timedelta(days=1),
            status='Borrowed',
        )
        self.item.status = 'Borrowed'
        self.item.save()

        self.client.login(username='staff1', password='StrongPass123!')
        self.client.get(reverse('dashboard'))
        transaction.refresh_from_db()

        self.assertEqual(transaction.status, 'Overdue')

    def test_report_csv_export_returns_file(self):
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('report_list'), {'export': 'csv'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('transaction-report.csv', response['Content-Disposition'])

    def test_report_export_buttons_show_loading_state(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('report_list'))

        self.assertContains(response, 'data-loading-label="Preparing CSV"')
        self.assertContains(response, 'data-loading-label="Preparing PDF"')

    def test_report_page_has_tabs_inventory_summary_and_overdue_days(self):
        self.item.status = 'Borrowed'
        self.item.save()
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() - timedelta(days=2),
            status='Borrowed',
            borrowed_condition='Good',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('report_list'), {'type': 'inventory'})

        self.assertContains(response, 'Transactions')
        self.assertContains(response, 'Overdue')
        self.assertContains(response, 'Inventory Summary')
        self.assertContains(response, 'Days Overdue')
        self.assertContains(response, '+2')

    def test_inventory_summary_csv_export_returns_category_counts(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('report_list'), {
            'type': 'inventory',
            'export': 'csv',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('inventory-summary-report.csv', response['Content-Disposition'])
        self.assertIn('Electronics', response.content.decode())

    def test_activity_logs_capture_authenticated_user(self):
        self.client.login(username='staff1', password='StrongPass123!')

        self.client.post(reverse('borrower_create'), {
            'full_name': 'John Example',
            'school_id': '2026-0002',
            'program': 'BSCS',
            'section': 'B',
            'active_status': True,
        })

        log = ActivityLog.objects.latest('timestamp')
        self.assertEqual(log.user, self.staff_user)

    def test_activity_log_action_filter_and_csv_export(self):
        ActivityLog.objects.create(
            user=self.admin_user,
            action='Export Report',
            description='Admin exported a report.',
        )
        ActivityLog.objects.create(
            user=self.staff_user,
            action='Create Borrower',
            description='Staff created a borrower.',
        )
        self.client.login(username='admin1', password='StrongPass123!')

        page = self.client.get(reverse('activity_log_list'), {'action': 'Export Report'})
        self.assertContains(page, 'Immutable Audit Trail')
        self.assertContains(page, 'Export Report')
        self.assertNotContains(page, 'Staff created a borrower.')

        export = self.client.get(reverse('activity_log_list'), {
            'action': 'Export Report',
            'export': 'csv',
        })
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export['Content-Type'], 'text/csv')
        self.assertIn('activity-log-export.csv', export['Content-Disposition'])
        self.assertIn('Admin exported a report.', export.content.decode())

    def test_inactive_borrower_cannot_borrow_item(self):
        self.borrower.active_status = False
        self.borrower.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': self.item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Testing inactive borrower',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inactive borrowers cannot borrow items.')

    def test_damaged_return_creates_maintenance_record(self):
        transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )
        self.item.status = 'Borrowed'
        self.item.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('return_item', args=[transaction.pk]), {
            'returned_condition': 'Damaged',
            'notes': 'Screen cracked on return',
        })

        self.assertRedirects(response, reverse('transaction_receipt', args=[transaction.pk]))
        self.item.refresh_from_db()
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, 'Returned')
        self.assertEqual(self.item.status, 'Maintenance')
        self.assertTrue(MaintenanceRecord.objects.filter(item=self.item, notes__icontains='cracked').exists())

    def test_damaged_return_requires_notes(self):
        transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )
        self.item.status = 'Borrowed'
        self.item.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('return_item', args=[transaction.pk]), {
            'returned_condition': 'Damaged',
            'notes': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Return notes are required when the item is damaged.')

    def test_return_list_search_and_overdue_filter(self):
        overdue_item = Item.objects.create(
            item_code='EQ-OD',
            item_name='Overdue Projector',
            category='AV',
            status='Borrowed',
        )
        Transaction.objects.create(
            borrower=self.borrower,
            item=overdue_item,
            due_time=timezone.now() - timedelta(days=1),
            status='Overdue',
            borrowed_condition='Good',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('return_list'), {
            'search': 'Projector',
            'status': 'Overdue',
        })

        self.assertContains(response, 'Quick Return Lookup')
        self.assertContains(response, 'Overdue Projector')
        self.assertContains(response, '+1 day overdue')
        self.assertNotContains(response, 'Laptop')

    def test_borrower_search_filters_results(self):
        Borrower.objects.create(
            full_name='Mark Sample',
            school_id='2026-0003',
            program='BSBA',
            section='C',
            active_status=True,
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('borrower_list'), {'search': 'Jane'})

        self.assertContains(response, 'Jane Borrower')
        self.assertNotContains(response, 'Mark Sample')

    def test_borrower_list_filters_overdue_status(self):
        Borrower.objects.create(
            full_name='Mark Sample',
            school_id='2026-0003',
            program='BSBA',
            section='C',
            active_status=True,
        )
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() - timedelta(days=1),
            status='Overdue',
            borrowed_condition='Good',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('borrower_list'), {'status': 'overdue'})

        self.assertContains(response, 'Has Overdue')
        self.assertContains(response, 'Jane Borrower')
        self.assertNotContains(response, 'Mark Sample')

    def test_borrower_delete_archives_record(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.post(reverse('borrower_delete', args=[self.borrower.pk]))

        self.assertRedirects(response, reverse('borrower_list'))
        self.borrower.refresh_from_db()
        self.assertTrue(self.borrower.is_archived)
        self.assertFalse(self.borrower.active_status)

    def test_logout_requires_post(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, reverse('dashboard'))

    def test_admin_can_reset_user_password(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('user_reset_password', args=[self.staff_user.pk]), {
            'new_password1': 'AnotherStrongPass123!',
            'new_password2': 'AnotherStrongPass123!',
        })

        self.assertRedirects(response, reverse('user_list'))
        self.staff_user.refresh_from_db()
        self.assertTrue(self.staff_user.check_password('AnotherStrongPass123!'))

    def test_archived_item_without_history_can_be_deleted_permanently(self):
        archived_item = Item.objects.create(
            item_code='EQ-099',
            item_name='Old Mouse',
            category='Electronics',
            status='Available',
            is_archived=True,
        )
        self.client.login(username='staff1', password='StrongPass123!')

        page = self.client.get(reverse('item_archive_list'))
        self.assertContains(page, 'Restore')
        self.assertContains(page, 'Delete')
        self.assertContains(page, 'data-confirm="Permanently delete Old Mouse')

        response = self.client.post(reverse('item_purge', args=[archived_item.pk]))

        self.assertRedirects(response, reverse('item_archive_list'))
        self.assertFalse(Item.objects.filter(pk=archived_item.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='Delete Item Permanently').exists())

    def test_item_list_filters_by_category_and_sorts(self):
        Item.objects.create(
            item_code='EQ-002',
            item_name='Projector',
            category='AV',
            status='Available',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('item_list'), {
            'category': 'AV',
            'sort': 'category',
        })

        self.assertContains(response, 'Category')
        self.assertContains(response, 'Projector')
        self.assertNotContains(response, 'Laptop')

    def test_item_form_uses_configured_category_suggestions(self):
        settings_obj = SystemSettings.load()
        settings_obj.item_categories = 'AV, Lab, Sports'
        settings_obj.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('item_create'))

        self.assertContains(response, 'id="category-options"')
        self.assertContains(response, '<option value="AV"></option>', html=True)
        self.assertContains(response, 'Suggested categories: AV, Lab, Sports')
        self.assertContains(response, 'data-loading-label="Saving item..."')

    def test_archived_item_with_history_can_be_deleted_permanently(self):
        archived_item = Item.objects.create(
            item_code='EQ-100',
            item_name='Old Projector',
            category='AV',
            status='Maintenance',
            is_archived=True,
        )
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=archived_item,
            due_time=timezone.now() + timedelta(days=1),
            status='Returned',
            borrowed_condition='Good',
        )
        maintenance_record = MaintenanceRecord.objects.create(
            item=archived_item,
            reported_by=self.staff_user,
            previous_status='Available',
            new_status='Maintenance',
            notes='Old lamp issue',
        )
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.post(reverse('item_purge', args=[archived_item.pk]))

        self.assertRedirects(response, reverse('item_archive_list'))
        self.assertFalse(Item.objects.filter(pk=archived_item.pk).exists())
        self.assertFalse(Transaction.objects.filter(pk=transaction_record.pk).exists())
        self.assertFalse(MaintenanceRecord.objects.filter(pk=maintenance_record.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='Delete Item Permanently').exists())

    def test_health_check_returns_ok(self):
        response = self.client.get(reverse('health_check'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_backup_command_writes_json_backup(self):
        output_dir = settings.BASE_DIR / 'test-backups'
        if output_dir.exists():
            shutil.rmtree(output_dir)

        call_command('backup_system_data', output_dir=str(output_dir))
        created_files = list(output_dir.iterdir())
        shutil.rmtree(output_dir)

        self.assertTrue(any(
            path.name.startswith('backup-') and path.suffix == '.json' and '.manifest.' not in path.name
            for path in created_files
        ))
        self.assertTrue(any(path.name.endswith('.manifest.json') for path in created_files))

    def test_archived_borrower_can_be_restored(self):
        self.borrower.is_archived = True
        self.borrower.active_status = False
        self.borrower.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrower_restore', args=[self.borrower.pk]))

        self.assertRedirects(response, reverse('borrower_archive_list'))
        self.borrower.refresh_from_db()
        self.assertFalse(self.borrower.is_archived)
        self.assertTrue(self.borrower.active_status)

    def test_archived_borrower_without_history_can_be_deleted_permanently(self):
        self.borrower.is_archived = True
        self.borrower.active_status = False
        self.borrower.save()

        self.client.login(username='staff1', password='StrongPass123!')
        page = self.client.get(reverse('borrower_archive_list'))
        self.assertContains(page, 'Restore')
        self.assertContains(page, 'Delete')

        response = self.client.post(reverse('borrower_purge', args=[self.borrower.pk]))

        self.assertRedirects(response, reverse('borrower_archive_list'))
        self.assertFalse(Borrower.objects.filter(pk=self.borrower.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='Delete Borrower Permanently').exists())

    def test_archived_borrower_with_history_can_be_deleted_permanently(self):
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Returned',
            borrowed_condition='Good',
        )
        self.borrower.is_archived = True
        self.borrower.active_status = False
        self.borrower.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrower_purge', args=[self.borrower.pk]))

        self.assertRedirects(response, reverse('borrower_archive_list'))
        self.assertFalse(Borrower.objects.filter(pk=self.borrower.pk).exists())
        self.assertFalse(Transaction.objects.filter(pk=transaction_record.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='Delete Borrower Permanently').exists())

    def test_borrower_detail_page_shows_history(self):
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('borrower_detail', args=[self.borrower.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jane Borrower')
        self.assertContains(response, 'Laptop')
        self.assertContains(response, 'Print History')

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_custom_404_page_is_available(self):
        response = self.client.get('/missing-page/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page not found', status_code=404)
        self.assertContains(response, 'Back to Dashboard', status_code=404)

    @patch('core.views.send_telegram_message')
    def test_borrow_creates_notification_log_entry(self, mock_send_telegram_message):
        mock_send_telegram_message.return_value = {
            'status': 'sent',
            'recipient': 'admin-chat',
            'error': '',
        }

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': self.item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Testing notification logging',
        })

        transaction_record = Transaction.objects.get(item=self.item, borrower=self.borrower)
        self.assertRedirects(response, reverse('transaction_receipt', args=[transaction_record.pk]))
        self.assertTrue(NotificationLog.objects.filter(
            channel='Telegram',
            event_type='Borrow Transaction Alert',
            status='Sent',
        ).exists())

    @patch('core.views.send_telegram_message')
    def test_borrow_skips_telegram_when_user_disabled_preference(self, mock_send_telegram_message):
        self.staff_user.profile.notify_by_telegram = False
        self.staff_user.profile.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': self.item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Telegram preference disabled',
        })

        transaction_record = Transaction.objects.get(item=self.item, borrower=self.borrower)
        self.assertRedirects(response, reverse('transaction_receipt', args=[transaction_record.pk]))
        mock_send_telegram_message.assert_not_called()
        self.assertTrue(NotificationLog.objects.filter(
            channel='Telegram',
            event_type='Borrow Transaction Alert',
            status='Skipped',
            error_message='Telegram notifications are disabled for this user.',
        ).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    @patch('core.views.send_telegram_message')
    def test_borrow_sends_email_receipt_when_borrower_has_email(self, mock_send_telegram_message):
        mock_send_telegram_message.return_value = {
            'status': 'skipped',
            'recipient': '',
            'error': '',
        }
        self.borrower.email = 'jane@example.com'
        self.borrower.save()

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': self.item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Testing email receipt',
        })

        transaction_record = Transaction.objects.get(item=self.item, borrower=self.borrower)
        self.assertRedirects(response, reverse('transaction_receipt', args=[transaction_record.pk]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('borrow receipt', mail.outbox[0].subject.lower())
        self.assertIn('Laptop', mail.outbox[0].body)
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Borrow Receipt Email',
            status='Sent',
            recipient='jane@example.com',
        ).exists())

    @patch('core.views.send_telegram_message')
    def test_borrow_logs_skipped_email_receipt_without_borrower_email(self, mock_send_telegram_message):
        mock_send_telegram_message.return_value = {
            'status': 'skipped',
            'recipient': '',
            'error': '',
        }

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': self.item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Testing skipped email receipt',
        })

        transaction_record = Transaction.objects.get(item=self.item, borrower=self.borrower)
        self.assertRedirects(response, reverse('transaction_receipt', args=[transaction_record.pk]))
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Borrow Receipt Email',
            status='Skipped',
            error_message='Borrower email is not set.',
        ).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    def test_due_notification_command_sends_due_soon_and_due_today_reminders(self):
        self.borrower.email = 'jane@example.com'
        self.borrower.save()
        settings_obj = SystemSettings.load()
        settings_obj.reminder_days_before_due = 1
        settings_obj.save()
        due_today_item = Item.objects.create(
            item_code='EQ-REM-1',
            item_name='Tripod',
            category='AV',
            status='Borrowed',
        )
        due_soon_transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )
        due_today_transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=due_today_item,
            due_time=timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59))),
            status='Borrowed',
            borrowed_condition='Good',
        )

        stdout = StringIO()
        call_command('send_due_notifications', stdout=stdout)

        self.assertIn('Due notification pass complete', stdout.getvalue())
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Due Date Reminder Email',
            transaction=due_soon_transaction,
            status='Sent',
        ).exists())
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Due Today Reminder Email',
            transaction=due_today_transaction,
            status='Sent',
        ).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    def test_due_notification_command_marks_overdue_and_alerts_borrower_and_staff(self):
        self.borrower.email = 'jane@example.com'
        self.borrower.save()
        self.item.status = 'Borrowed'
        self.item.save()
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() - timedelta(hours=2),
            status='Borrowed',
            borrowed_condition='Good',
        )

        call_command('send_due_notifications')

        transaction_record.refresh_from_db()
        self.assertEqual(transaction_record.status, 'Overdue')
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Overdue Borrower Email',
            transaction=transaction_record,
            status='Sent',
            recipient='jane@example.com',
        ).exists())
        staff_alert = NotificationLog.objects.get(
            channel='Email',
            event_type='Overdue Staff Alert Email',
            transaction=transaction_record,
            status='Sent',
        )
        self.assertIn('admin@example.com', staff_alert.recipient)
        self.assertIn('staff@example.com', staff_alert.recipient)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    def test_due_notification_command_skips_staff_alert_when_email_preferences_disabled(self):
        self.borrower.email = 'jane@example.com'
        self.borrower.save()
        self.admin_user.profile.notify_by_email = False
        self.admin_user.profile.save()
        self.staff_user.profile.notify_by_email = False
        self.staff_user.profile.save()
        self.item.status = 'Borrowed'
        self.item.save()
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() - timedelta(hours=2),
            status='Borrowed',
            borrowed_condition='Good',
        )

        call_command('send_due_notifications')

        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Overdue Staff Alert Email',
            transaction=transaction_record,
            status='Skipped',
            error_message='Staff/admin email notifications are disabled for every recipient.',
        ).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    def test_due_notification_command_logs_skipped_reminder_without_borrower_email(self):
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59))),
            status='Borrowed',
            borrowed_condition='Good',
        )

        call_command('send_due_notifications')

        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(NotificationLog.objects.filter(
            channel='Email',
            event_type='Due Today Reminder Email',
            transaction=transaction_record,
            status='Skipped',
            error_message='Borrower email is not set.',
        ).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@example.com',
    )
    def test_due_notification_command_does_not_duplicate_daily_reminders(self):
        self.borrower.email = 'jane@example.com'
        self.borrower.save()
        transaction_record = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59))),
            status='Borrowed',
            borrowed_condition='Good',
        )

        call_command('send_due_notifications')
        call_command('send_due_notifications')

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationLog.objects.filter(
            channel='Email',
            event_type='Due Today Reminder Email',
            transaction=transaction_record,
            status='Sent',
        ).count(), 1)

    def test_session_timeout_logs_user_out(self):
        self.client.login(username='staff1', password='StrongPass123!')
        session = self.client.session
        session['last_activity'] = int((timezone.now() - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT + 5)).timestamp())
        session.save()

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('login'))

    @override_settings(TELEGRAM_BOT_TOKEN='test-token', TELEGRAM_CHAT_ID='6048912919')
    @patch('core.management.commands.test_telegram_notification.send_telegram_message')
    def test_telegram_test_command_logs_success(self, mock_send_telegram_message):
        mock_send_telegram_message.return_value = {
            'ok': True,
            'status': 'sent',
            'recipient': '6048912919',
        }

        stdout = StringIO()
        call_command('test_telegram_notification', stdout=stdout)

        self.assertIn('Telegram test sent successfully', stdout.getvalue())
        self.assertTrue(NotificationLog.objects.filter(
            channel='Telegram',
            event_type='Manual Telegram Test',
            status='Sent',
        ).exists())

    def test_admin_can_update_system_settings(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('system_settings'), {
            'school_name': 'Smart Campus Hub',
            'school_logo_url': 'https://example.com/logo.png',
            'borrow_limit': 2,
            'overdue_grace_period_days': 1,
            'reminder_days_before_due': 2,
            'item_categories': 'AV, Lab, Sports',
        })

        self.assertRedirects(response, reverse('system_settings'))
        settings_obj = SystemSettings.load()
        self.assertEqual(settings_obj.school_name, 'Smart Campus Hub')
        self.assertEqual(settings_obj.borrow_limit, 2)

    def test_settings_page_is_grouped_into_admin_sections(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('system_settings'))

        self.assertContains(response, 'Users &amp; Roles')
        self.assertContains(response, 'Notifications')
        self.assertContains(response, 'Database Status')
        self.assertContains(response, 'Backup &amp; Restore')
        self.assertContains(response, 'Create JSON Backup')
        self.assertContains(response, 'Appearance')
        self.assertContains(response, 'Session Timeout')
        self.assertContains(response, 'Login Attempt Limit')

    def test_notification_center_filters_logs(self):
        NotificationLog.objects.create(
            channel='Email',
            recipient='jane@example.com',
            event_type='Due Today Reminder Email',
            message='Reminder for laptop',
            status='Failed',
            error_message='SMTP offline',
        )
        NotificationLog.objects.create(
            channel='Telegram',
            recipient='6048912919',
            event_type='Manual Telegram Test',
            message='Telegram ok',
            status='Sent',
        )
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.get(reverse('notification_list'), {
            'channel': 'Email',
            'status': 'Failed',
            'search': 'SMTP',
        })

        self.assertContains(response, 'Notification Center')
        self.assertContains(response, 'SMTP offline')
        self.assertNotContains(response, 'Telegram ok')

    def test_admin_can_run_notification_check_dry_run(self):
        self.client.login(username='admin1', password='StrongPass123!')

        response = self.client.post(reverse('run_notification_check'), {
            'dry_run': 'on',
        })

        self.assertRedirects(response, reverse('notification_list'))
        self.assertTrue(ActivityLog.objects.filter(action='Run Notification Check').exists())

    def test_admin_can_create_backup_from_settings(self):
        output_dir = settings.BASE_DIR / 'test-view-backups'
        if output_dir.exists():
            shutil.rmtree(output_dir)

        self.client.login(username='admin1', password='StrongPass123!')
        with override_settings(BACKUP_DIR=output_dir):
            response = self.client.post(reverse('create_system_backup'))

        created_files = list(output_dir.iterdir())
        shutil.rmtree(output_dir)

        self.assertRedirects(response, reverse('system_settings'))
        self.assertTrue(any(
            path.name.startswith('backup-') and path.suffix == '.json' and '.manifest.' not in path.name
            for path in created_files
        ))
        self.assertTrue(any(path.name.endswith('.manifest.json') for path in created_files))
        self.assertTrue(ActivityLog.objects.filter(action='Create Backup').exists())

    def test_borrower_email_is_saved(self):
        self.client.login(username='staff1', password='StrongPass123!')

        response = self.client.post(reverse('borrower_create'), {
            'full_name': 'John Example',
            'school_id': '2026-0009',
            'email': 'john@example.com',
            'program': 'BSCS',
            'section': 'B',
            'active_status': True,
        })

        self.assertRedirects(response, reverse('borrower_list'))
        borrower = Borrower.objects.get(school_id='2026-0009')
        self.assertEqual(borrower.email, 'john@example.com')

    def test_borrow_limit_from_system_settings_is_enforced(self):
        settings_obj = SystemSettings.load()
        settings_obj.borrow_limit = 1
        settings_obj.save()

        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )
        self.item.status = 'Borrowed'
        self.item.save()

        second_item = Item.objects.create(
            item_code='EQ-002',
            item_name='Projector',
            category='AV',
            status='Available',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.post(reverse('borrow_item'), {
            'borrower': self.borrower.pk,
            'item': second_item.pk,
            'due_time': (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'borrowed_condition': 'Good',
            'notes': 'Should be blocked by borrow limit',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'maximum of 1 active borrow')

    def test_active_transaction_per_item_is_database_enforced(self):
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
        )

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                Transaction.objects.create(
                    borrower=self.borrower,
                    item=self.item,
                    due_time=timezone.now() + timedelta(days=2),
                    status='Borrowed',
                    borrowed_condition='Good',
                )

    def test_borrow_form_shows_phase_five_guided_flow(self):
        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('borrow_item'))

        self.assertContains(response, 'Borrowing steps')
        self.assertContains(response, 'Confirm &amp; Process Borrow')
        self.assertContains(response, 'data-loading-label="Checking availability..."')

    def test_transaction_receipt_page_renders_borrow_details(self):
        transaction = Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Borrowed',
            borrowed_condition='Good',
            notes='Classroom use',
        )

        self.client.login(username='staff1', password='StrongPass123!')
        response = self.client.get(reverse('transaction_receipt', args=[transaction.pk]))

        self.assertContains(response, 'Borrow Receipt')
        self.assertContains(response, 'Transaction #')
        self.assertContains(response, 'Print Receipt')
        self.assertContains(response, 'Classroom use')

    def test_transaction_history_protects_borrower_and_item_from_delete(self):
        Transaction.objects.create(
            borrower=self.borrower,
            item=self.item,
            due_time=timezone.now() + timedelta(days=1),
            status='Returned',
            borrowed_condition='Good',
        )

        with self.assertRaises(ProtectedError):
            self.borrower.delete()

        with self.assertRaises(ProtectedError):
            self.item.delete()

    def test_activity_log_entries_are_immutable(self):
        log = ActivityLog.objects.create(
            user=self.staff_user,
            action='Test Log',
            description='Original entry',
        )

        log.description = 'Changed entry'
        with self.assertRaises(ValidationError):
            log.save()

        with self.assertRaises(ValidationError):
            log.delete()

    def test_security_headers_are_set(self):
        response = self.client.get(reverse('health_check'))

        self.assertIn('Content-Security-Policy', response)
        self.assertIn('Permissions-Policy', response)
        self.assertEqual(response['X-Permitted-Cross-Domain-Policies'], 'none')

    @override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=2, LOGIN_RATE_LIMIT_WINDOW=60)
    def test_login_rate_limit_blocks_repeated_failures(self):
        cache.clear()

        for _ in range(2):
            self.client.post(reverse('login'), {
                'username': 'staff1',
                'password': 'wrong-password',
            })

        response = self.client.post(reverse('login'), {
            'username': 'staff1',
            'password': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many failed login attempts')

    def test_supabase_url_parser_configures_ssl(self):
        config = supabase_config_from_url(
            'postgresql://dbuser:dbpass@example.supabase.co:5432/postgres?sslmode=require'
        )

        self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config['NAME'], 'postgres')
        self.assertEqual(config['USER'], 'dbuser')
        self.assertEqual(config['PASSWORD'], 'dbpass')
        self.assertEqual(config['HOST'], 'example.supabase.co')
        self.assertEqual(config['PORT'], '5432')
        self.assertEqual(config['OPTIONS']['sslmode'], 'require')

    def test_debug_allowed_hosts_can_accept_lan_devices(self):
        hosts = build_allowed_hosts('127.0.0.1,localhost', debug=True, allow_lan_hosts=True)

        self.assertIn('*', hosts)

        production_hosts = build_allowed_hosts('example.com', debug=False, allow_lan_hosts=True)
        self.assertNotIn('*', production_hosts)
