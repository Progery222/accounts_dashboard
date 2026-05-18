from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0030_audiencemember_follower_network"),
    ]

    operations = [
        migrations.AddField(
            model_name="autorefreshstate",
            name="last_auto_refresh_error_account_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
