from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_alter_account_platform_add_reddit"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutoRefreshPoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("measured_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("local_date", models.DateField(db_index=True)),
                ("source", models.CharField(default="scheduler", max_length=32)),
                ("slot_label", models.CharField(blank=True, default="", max_length=32)),
                ("view_count_total", models.BigIntegerField(default=0)),
                ("view_delta_from_prev_point", models.BigIntegerField(default=0)),
                ("view_delta_from_day_start", models.BigIntegerField(default=0)),
            ],
            options={
                "ordering": ["measured_at"],
            },
        ),
        migrations.AddIndex(
            model_name="autorefreshpoint",
            index=models.Index(fields=["local_date", "measured_at"], name="accounts_aut_local_d_229762_idx"),
        ),
    ]
