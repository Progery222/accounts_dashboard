from django.db import models
from django.utils import timezone

from .constants import MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT


class Profile(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=7, default="#6366f1")  # hex
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


class Owner(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=7, default="#6366f1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AccountGroup(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=7, default="#6366f1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Группа"
        verbose_name_plural = "Группы"

    def __str__(self):
        return self.name


class Country(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=7, default="#6366f1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Страна"
        verbose_name_plural = "Страны"

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
    refresh_warm_enabled = models.BooleanField(
        default=True,
        help_text="Прогрев Facebook при refresh_all, bulk и автообновлении.",
    )
    auto_refresh_csv_report = models.BooleanField(
        default=True,
        help_text="После завершения автообновления сохранять CSV-отчёт для скачивания в интерфейсе.",
    )
    auto_refresh_telegram_enabled = models.BooleanField(
        default=False,
        help_text="После успешного автообновления отправлять отчёт в Telegram.",
    )
    auto_refresh_telegram_chat_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Устаревшее: один chat ID; используйте auto_refresh_telegram_chat_ids.",
    )
    auto_refresh_telegram_chat_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Список chat ID получателей отчёта в Telegram.",
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
    auto_refresh_platforms = models.JSONField(
        default=list,
        blank=True,
        help_text="Пусто — все платформы; иначе только перечисленные id платформ.",
    )
    auto_refresh_profile_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Пусто — все профили; иначе id профилей и/или «none» (без профиля).",
    )
    auto_refresh_owner_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Пусто — все владельцы; иначе id владельцев и/или «none» (без владельца).",
    )
    auto_refresh_group_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Пусто — все группы; иначе id групп и/или «none» (без группы).",
    )
    auto_refresh_country_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Пусто — все страны; иначе id стран и/или «none» (без страны).",
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
                "refresh_warm_enabled": True,
                "auto_refresh_csv_report": True,
                "auto_refresh_telegram_enabled": False,
                "auto_refresh_telegram_chat_id": "",
                "auto_refresh_telegram_chat_ids": [],
                "include_hidden_platform_accounts": False,
                "include_hidden_profile_accounts": False,
                "include_unavailable_accounts": False,
                "auto_refresh_platforms": [],
                "auto_refresh_profile_ids": [],
                "auto_refresh_owner_ids": [],
                "auto_refresh_group_ids": [],
                "auto_refresh_country_ids": [],
                "account_delta_period_days": 1,
                "max_audience_followers_per_account": MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT,
                "times": ["06:00", "12:00", "18:00", "00:00"],
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
    last_telegram_error = models.TextField(blank=True, default="")
    last_telegram_sent_at = models.DateTimeField(null=True, blank=True)
    # ID аккаунтов со статусом «ошибка» в последнем завершённом автообновлении (по расписанию / «запустить сейчас»).
    last_auto_refresh_error_account_ids = models.JSONField(blank=True, default=list)
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
                "last_auto_refresh_error_account_ids": [],
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


class ScrapeBackendChoice(models.TextChoices):
    PLAYWRIGHT = "playwright", "Playwright"
    APIFY = "apify", "Apify"


class ScrapeBackendConfig(models.Model):
    """Singleton (pk=1). Backend сбора данных по платформе."""

    facebook_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    tiktok_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    instagram_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    youtube_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    reddit_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    rumble_backend = models.CharField(
        max_length=16,
        choices=ScrapeBackendChoice.choices,
        default=ScrapeBackendChoice.PLAYWRIGHT,
    )
    facebook_fallback_enabled = models.BooleanField(
        default=False,
        help_text="Facebook: Playwright→Apify при rate limit, антиботе или недоступном профиле в одном прогоне.",
    )
    tiktok_fallback_enabled = models.BooleanField(
        default=False,
        help_text="TikTok: Playwright→Apify при капче или 3 новых ошибках в одном прогоне.",
    )
    instagram_fallback_enabled = models.BooleanField(default=False)
    youtube_fallback_enabled = models.BooleanField(default=False)
    reddit_fallback_enabled = models.BooleanField(default=False)
    rumble_fallback_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Способ сбора данных"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "facebook_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "tiktok_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "instagram_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "youtube_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "reddit_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "rumble_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "facebook_fallback_enabled": False,
                "tiktok_fallback_enabled": False,
                "instagram_fallback_enabled": False,
                "youtube_fallback_enabled": False,
                "reddit_fallback_enabled": False,
                "rumble_fallback_enabled": False,
            },
        )
        return obj

    def get_backend(self, platform: str) -> str:
        key = str(platform or "").strip().lower()
        if key == "facebook":
            return self.facebook_backend
        if key == "tiktok":
            return self.tiktok_backend
        if key == "instagram":
            return self.instagram_backend
        if key == "youtube":
            return self.youtube_backend
        if key == "reddit":
            return self.reddit_backend
        if key == "rumble":
            return self.rumble_backend
        return ScrapeBackendChoice.PLAYWRIGHT


