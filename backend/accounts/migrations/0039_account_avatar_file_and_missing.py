from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0038_auto_refresh_telegram"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="avatar_file",
            field=models.FileField(
                blank=True,
                help_text="Локальная копия аватара (скачивается один раз при refresh).",
                max_length=512,
                upload_to="accounts/avatars/%Y/%m/",
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="avatar_missing",
            field=models.BooleanField(
                default=False,
                help_text="На площадке нет аватара; не пытаться скачивать при автообновлении.",
            ),
        ),
        migrations.AlterField(
            model_name="account",
            name="avatar_url",
            field=models.URLField(
                blank=True,
                help_text="CDN-URL с площадки; fallback, если локальный файл ещё не скачан.",
                max_length=1024,
            ),
        ),
    ]
