from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0034_account_scrape_shard"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="account",
            name="scrape_shard",
        ),
    ]
