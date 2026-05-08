from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0021_autorefreshpoint_platform_deltas"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="include_unavailable_accounts",
            field=models.BooleanField(
                default=False,
                help_text="В автообновлении учитывать недоступные аккаунты.",
            ),
        ),
    ]
