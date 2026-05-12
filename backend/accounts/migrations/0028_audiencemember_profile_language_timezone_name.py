from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_rename_accounts_aut_local_d_229762_idx_accounts_au_local_d_43bfc3_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="audiencemember",
            name="profile_language",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Язык/локаль профиля с площадки (если отдаётся), например en, ru.",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="audiencemember",
            name="timezone_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Часовой пояс с площадки (если отдаётся), например Europe/Moscow.",
                max_length=64,
            ),
        ),
    ]
