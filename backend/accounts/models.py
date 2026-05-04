from django.db import models
from django.utils import timezone


class Profile(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#6366f1")  # hex
    avatar_url = models.URLField(max_length=1024, blank=True)
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
    times = models.JSONField(default=list)  # e.g. ["09:00", "21:00"]

    class Meta:
        verbose_name = "Расписание обновлений"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"enabled": False, "mode": "interval", "interval_hours": 6, "times": []},
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("username", "platform")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform}/@{self.username}"

    def take_snapshot_if_needed(self):
        today = timezone.now().date()
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
        today = timezone.now().date()
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
