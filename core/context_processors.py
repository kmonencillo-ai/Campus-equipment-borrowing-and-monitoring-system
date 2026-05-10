from django.utils import timezone

from .models import SystemSettings, Transaction, UserProfile


def system_settings(request):
    user_role = ''
    overdue_count = 0
    due_today_count = 0
    if request.user.is_authenticated:
        try:
            user_role = request.user.profile.role
        except UserProfile.DoesNotExist:
            user_role = ''
        if user_role in {'Admin', 'Staff'}:
            today = timezone.localdate()
            overdue_count = Transaction.objects.filter(status='Overdue').count()
            due_today_count = Transaction.objects.filter(
                status='Borrowed',
                due_time__date=today,
            ).count()

    return {
        'system_settings': SystemSettings.load(),
        'current_user_role': user_role,
        'can_manage_records': user_role in {'Admin', 'Staff'},
        'is_admin_user': user_role == 'Admin',
        'global_overdue_count': overdue_count,
        'global_due_today_count': due_today_count,
    }
