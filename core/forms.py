from datetime import timedelta

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.utils import timezone

from .models import Borrower, Item, MaintenanceRecord, SystemSettings, Transaction, UserProfile


class CustomUserRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'password1', 'password2']

    def __init__(self, *args, include_role=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_role:
            self.fields['role'].required = False
            self.fields['role'].widget = forms.HiddenInput()

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email already exists.")
        return email

    def save(self, commit=True, role=None):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        chosen_role = role or self.cleaned_data['role']
        user.is_staff = chosen_role == 'Admin'

        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = chosen_role
            profile.save()

        return user


class CustomAuthenticationForm(AuthenticationForm):
    login_role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.RadioSelect,
    )
    username = forms.CharField(widget=forms.TextInput(attrs={
        'autofocus': True,
        'autocomplete': 'username',
        'placeholder': 'Enter admin or staff username',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'autocomplete': 'current-password',
        'placeholder': 'Enter password',
    }))
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'aria-describedby': 'remember-help',
        }),
    )


class BorrowerSelfServiceLookupForm(forms.Form):
    school_id = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={
            'autocomplete': 'off',
            'placeholder': 'Enter your school ID',
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'placeholder': 'Enter your registered email',
        }),
    )

    def clean_school_id(self):
        return self.cleaned_data['school_id'].strip()

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class BorrowerForm(forms.ModelForm):
    class Meta:
        model = Borrower
        fields = ['full_name', 'school_id', 'email', 'program', 'section', 'active_status']

    def clean_school_id(self):
        school_id = self.cleaned_data['school_id']
        qs = Borrower.objects.filter(school_id=school_id)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("School ID already exists.")

        return school_id

    def clean_full_name(self):
        full_name = self.cleaned_data['full_name'].strip()
        if not full_name:
            raise forms.ValidationError("Full name is required.")
        return full_name

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            return ''

        qs = Borrower.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("Borrower email already exists.")

        return email

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk and self.instance.is_archived:
            raise forms.ValidationError("Archived borrowers cannot be edited.")
        return cleaned_data


class ItemForm(forms.ModelForm):
    maintenance_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Explain the maintenance issue or work performed.'}),
        help_text='Required when setting an item to Maintenance.',
    )

    class Meta:
        model = Item
        fields = ['item_code', 'item_name', 'category', 'description', 'status']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings_obj = SystemSettings.load()
        self.category_options = [
            category.strip()
            for category in (settings_obj.item_categories or '').split(',')
            if category.strip()
        ]
        self.fields['category'].widget.attrs.update({
            'list': 'category-options',
            'autocomplete': 'off',
            'placeholder': 'Choose or type a category',
        })
        if self.category_options:
            self.fields['category'].help_text = f"Suggested categories: {', '.join(self.category_options)}"

    def clean_item_code(self):
        item_code = self.cleaned_data['item_code']
        qs = Item.objects.filter(item_code=item_code)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("Item code already exists.")

        return item_code

    def clean_item_name(self):
        item_name = self.cleaned_data['item_name'].strip()
        if not item_name:
            raise forms.ValidationError("Item name is required.")
        return item_name

    def clean_category(self):
        category = self.cleaned_data['category'].strip()
        if not category:
            raise forms.ValidationError("Category is required.")
        return category

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        maintenance_notes = (cleaned_data.get('maintenance_notes') or '').strip()

        if self.instance.pk and self.instance.is_archived:
            raise forms.ValidationError("Archived items cannot be edited.")

        if status == 'Maintenance' and not maintenance_notes:
            self.add_error('maintenance_notes', "Maintenance notes are required when the item is under maintenance.")

        return cleaned_data


