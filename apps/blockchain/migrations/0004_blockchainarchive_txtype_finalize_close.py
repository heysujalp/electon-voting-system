"""Add BlockchainArchive model and FINALIZE/CLOSE TxType choices."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("blockchain", "0003_contractdeployment_add_localnet"),
        ("elections", "0001_initial"),
    ]

    operations = [
        # ── 1. Add FINALIZE / CLOSE to TxType choices (no column change needed) ──
        migrations.AlterField(
            model_name="blockchaintransaction",
            name="tx_type",
            field=models.CharField(
                choices=[
                    ("deploy", "Deploy Election"),
                    ("register_voters", "Register Voters"),
                    ("cast_vote", "Cast Vote"),
                    ("finalize", "Finalize Election"),
                    ("close_election", "Close Election Account"),
                ],
                max_length=30,
            ),
        ),
        # ── 2. Create BlockchainArchive table ─────────────────────────────────
        migrations.CreateModel(
            name="BlockchainArchive",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "election",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blockchain_archive",
                        to="elections.election",
                    ),
                ),
                ("merkle_root", models.BinaryField(max_length=32)),
                ("voted_bitfield", models.BinaryField()),
                ("vote_counts", models.JSONField(default=dict)),
                ("config_hash", models.BinaryField(max_length=32)),
                ("total_voters", models.PositiveIntegerField(default=0)),
                ("total_votes_cast", models.PositiveIntegerField(default=0)),
                ("on_chain_slot", models.BigIntegerField(default=0)),
                ("archived_at", models.DateTimeField(auto_now_add=True)),
                ("account_closed_at", models.DateTimeField(blank=True, null=True)),
                ("rent_recovered_lamports", models.BigIntegerField(default=0)),
            ],
            options={"db_table": "blockchain_archive"},
        ),
    ]
