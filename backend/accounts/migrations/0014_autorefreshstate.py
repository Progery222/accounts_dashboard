from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_alter_account_profile_unavailable"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutoRefreshState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_running", models.BooleanField(default=False)),
                ("source", models.CharField(blank=True, default="scheduler", max_length=32)),
                ("total_accounts", models.IntegerField(default=0)),
                ("processed_accounts", models.IntegerField(default=0)),
                ("success_accounts", models.IntegerField(default=0)),
                ("failed_accounts", models.IntegerField(default=0)),
                ("current_account", models.CharField(blank=True, default="", max_length=255)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Состояние автообновления",
            },
        ),
    ]
