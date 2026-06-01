from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0039_account_avatar_file_and_missing"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="thumbnail_file",
            field=models.FileField(
                blank=True,
                help_text="Локальная копия превью (скачивается один раз при sync постов).",
                max_length=512,
                upload_to="posts/thumbnails/%Y/%m/",
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="thumbnail_missing",
            field=models.BooleanField(
                default=False,
                help_text="У поста нет превью на площадке; не пытаться скачивать при обновлении.",
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="thumbnail_url",
            field=models.URLField(
                blank=True,
                help_text="CDN-URL превью; fallback, если локальный файл ещё не скачан.",
                max_length=2048,
            ),
        ),
    ]
