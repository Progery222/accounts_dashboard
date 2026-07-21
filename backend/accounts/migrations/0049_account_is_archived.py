from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0048_refreshscheduleconfig_group_country_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="is_archived",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Архивные аккаунты скрыты из основного списка и не участвуют в автообновлении.",
                verbose_name="В архиве",
            ),
        ),
    ]
