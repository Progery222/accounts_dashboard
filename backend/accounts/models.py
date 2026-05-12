from django.db import models
from django.utils import timezone

from .constants import MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT


class Profile(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#6366f1")  # hex
    avatar_url = models.URLField(max_length=1024, blank=True)
    is_hidden = models.BooleanField(
        default=False,
        help_text="Скрыть профиль и его аккаунты на главном экране для всех пользователей.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RefreshScheduleConfig(models.Model):
    """Singleton (pk=1). Stores user-configured auto-refresh schedule."""
    enabled = models.BooleanField(default=False)
    mode = models.CharField(
        max_length=10,
        choices=[("interval", "Интервал"), ("times", "Время")],
        default="interval",
    )
    interval_hours = models.IntegerField(default=6)
    skip_recent_hours = models.IntegerField(default=0)
    auto_refresh_csv_report = models.BooleanField(
        default=False,
        help_text="После завершения автообновления сохранять CSV-отчёт для скачивания в интерфейсе.",
    )
    include_hidden_platform_accounts = models.BooleanField(
        default=False,
        help_text="В автообновлении учитывать аккаунты скрытых платформ.",
    )
    include_hidden_profile_accounts = models.BooleanField(
        default=False,
        help_text="В автообновлении учитывать аккаунты скрытых профилей.",
    )
    include_unavailable_accounts = models.BooleanField(
        default=False,
        help_text="В автообновлении учитывать недоступные аккаунты.",
    )
    account_delta_period_days = models.PositiveSmallIntegerField(
        default=1,
        help_text="За сколько календарных дней назад брать опорный снимок для дельт в списке аккаунтов (1, 7 или 30).",
    )
    max_audience_followers_per_account = models.PositiveSmallIntegerField(
        default=MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT,
        help_text=(
            "Не более стольких подписчиков на один отслеживаемый аккаунт "
            f"(не больше {MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT}; съём аудитории TikTok/Instagram)."
        ),
    )
    times = models.JSONField(default=list)  # e.g. ["09:00", "21:00"]

    class Meta:
        verbose_name = "Расписание обновлений"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "skip_recent_hours": 0,
                "auto_refresh_csv_report": False,
                "include_hidden_platform_accounts": False,
                "include_hidden_profile_accounts": False,
                "include_unavailable_accounts": False,
                "account_delta_period_days": 1,
                "max_audience_followers_per_account": MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT,
                "times": [],
            },
        )
        return obj


class GlobalVisibilityConfig(models.Model):
    """Singleton (pk=1). Stores globally hidden platforms."""

    hidden_platforms = models.JSONField(default=list)

    class Meta:
        verbose_name = "Глобальная видимость платформ"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"hidden_platforms": []},
        )
        return obj


class AutoRefreshState(models.Model):
    """Singleton (pk=1). Stores current/last auto-refresh execution state."""

    is_running = models.BooleanField(default=False)
    source = models.CharField(max_length=32, blank=True, default="scheduler")
    cancel_requested = models.BooleanField(default=False)
    total_accounts = models.IntegerField(default=0)
    processed_accounts = models.IntegerField(default=0)
    success_accounts = models.IntegerField(default=0)
    failed_accounts = models.IntegerField(default=0)
    current_account = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    last_report_csv = models.TextField(blank=True, default="")
    last_report_generated_at = models.DateTimeField(null=True, blank=True)
    # Прогресс текущего/последнего автообновления: { "worker_count": int, "items": [...] }
    run_detail = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние автообновления"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "is_running": False,
                "source": "scheduler",
                "cancel_requested": False,
                "total_accounts": 0,
                "processed_accounts": 0,
                "success_accounts": 0,
                "failed_accounts": 0,
                "current_account": "",
                "started_at": None,
                "finished_at": None,
                "last_error": "",
                "last_report_csv": "",
                "last_report_generated_at": None,
                "run_detail": {},
            },
        )
        return obj


class RefreshAllState(models.Model):
    """Singleton (pk=1). Состояние ручного «собрать всех» (POST /api/accounts/refresh_all/)."""

    is_running = models.BooleanField(default=False)
    cancel_requested = models.BooleanField(default=False)
    total_accounts = models.IntegerField(default=0)
    processed_accounts = models.IntegerField(default=0)
    success_accounts = models.IntegerField(default=0)
    failed_accounts = models.IntegerField(default=0)
    current_account = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    last_report_csv = models.TextField(blank=True, default="")
    last_report_generated_at = models.DateTimeField(null=True, blank=True)
    run_detail = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние сбора всех аккаунтов"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "is_running": False,
                "cancel_requested": False,
                "total_accounts": 0,
                "processed_accounts": 0,
                "success_accounts": 0,
                "failed_accounts": 0,
                "current_account": "",
                "started_at": None,
                "finished_at": None,
                "last_error": "",
                "last_report_csv": "",
                "last_report_generated_at": None,
                "run_detail": {},
            },
        )
        return obj


