from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0050_refreshscheduleconfig_include_archived_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="is_banned",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Забаненные аккаунты скрыты из основного списка и не участвуют в автообновлении.",
                verbose_name="В бане",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="include_banned_accounts",
            field=models.BooleanField(
                default=False,
                help_text="В автообновлении учитывать аккаунты в бане.",
            ),
        ),
    ]
