# Темы для домена AI: многие-ко-многим с аккаунтами.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0058_autorefreshpoint_account_totals"),
    ]

    operations = [
        migrations.CreateModel(
            name="Topic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=63, unique=True)),
                ("color", models.CharField(default="#6366f1", max_length=7)),
                ("emoji", models.CharField(blank=True, default="", max_length=8)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accounts", models.ManyToManyField(
                    blank=True, related_name="topics", to="accounts.account",
                    help_text="Аккаунты темы. Один аккаунт может быть в нескольких темах.",
                )),
            ],
            options={
                "ordering": ["sort_order", "name"],
                "verbose_name": "Тема (AI)",
                "verbose_name_plural": "Темы (AI)",
            },
        ),
    ]
