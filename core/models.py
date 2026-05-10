from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Borrower(models.Model):
    full_name = models.CharField(max_length=255)
    school_id = models.CharField(max_length=50, unique=True)
    email = models.EmailField(blank=True, null=True)
    program = models.CharField(max_length=100, blank=True, null=True)
    section = models.CharField(max_length=100, blank=True, null=True)
    active_status = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.school_id})"

    def clean(self):
        if not self.full_name.strip():
            raise ValidationError({'full_name': 'Full name is required.'})
        if not self.school_id.strip():
            raise ValidationError({'school_id': 'School ID is required.'})


class Item(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Borrowed', 'Borrowed'),
        ('Maintenance', 'Maintenance'),
    ]

    item_code = models.CharField(max_length=50, unique=True)
    item_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.item_name} ({self.item_code})"

    def clean(self):
        errors = {}
        if not self.item_code.strip():
            errors['item_code'] = 'Item code is required.'
        if not self.item_name.strip():
            errors['item_name'] = 'Item name is required.'
        if not self.category.strip():
            errors['category'] = 'Category is required.'
        if errors:
            raise ValidationError(errors)


class Transaction(models.Model):
    CONDITION_CHOICES = [
        ('Excellent', 'Excellent'),
        ('Good', 'Good'),
        ('Fair', 'Fair'),
        ('Damaged', 'Damaged'),
    ]

    STATUS_CHOICES = [
        ('Borrowed', 'Borrowed'),
        ('Returned', 'Returned'),
        ('Overdue', 'Overdue'),
    ]

    borrower = models.ForeignKey(Borrower, on_delete=models.PROTECT)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    borrow_time = models.DateTimeField(auto_now_add=True)
    due_time = models.DateTimeField(blank=True, null=True)
    return_time = models.DateTimeField(blank=True, null=True)
    borrowed_condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='Good')
    returned_condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Borrowed')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status'], name='core_tr_status_idx'),
            models.Index(fields=['borrow_time'], name='core_tr_borrow_idx'),
            models.Index(fields=['due_time'], name='core_tr_due_idx'),
            models.Index(fields=['return_time'], name='core_tr_return_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['item'],
                condition=models.Q(status__in=['Borrowed', 'Overdue']),
                name='core_unique_active_transaction_per_item',
            ),
        ]

    def __str__(self):
        return f"{self.borrower.full_name} - {self.item.item_name}"

    @property
    def days_overdue(self):
        if not self.due_time or self.status not in {'Borrowed', 'Overdue'}:
            return 0
        now = timezone.now()
        if now <= self.due_time:
            return 0
        local_due_date = timezone.localtime(self.due_time).date()
        local_today = timezone.localdate()
        return max((local_today - local_due_date).days, 1)

    def clean(self):
        errors = {}
        if self.return_time and self.borrow_time and self.return_time < self.borrow_time:
            errors['return_time'] = 'Return time cannot be earlier than borrow time.'
        if self.status == 'Returned' and not self.return_time:
            errors['return_time'] = 'Returned transactions must have a return time.'
        if self.status in {'Borrowed', 'Overdue'} and self.return_time:
            errors['return_time'] = 'Active borrow transactions cannot have a return time.'
        if errors:
            raise ValidationError(errors)


class NotificationLog(models.Model):
    CHANNEL_CHOICES = [
        ('Email', 'Email'),
        ('Telegram', 'Telegram'),
    ]

    STATUS_CHOICES = [
        ('Sent', 'Sent'),
        ('Failed', 'Failed'),
        ('Skipped', 'Skipped'),
    ]

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    recipient = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(max_length=100)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)
    triggered_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
    transaction = models.ForeignKey('Transaction', on_delete=models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.channel} - {self.event_type} - {self.status}"


class SystemSettings(models.Model):
    school_name = models.CharField(max_length=255, default='Campus Equipment Borrowing & Monitoring System')
    school_logo_url = models.URLField(blank=True)
    borrow_limit = models.PositiveIntegerField(default=3)
    overdue_grace_period_days = models.PositiveIntegerField(default=0)
    reminder_days_before_due = models.PositiveIntegerField(default=1)
    item_categories = models.TextField(
        blank=True,
        help_text='Comma-separated list of item categories such as AV, Lab, Sports, Tools.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.school_name

    @classmethod
    def load(cls):
        settings_obj, _ = cls.objects.get_or_create(pk=1)
        return settings_obj


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
    action = models.CharField(max_length=100)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return self.action

    def save(self, *args, **kwargs):
        if self.pk and ActivityLog.objects.filter(pk=self.pk).exists():
            raise ValidationError('Activity log entries are immutable and cannot be edited.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Activity log entries are immutable and cannot be deleted.')


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('Admin', 'Admin'),
        ('Staff', 'Staff'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Staff')
    notify_by_email = models.BooleanField(default=True)
    notify_by_telegram = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class MaintenanceRecord(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='maintenance_records')
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.item.item_name} - {self.new_status}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, raw=False, **kwargs):
    if raw:
        return
    UserProfile.objects.get_or_create(user=instance)
