from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0024_refreshscheduleconfig_account_delta_period_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="max_audience_followers_per_account",
            field=models.PositiveSmallIntegerField(
                default=100,
                help_text="Не более стольких подписчиков на один отслеживаемый аккаунт (не больше 100; съём аудитории TikTok/Instagram).",
            ),
        ),
    ]
