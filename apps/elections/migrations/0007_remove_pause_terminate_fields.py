# Dashboard V2 — Remove legacy pause/terminate fields
# These fields were never used in V2 views and have been cleaned from the codebase.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0006_add_election_type'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='election',
            name='is_paused',
        ),
        migrations.RemoveField(
            model_name='election',
            name='is_terminated_by_admin',
        ),
    ]
