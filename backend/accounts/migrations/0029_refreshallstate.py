# Generated manually for async refresh_all progress UI.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0028_audiencemember_profile_language_timezone_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="RefreshAllState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_running", models.BooleanField(default=False)),
                ("cancel_requested", models.BooleanField(default=False)),
                ("total_accounts", models.IntegerField(default=0)),
                ("processed_accounts", models.IntegerField(default=0)),
                ("success_accounts", models.IntegerField(default=0)),
                ("failed_accounts", models.IntegerField(default=0)),
                ("current_account", models.CharField(blank=True, default="", max_length=255)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("last_report_csv", models.TextField(blank=True, default="")),
                ("last_report_generated_at", models.DateTimeField(blank=True, null=True)),
                ("run_detail", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Состояние сбора всех аккаунтов",
            },
        ),
    ]
