from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0049_account_is_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="include_archived_accounts",
            field=models.BooleanField(
                default=False,
                help_text="В автообновлении учитывать аккаунты в архиве.",
            ),
        ),
    ]
