from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_refreshschedule_skip_recent_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="autorefreshstate",
            name="cancel_requested",
            field=models.BooleanField(default=False),
        ),
    ]
