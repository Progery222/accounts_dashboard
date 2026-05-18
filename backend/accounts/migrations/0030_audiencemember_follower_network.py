# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0029_refreshallstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="audiencemember",
            name="follower_network",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Срез подписчиков этого подписчика (TikTok), до 100 записей с полями username, bio, счётчики.",
            ),
        ),
    ]
