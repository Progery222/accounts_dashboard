# Generated manually for schedule domain scope

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0055_externalapikey"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshscheduleconfig",
            name="auto_refresh_domain_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Пусто — все домены; иначе id доменов и/или «none» (без домена).",
            ),
        ),
    ]
