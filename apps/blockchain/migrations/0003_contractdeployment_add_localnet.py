from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("blockchain", "0002_remove_blockchaintransaction_block_number_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contractdeployment",
            name="network",
            field=models.CharField(
                choices=[
                    ("localnet", "Solana Localnet (test-validator)"),
                    ("devnet", "Solana Devnet"),
                    ("mainnet-beta", "Solana Mainnet Beta"),
                ],
                max_length=20,
            ),
        ),
    ]
