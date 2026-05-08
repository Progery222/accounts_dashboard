from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0020_autorefreshpoint"),
    ]

    operations = [
        migrations.AddField(
            model_name="autorefreshpoint",
            name="platform_deltas",
            field=models.JSONField(
                default=dict,
                help_text="Дельты просмотров по платформам для этого прогона, например {'tiktok': 1200}.",
            ),
        ),
    ]
