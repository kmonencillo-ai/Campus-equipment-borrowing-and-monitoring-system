from django.contrib import admin
from .models import ActivityLog, Borrower, Item, MaintenanceRecord, NotificationLog, SystemSettings, Transaction, UserProfile


class ReadOnlyLogAdmin(admin.ModelAdmin):
    readonly_fields = [field.name for field in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(Borrower)
admin.site.register(Item)
admin.site.register(Transaction)
admin.site.register(ActivityLog, ReadOnlyLogAdmin)
admin.site.register(NotificationLog)
admin.site.register(SystemSettings)
admin.site.register(UserProfile)
admin.site.register(MaintenanceRecord)
