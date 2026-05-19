from django.db import migrations, models

SCRAPE_SHARD_COUNT = 3


def _even_shard(index: int, total: int, shard_count: int = SCRAPE_SHARD_COUNT) -> int:
    """Равномерно: при total=60 и shard_count=3 → по 20 на шард 0,1,2."""
    if total <= 0:
        return 0
    return min(shard_count - 1, (index * shard_count) // total)


def distribute_scrape_shards(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    by_platform: dict[str, list] = {}
    for acc in Account.objects.order_by("platform", "id").iterator():
        by_platform.setdefault(acc.platform, []).append(acc)

    to_update = []
    for _platform, accounts in by_platform.items():
        n = len(accounts)
        for index, acc in enumerate(accounts):
            acc.scrape_shard = _even_shard(index, n)
            to_update.append(acc)

    if to_update:
        Account.objects.bulk_update(to_update, ["scrape_shard"], batch_size=500)


def reverse_distribute(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    Account.objects.update(scrape_shard=0)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0033_post_missing_from_scrape_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="scrape_shard",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Линия браузера/IP (0–2, всего 3). Пока не используется воркерами.",
                verbose_name="Шард съёма",
            ),
        ),
        migrations.RunPython(distribute_scrape_shards, reverse_distribute),
    ]
