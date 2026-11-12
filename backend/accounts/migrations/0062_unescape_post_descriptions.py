"""Посты, сохранённые с HTML-сущностями («night&#39;s»): переводим в символы.

Telegram-скрапер резал HTML регулярками и не раскодировал сущности: в топе
постов светилось «&#39;», а из «&#39;» вытаскивался хештег «#39».
Пересчитываем хештеги по исправленному тексту тем же правилом, что в sync.
"""
import html
import re

from django.db import migrations

ENTITY = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
HASHTAG = re.compile(r"#([\wЀ-ӿ]+)")


def forwards(apps, schema_editor):
    Post = apps.get_model("accounts", "Post")
    batch = []
    qs = Post.objects.filter(description__contains="&").only("id", "description", "hashtags")
    for post in qs.iterator(chunk_size=2000):
        text = post.description or ""
        if not ENTITY.search(text):
            continue
        fixed = html.unescape(text)
        if fixed == text:
            continue
        post.description = fixed
        post.hashtags = sorted({t.lower() for t in HASHTAG.findall(fixed)})
        batch.append(post)
        if len(batch) >= 500:
            Post.objects.bulk_update(batch, ["description", "hashtags"])
            batch = []
    if batch:
        Post.objects.bulk_update(batch, ["description", "hashtags"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0061_topic_board")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
