from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0059_topic"),
    ]

    operations = [
        migrations.CreateModel(
            name="TopicBoard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(default="ai", max_length=32, unique=True)),
                ("account_ids", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Порядок карточек (AI)",
                "verbose_name_plural": "Порядок карточек (AI)",
            },
        ),
    ]
