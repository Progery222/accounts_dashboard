"""
Отдельная БД subs: свои таблицы. Поле mirror_dashboard_id связывает сущности с id в API дашборда (синхронизация).
"""

from django.db import models


class Platform(models.TextChoices):
    TIKTOK = "tiktok", "TikTok"
    INSTAGRAM = "instagram", "Instagram"
    YOUTUBE = "youtube", "YouTube"
    TELEGRAM = "telegram", "Telegram"
    X = "x", "X (Twitter)"
    THREADS = "threads", "Threads"
    FACEBOOK = "facebook", "Facebook"
    RUMBLE = "rumble", "Rumble"
    REDDIT = "reddit", "Reddit"


# Площадки раздела «Подписчики» в subs: синхронизация с дашборда и API-фильтры.
SUBS_SUBSCRIBER_PLATFORMS = (
    Platform.TIKTOK,
    Platform.INSTAGRAM,
    Platform.X,
    Platform.THREADS,
    Platform.FACEBOOK,
)
SUBS_SUBSCRIBER_PLATFORM_VALUES = frozenset(p.value for p in SUBS_SUBSCRIBER_PLATFORMS)


class Profile(models.Model):
    """Профиль в subs (может быть заполнен синхронизацией с дашборда)."""

    mirror_dashboard_id = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#6366f1")
    avatar_url = models.URLField(max_length=1024, blank=True)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GlobalVisibilityConfig(models.Model):
    hidden_platforms = models.JSONField(default=list)

    class Meta:
        verbose_name = "Глобальная видимость платформ (subs)"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"hidden_platforms": []})
        return obj


class Account(models.Model):
    mirror_dashboard_id = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True)
    username = models.CharField(max_length=255)
    platform = models.CharField(max_length=20, choices=Platform.choices)
    profile = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts",
    )
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=1024, blank=True)
    bio = models.TextField(blank=True)
    follower_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    view_count = models.BigIntegerField(default=0)
    post_count = models.IntegerField(default=0)
    profile_unavailable = models.BooleanField(default=False)
    audience_last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("username", "platform")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform}/@{self.username}"


class AudienceMember(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "username"],
                name="subs_audience_member_unique_platform_username",
            ),
        ]
        ordering = ["username"]

    def __str__(self):
        return f"{self.platform}/@{self.username}"


class AccountAudienceMembership(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="audience_memberships")
    member = models.ForeignKey(AudienceMember, on_delete=models.CASCADE, related_name="memberships")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("account", "member")]
        ordering = ["-last_synced_at"]
