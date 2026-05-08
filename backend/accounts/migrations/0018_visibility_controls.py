from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_auto_refresh_csv_report"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="is_hidden",
            field=models.BooleanField(
                default=False,
                help_text="Скрыть профиль и его аккаунты на главном экране для всех пользователей.",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="include_hidden_platform_accounts",
            field=models.BooleanField(
                default=False,
                help_text="В автообновлении учитывать аккаунты скрытых платформ.",
            ),
        ),
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="include_hidden_profile_accounts",
            field=models.BooleanField(
                default=False,
                help_text="В автообновлении учитывать аккаунты скрытых профилей.",
            ),
        ),
        migrations.CreateModel(
            name="GlobalVisibilityConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hidden_platforms", models.JSONField(default=list)),
            ],
            options={
                "verbose_name": "Глобальная видимость платформ",
            },
        ),
    ]
