# Generated manually for ExternalApiKey + external API v1

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0054_remove_audience"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalApiKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Кто пользуется ключом (сервис / интеграция).", max_length=128)),
                ("key_prefix", models.CharField(db_index=True, help_text="Префикс для поиска в админке.", max_length=16)),
                ("key_hash", models.CharField(max_length=64, unique=True)),
                (
                    "scopes",
                    models.JSONField(default=list, help_text='Список: "read", "write", "refresh", "export".'),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "domain",
                    models.ForeignKey(
                        blank=True,
                        help_text="Если задан — все запросы ключа ограничены этим доменом (как X-Domain).",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="api_keys",
                        to="accounts.domain",
                    ),
                ),
            ],
            options={
                "verbose_name": "Внешний API-ключ",
                "verbose_name_plural": "Внешние API-ключи",
                "ordering": ["-created_at"],
            },
        ),
    ]
