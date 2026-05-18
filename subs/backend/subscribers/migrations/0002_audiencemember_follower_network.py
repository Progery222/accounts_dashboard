# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscribers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="audiencemember",
            name="follower_network",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Подписчики этого подписчика (TikTok), снимок с дашборда.",
            ),
        ),
    ]
