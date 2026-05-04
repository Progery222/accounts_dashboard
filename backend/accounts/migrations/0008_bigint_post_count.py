from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_refresh_schedule_config"),
    ]

    operations = [
        # Account.post_count
        migrations.AlterField(
            model_name="account",
            name="post_count",
            field=models.BigIntegerField(default=0),
        ),
        # AccountSnapshot.post_count
        migrations.AlterField(
            model_name="accountsnapshot",
            name="post_count",
            field=models.BigIntegerField(default=0),
        ),
    ]
