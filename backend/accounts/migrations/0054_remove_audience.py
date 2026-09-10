"""Remove audience models and related schedule/account fields."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0053_seed_domains"),
    ]

    operations = [
        migrations.DeleteModel(name="AudienceMemberPost"),
        migrations.DeleteModel(name="AccountAudienceMembership"),
        migrations.DeleteModel(name="AudienceMember"),
        migrations.RemoveField(
            model_name="account",
            name="audience_last_synced_at",
        ),
        migrations.RemoveField(
            model_name="refreshscheduleconfig",
            name="max_audience_followers_per_account",
        ),
    ]
