from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_checklist_hardening'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='notify_by_email',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='notify_by_telegram',
            field=models.BooleanField(default=True),
        ),
    ]
