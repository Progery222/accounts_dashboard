from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0042_scrape_backend_defaults_playwright"),
    ]

    operations = [
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="reddit_backend",
            field=models.CharField(
                choices=[("playwright", "Playwright"), ("apify", "Apify")],
                default="playwright",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="rumble_backend",
            field=models.CharField(
                choices=[("playwright", "Playwright"), ("apify", "Apify")],
                default="playwright",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="scrapebackendconfig",
            name="youtube_backend",
            field=models.CharField(
                choices=[("playwright", "Playwright"), ("apify", "Apify")],
                default="playwright",
                max_length=16,
            ),
        ),
    ]
