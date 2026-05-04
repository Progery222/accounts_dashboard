from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_alter_account_platform_add_rumble"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="profile_unavailable",
            field=models.BooleanField(
                default=False,
                verbose_name="Профиль на площадке недоступен",
                help_text="Последнее обновление зафиксировало удалённый или недоступный профиль (например Instagram).",
            ),
        ),
    ]
