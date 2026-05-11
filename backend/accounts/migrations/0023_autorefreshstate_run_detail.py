# Generated manually for auto-refresh per-account progress UI.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0022_refreshschedule_include_unavailable_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="autorefreshstate",
            name="run_detail",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
