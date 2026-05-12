from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0023_autorefreshstate_run_detail"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="account_delta_period_days",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="За сколько календарных дней назад брать опорный снимок для дельт в списке аккаунтов (1, 7 или 30).",
            ),
        ),
    ]