class ApifyRefreshJobStatus(models.TextChoices):
    QUEUED = "queued", "В очереди"
    STARTING = "starting", "Запуск"
    RUNNING = "running", "Выполняется"
    SUCCEEDED = "succeeded", "Успех"
    FAILED = "failed", "Ошибка"
    ABORTED = "aborted", "Отменён"


class ApifyRefreshJobTrigger(models.TextChoices):
    MANUAL = "manual", "Ручной"
    REFRESH_ALL = "refresh_all", "Сбор всех"
    BULK = "bulk", "Массовый"
    SCHEDULER = "scheduler", "Расписание"


class ApifyRefreshJob(models.Model):
    """История и состояние асинхронного refresh через Apify."""

    account = models.ForeignKey(
        "Account",
        on_delete=models.CASCADE,
        related_name="apify_refresh_jobs",
    )
    platform = models.CharField(max_length=32)
    username_snapshot = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=ApifyRefreshJobStatus.choices,
        default=ApifyRefreshJobStatus.QUEUED,
        db_index=True,
    )
    apify_run_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    apify_actor_id = models.CharField(max_length=255, blank=True, default="")
    apify_dataset_id = models.CharField(max_length=64, blank=True, default="")
    apify_stages = models.JSONField(blank=True, default=list)
    trigger = models.CharField(
        max_length=32,
        choices=ApifyRefreshJobTrigger.choices,
        default=ApifyRefreshJobTrigger.MANUAL,
    )
    parent_batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    run_detail_extra = models.JSONField(blank=True, default=dict)
    normalized_preview = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["account", "-started_at"]),
            models.Index(fields=["status"]),
        ]
        verbose_name = "Задача Apify refresh"

    def __str__(self):
        return f"ApifyJob#{self.pk} {self.platform}/@{self.username_snapshot} [{self.status}]"


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
    owner = models.ForeignKey(
        Owner, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="accounts",
    )
    group = models.ForeignKey(
        AccountGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="accounts",
    )
    country = models.ForeignKey(
        Country, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="accounts",
    )
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(
        max_length=1024,
        blank=True,
        help_text="CDN-URL с площадки; fallback, если локальный файл ещё не скачан.",
    )
    avatar_file = models.FileField(
        upload_to="accounts/avatars/%Y/%m/",
        blank=True,
        max_length=512,
        help_text="Локальная копия аватара (скачивается один раз при refresh).",
    )
    avatar_missing = models.BooleanField(
        default=False,
        help_text="На площадке нет аватара; не пытаться скачивать при автообновлении.",
    )
    bio = models.TextField(blank=True)
    follower_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    view_count = models.BigIntegerField(default=0)
    post_count = models.IntegerField(default=0)
    link_click_count = models.BigIntegerField(
        default=0,
        verbose_name="Переходы по ссылке из bio",
        help_text="Сумма кликов по коротким ссылкам Links с label = URL профиля; обновляется при refresh.",
    )
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
                "link_click_count": self.link_click_count,
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
    link_click_count = models.BigIntegerField(default=0)

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
    thumbnail_url = models.URLField(
        max_length=2048,
        blank=True,
        help_text="CDN-URL превью; fallback, если локальный файл ещё не скачан.",
    )
    thumbnail_file = models.FileField(
        upload_to="posts/thumbnails/%Y/%m/",
        blank=True,
        max_length=512,
        help_text="Локальная копия превью (скачивается один раз при sync постов).",
    )
    thumbnail_missing = models.BooleanField(
        default=False,
        help_text="У поста нет превью на площадке; не пытаться скачивать при обновлении.",
    )
    post_url = models.URLField(max_length=2048, blank=True)
    view_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    comment_count = models.BigIntegerField(default=0)
    share_count = models.BigIntegerField(default=0)
    posted_at = models.DateTimeField(null=True, blank=True)
    # Не попал в последний авторитетный список со скрапа — не удаляем автоматически.
    missing_from_scrape_at = models.DateTimeField(null=True, blank=True, db_index=True)
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
    follower_network = models.JSONField(
        default=list,
        blank=True,
        help_text="Срез подписчиков этого подписчика (TikTok), до 100 записей с полями username, bio, счётчики.",
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
