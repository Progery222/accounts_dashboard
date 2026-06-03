# Generated manually

from django.db import migrations, models


def copy_legacy_chat_id(apps, schema_editor):
    RefreshScheduleConfig = apps.get_model("accounts", "RefreshScheduleConfig")
    for cfg in RefreshScheduleConfig.objects.all():
        legacy = (cfg.auto_refresh_telegram_chat_id or "").strip()
        existing = cfg.auto_refresh_telegram_chat_ids
        if legacy and (not existing or existing == []):
            cfg.auto_refresh_telegram_chat_ids = [legacy]
            cfg.save(update_fields=["auto_refresh_telegram_chat_ids"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0043_scrape_backend_more_platforms"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_telegram_chat_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Список chat ID получателей отчёта в Telegram.",
            ),
        ),
        migrations.RunPython(copy_legacy_chat_id, migrations.RunPython.noop),
    ]
