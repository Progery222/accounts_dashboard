from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0032_account_link_click_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="missing_from_scrape_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
