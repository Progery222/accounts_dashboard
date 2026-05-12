import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0025_refreshscheduleconfig_max_audience_followers"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="audience_last_synced_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Последний успешный съём списка подписчиков (TikTok/Instagram).",
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="AudienceMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("tiktok", "TikTok"), ("instagram", "Instagram"), ("youtube", "YouTube"), ("telegram", "Telegram"), ("x", "X (Twitter)"), ("threads", "Threads"), ("facebook", "Facebook"), ("rumble", "Rumble"), ("reddit", "Reddit")], db_index=True, max_length=20)),
                ("username", models.CharField(db_index=True, max_length=255)),
                ("external_id", models.CharField(blank=True, default="", max_length=160)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("avatar_url", models.URLField(blank=True, max_length=2048)),
                ("bio", models.TextField(blank=True)),
                ("is_private", models.BooleanField(default=False)),
                ("follower_count", models.BigIntegerField(default=0)),
                ("following_count", models.BigIntegerField(default=0)),
                ("like_count", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["username"],
            },
        ),
        migrations.CreateModel(
            name="AccountAudienceMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audience_memberships", to="accounts.account")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="accounts.audiencemember")),
            ],
            options={
                "ordering": ["-last_synced_at"],
                "unique_together": {("account", "member")},
            },
        ),
        migrations.CreateModel(
            name="AudienceMemberPost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("thumbnail_url", models.URLField(blank=True, max_length=2048)),
                ("post_url", models.URLField(blank=True, max_length=2048)),
                ("view_count", models.BigIntegerField(default=0)),
                ("like_count", models.BigIntegerField(default=0)),
                ("comment_count", models.BigIntegerField(default=0)),
                ("share_count", models.BigIntegerField(default=0)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audience_posts", to="accounts.audiencemember")),
            ],
            options={
                "ordering": ["-posted_at", "-id"],
                "unique_together": {("member", "external_id")},
            },
        ),
        migrations.AddConstraint(
            model_name="audiencemember",
            constraint=models.UniqueConstraint(fields=("platform", "username"), name="audience_member_unique_platform_username"),
        ),
    ]
