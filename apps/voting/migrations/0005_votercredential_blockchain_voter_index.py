"""Add blockchain_voter_index to VoterCredential for Merkle tree model."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("voting", "0004_add_batch_and_timestamps"),
    ]

    operations = [
        migrations.AddField(
            model_name="votercredential",
            name="blockchain_voter_index",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text=(
                    "0-based position of this voter in the election's Merkle tree. "
                    "Set by deploy_election() before the election is launched."
                ),
            ),
        ),
    ]
