from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0047_account_group_country"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_group_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Пусто — все группы; иначе id групп и/или «none» (без группы).",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_country_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Пусто — все страны; иначе id стран и/или «none» (без страны).",
            ),
        ),
    ]
