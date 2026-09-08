"""Заводим домены, под которые делалась фича.

Без этого 0052 создаёт только пустую таблицу, и /product на сервере отвечает
«раздела нет»: код готов, а строк нет. Держим это миграцией, а не разовой
командой, чтобы домены появлялись сами на каждом окружении.

Аккаунты никому не назначаем — их раскладывает владелец.
"""

from django.db import migrations

SEED = [
    ("product", "Product", "#6366f1"),
    ("ferma", "Ферма", "#16A34A"),
    ("reiz", "Reiz", "#EA580C"),
]


def create_domains(apps, schema_editor):
    Domain = apps.get_model("accounts", "Domain")
    for slug, name, color in SEED:
        Domain.objects.get_or_create(
            slug=slug, defaults={"name": name, "color": color, "is_active": True},
        )


def drop_domains(apps, schema_editor):
    """Откат сносит только пустые домены: с назначенными аккаунтами их удалять
    нельзя (FK стоит на PROTECT), да и не нужно — это была бы потеря работы."""
    Domain = apps.get_model("accounts", "Domain")
    for slug, _name, _color in SEED:
        d = Domain.objects.filter(slug=slug).first()
        if d and not d.accounts.exists():
            d.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0052_domain"),
    ]

    operations = [
        migrations.RunPython(create_domains, drop_domains),
    ]
