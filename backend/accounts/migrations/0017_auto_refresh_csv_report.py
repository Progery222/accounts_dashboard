from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_autorefreshstate_cancel_requested"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_csv_report",
            field=models.BooleanField(
                default=False,
                help_text="После завершения автообновления сохранять CSV-отчёт для скачивания в интерфейсе.",
            ),
        ),
        migrations.AddField(
            model_name="autorefreshstate",
            name="last_report_csv",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="autorefreshstate",
            name="last_report_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
