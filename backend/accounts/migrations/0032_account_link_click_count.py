from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0031_autorefreshstate_last_auto_refresh_error_account_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="link_click_count",
            field=models.BigIntegerField(
                default=0,
                help_text="Сумма кликов по коротким ссылкам Links с label = URL профиля; обновляется при refresh.",
                verbose_name="Переходы по ссылке из bio",
            ),
        ),
        migrations.AddField(
            model_name="accountsnapshot",
            name="link_click_count",
            field=models.BigIntegerField(default=0),
        ),
    ]
