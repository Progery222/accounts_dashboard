from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0036_refreshscheduleconfig_refresh_warm_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_platforms",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Пусто — все платформы; иначе только перечисленные id (tiktok, instagram, …).",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_profile_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Пусто — все профили; иначе id профилей и/или «none» (без профиля).",
            ),
        ),
    ]
