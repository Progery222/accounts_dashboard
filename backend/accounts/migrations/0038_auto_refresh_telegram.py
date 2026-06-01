from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0037_refreshscheduleconfig_auto_refresh_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_telegram_enabled",
            field=models.BooleanField(
                default=False,
                help_text="После успешного автообновления отправлять отчёт в Telegram.",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_telegram_chat_id",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                help_text="Chat ID получателя (личный чат с ботом).",
            ),
        ),
        migrations.AlterField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_csv_report",
            field=models.BooleanField(
                default=True,
                help_text="После завершения автообновления сохранять CSV-отчёт для скачивания в интерфейсе.",
            ),
        ),
        migrations.AddField(
            model_name="autorefreshstate",
            name="last_telegram_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="autorefreshstate",
            name="last_telegram_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
