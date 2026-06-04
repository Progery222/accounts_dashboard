from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0045_owner_model_profile_cleanup"),
    ]

    operations = [
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="facebook_fallback_enabled",
            field=models.BooleanField(
                default=False,
                help_text="При сбое основного способа переключиться на запасной (логика по платформам).",
            ),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="tiktok_fallback_enabled",
            field=models.BooleanField(
                default=False,
                help_text="TikTok: Playwright→Apify при капче или 3 новых ошибках в одном прогоне.",
            ),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="instagram_fallback_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="youtube_fallback_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="reddit_fallback_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="rumble_fallback_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