class Platform(models.TextChoices):
    TIKTOK    = "tiktok",    "TikTok"
    INSTAGRAM = "instagram", "Instagram"
    YOUTUBE   = "youtube",   "YouTube"
    TELEGRAM  = "telegram",  "Telegram"
    X         = "x",         "X (Twitter)"
    THREADS   = "threads",   "Threads"
    FACEBOOK  = "facebook",  "Facebook"
    RUMBLE    = "rumble",    "Rumble"
    REDDIT    = "reddit",    "Reddit"


class Account(models.Model):
    username = models.CharField(max_length=255)
    platform = models.CharField(max_length=20, choices=Platform.choices)
    profile = models.ForeignKey(
        Profile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="accounts",
    )
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=1024, blank=True)
    bio = models.TextField(blank=True)
    follower_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    view_count = models.BigIntegerField(default=0)
    post_count = models.IntegerField(default=0)
    profile_unavailable = models.BooleanField(
        default=False,
        verbose_name="Профиль на площадке недоступен",
        help_text="Последнее обновление: профиль удалён или недоступен на площадке.",
    )
    audience_last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Последний успешный съём списка подписчиков (TikTok/Instagram).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("username", "platform")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform}/@{self.username}"

    def take_snapshot_if_needed(self):
        today = timezone.localdate()
        snap, created = AccountSnapshot.objects.get_or_create(
            account=self,
            date=today,
            defaults={
                "follower_count": self.follower_count,
                "like_count": self.like_count,
                "view_count": self.view_count,
                "post_count": self.post_count,
            },
        )
        return snap, created


class AccountSnapshot(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    follower_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    view_count = models.BigIntegerField(default=0)
    post_count = models.IntegerField(default=0)

    class Meta:
        unique_together = [("account", "date")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.account} @ {self.date}"


class Post(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="posts")
    external_id = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    thumbnail_url = models.URLField(max_length=2048, blank=True)
    post_url = models.URLField(max_length=2048, blank=True)
    view_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    comment_count = models.BigIntegerField(default=0)
    share_count = models.BigIntegerField(default=0)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("account", "external_id")]
        ordering = ["-view_count"]

    def __str__(self):
        return f"{self.account}/{self.external_id}"

    def take_snapshot_if_needed(self):
        today = timezone.localdate()
        PostSnapshot.objects.get_or_create(
            post=self,
            date=today,
            defaults={
                "view_count": self.view_count,
                "like_count": self.like_count,
                "comment_count": self.comment_count,
            },
        )


class PostSnapshot(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    view_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    comment_count = models.BigIntegerField(default=0)

    class Meta:
        unique_together = [("post", "date")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.post} @ {self.date}"


class AutoRefreshPoint(models.Model):
    measured_at = models.DateTimeField(auto_now_add=True, db_index=True)
    local_date = models.DateField(db_index=True)
    source = models.CharField(max_length=32, default="scheduler")
    slot_label = models.CharField(max_length=32, blank=True, default="")
    view_count_total = models.BigIntegerField(default=0)
    view_delta_from_prev_point = models.BigIntegerField(default=0)
    view_delta_from_day_start = models.BigIntegerField(default=0)
    platform_deltas = models.JSONField(
        default=dict,
        help_text="Дельты просмотров по платформам для этого прогона, например {'tiktok': 1200}.",
    )

    class Meta:
        ordering = ["measured_at"]
        indexes = [
            models.Index(fields=["local_date", "measured_at"]),
        ]


class AudienceMember(models.Model):
    """Подписчик отслеживаемого аккаунта (внешний профиль на площадке)."""

    platform = models.CharField(max_length=20, choices=Platform.choices, db_index=True)
    username = models.CharField(max_length=255, db_index=True)
    external_id = models.CharField(max_length=160, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=2048, blank=True)
    bio = models.TextField(blank=True)
    is_private = models.BooleanField(default=False)
    follower_count = models.BigIntegerField(default=0)
    following_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    profile_language = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Язык/локаль профиля с площадки (если отдаётся), например en, ru.",
    )
    timezone_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Часовой пояс с площадки (если отдаётся), например Europe/Moscow.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "username"],
                name="audience_member_unique_platform_username",
            ),
        ]
        ordering = ["username"]

    def __str__(self):
        return f"{self.platform}/@{self.username}"


class AccountAudienceMembership(models.Model):
    """Связь «наш Account» ↔ подписчик."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="audience_memberships")
    member = models.ForeignKey(AudienceMember, on_delete=models.CASCADE, related_name="memberships")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("account", "member")]
        ordering = ["-last_synced_at"]


class AudienceMemberPost(models.Model):
    """Посты профиля подписчика."""

    member = models.ForeignKey(AudienceMember, on_delete=models.CASCADE, related_name="audience_posts")
    external_id = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    thumbnail_url = models.URLField(max_length=2048, blank=True)
    post_url = models.URLField(max_length=2048, blank=True)
    view_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    comment_count = models.BigIntegerField(default=0)
    share_count = models.BigIntegerField(default=0)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("member", "external_id")]
        ordering = ["-posted_at", "-id"]
