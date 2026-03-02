# Generated migration — remove dead password_reset_attempts field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_remove_customuser_last_password_reset_request_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customuser',
            name='password_reset_attempts',
        ),
    ]
