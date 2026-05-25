from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0035_remove_account_scrape_shard"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="refresh_warm_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Прогрев TikTok/Facebook в начале и периодически при refresh_all, bulk и автообновлении.",
            ),
        ),
    ]
