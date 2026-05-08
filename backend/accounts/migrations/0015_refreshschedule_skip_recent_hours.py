from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_autorefreshstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="skip_recent_hours",
            field=models.IntegerField(default=0),
        ),
    ]
