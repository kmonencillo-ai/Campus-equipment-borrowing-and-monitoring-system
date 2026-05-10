from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_userprofile_notification_preferences'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='transaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=['Borrowed', 'Overdue']),
                fields=('item',),
                name='core_unique_active_transaction_per_item',
            ),
        ),
    ]
