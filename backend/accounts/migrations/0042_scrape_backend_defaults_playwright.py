"""Сброс singleton способа сбора на Playwright (дефолт продукта)."""

from django.db import migrations


def reset_to_playwright(apps, schema_editor):
    ScrapeBackendConfig = apps.get_model("accounts", "ScrapeBackendConfig")
    ScrapeBackendConfig.objects.update_or_create(
        pk=1,
        defaults={
            "facebook_backend": "playwright",
            "tiktok_backend": "playwright",
            "instagram_backend": "playwright",
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0041_scrape_backend_apify"),
    ]

    operations = [
        migrations.RunPython(reset_to_playwright, migrations.RunPython.noop),
    ]
