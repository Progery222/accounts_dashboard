from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_alter_account_platform"),
    ]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="platform",
            field=models.CharField(
                choices=[
                    ("tiktok", "TikTok"),
                    ("instagram", "Instagram"),
                    ("youtube", "YouTube"),
                    ("telegram", "Telegram"),
                    ("x", "X (Twitter)"),
                    ("threads", "Threads"),
                    ("facebook", "Facebook"),
                    ("rumble", "Rumble"),
                ],
                max_length=20,
            ),
        ),
    ]
