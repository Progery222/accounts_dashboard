from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0060_topicboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="topic",
            name="board",
            field=models.CharField(
                db_index=True, default="ai", max_length=63,
                help_text="Slug домена, которому принадлежит тема: ai или stands.",
            ),
        ),
    ]