class TransactionForm(forms.ModelForm):
    due_time = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        input_formats=['%Y-%m-%dT%H:%M'],
    )
    borrowed_condition = forms.ChoiceField(choices=Transaction.CONDITION_CHOICES)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes about the item, borrower, or borrowing purpose.'}),
    )

    class Meta:
        model = Transaction
        fields = ['borrower', 'item', 'due_time', 'borrowed_condition', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        borrower_queryset = Borrower.objects.filter(
            active_status=True,
            is_archived=False,
        )
        item_queryset = Item.objects.filter(
            status='Available',
            is_archived=False,
        )

        if self.is_bound:
            borrower_id = self.data.get('borrower')
            item_id = self.data.get('item')
            if borrower_id:
                borrower_queryset = Borrower.objects.filter(is_archived=False).filter(
                    Q(active_status=True) | Q(pk=borrower_id)
                )
            if item_id:
                item_queryset = Item.objects.filter(is_archived=False).filter(
                    Q(status='Available') | Q(pk=item_id)
                )

        self.fields['borrower'].queryset = borrower_queryset.order_by('full_name')
        self.fields['item'].queryset = item_queryset.order_by('item_name')
        self.fields['borrower'].widget.attrs.update({
            'data-step-field': 'borrower',
            'aria-describedby': 'borrower-help',
        })
        self.fields['item'].widget.attrs.update({
            'data-step-field': 'item',
            'aria-describedby': 'item-help',
        })
        self.fields['due_time'].widget.attrs.update({
            'min': (timezone.localtime() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'),
        })

        if not self.is_bound:
            initial_due_time = timezone.localtime() + timedelta(days=1)
            self.initial['due_time'] = initial_due_time.strftime('%Y-%m-%dT%H:%M')

    def clean_item(self):
        item = self.cleaned_data['item']
        if item.is_archived:
            raise forms.ValidationError("Archived items cannot be borrowed.")
        if item.status != 'Available':
            raise forms.ValidationError("This item is not available for borrowing.")
        return item

    def clean_borrower(self):
        borrower = self.cleaned_data['borrower']
        if borrower.is_archived:
            raise forms.ValidationError("Archived borrowers cannot borrow items.")
        if not borrower.active_status:
            raise forms.ValidationError("Inactive borrowers cannot borrow items.")
        settings_obj = SystemSettings.load()
        active_borrow_count = Transaction.objects.filter(
            borrower=borrower,
            status__in=['Borrowed', 'Overdue'],
        ).count()
        if settings_obj.borrow_limit and active_borrow_count >= settings_obj.borrow_limit:
            raise forms.ValidationError(
                f'This borrower already reached the maximum of {settings_obj.borrow_limit} active borrow(s).'
            )
        return borrower

    def clean_due_time(self):
        due_time = self.cleaned_data['due_time']
        if due_time <= timezone.now():
            raise forms.ValidationError("Due date and time must be in the future.")
        return due_time


class UserUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    notify_by_email = forms.BooleanField(required=False, label='Email Notifications')
    notify_by_telegram = forms.BooleanField(required=False, label='Telegram Notifications')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            profile, _ = UserProfile.objects.get_or_create(user=self.instance)
            self.fields['role'].initial = profile.role
            self.fields['notify_by_email'].initial = profile.notify_by_email
            self.fields['notify_by_telegram'].initial = profile.notify_by_telegram

    def clean_email(self):
        email = self.cleaned_data['email']
        qs = User.objects.filter(email=email)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("Email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data['role']
        user.is_staff = role == 'Admin'

        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.notify_by_email = self.cleaned_data['notify_by_email']
            profile.notify_by_telegram = self.cleaned_data['notify_by_telegram']
            profile.save()

        return user


class SelfProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    notify_by_email = forms.BooleanField(required=False, label='Email Notifications')
    notify_by_telegram = forms.BooleanField(required=False, label='Telegram Notifications')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            profile, _ = UserProfile.objects.get_or_create(user=self.instance)
            self.fields['notify_by_email'].initial = profile.notify_by_email
            self.fields['notify_by_telegram'].initial = profile.notify_by_telegram

    def clean_email(self):
        email = self.cleaned_data['email']
        qs = User.objects.filter(email=email)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("Email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)

        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.notify_by_email = self.cleaned_data['notify_by_email']
            profile.notify_by_telegram = self.cleaned_data['notify_by_telegram']
            profile.save()

        return user


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'school_name',
            'school_logo_url',
            'borrow_limit',
            'overdue_grace_period_days',
            'reminder_days_before_due',
            'item_categories',
        ]
        widgets = {
            'item_categories': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'AV, Lab, Sports, Tools',
            }),
        }

    def clean_school_name(self):
        school_name = self.cleaned_data['school_name'].strip()
        if not school_name:
            raise forms.ValidationError("School name is required.")
        return school_name


class ReturnTransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['returned_condition', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional return notes, damages, or observations.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['returned_condition'].required = True
        self.fields['notes'].required = False

    def clean(self):
        cleaned_data = super().clean()
        returned_condition = cleaned_data.get('returned_condition')
        notes = (cleaned_data.get('notes') or '').strip()

        if returned_condition == 'Damaged' and not notes:
            self.add_error('notes', "Return notes are required when the item is damaged.")

        return cleaned_data


class MaintenanceRecordForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRecord
        fields = ['notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the issue, repair, or maintenance action.'}),
        }
