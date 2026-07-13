from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
import re
from .models import Account, Platform, Post, Profile, Owner, AccountGroup, Country, AudienceMember, AudienceMemberPost


class ProfileSerializer(serializers.ModelSerializer):
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["id", "name", "color", "is_hidden", "account_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_account_count(self, obj):
        prefetched = getattr(obj, "account_count", None)
        if prefetched is not None:
            return prefetched
        return obj.accounts.count()


class OwnerSerializer(serializers.ModelSerializer):
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = Owner
        fields = ["id", "name", "color", "account_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_account_count(self, obj):
        prefetched = getattr(obj, "account_count", None)
        if prefetched is not None:
            return prefetched
        return obj.accounts.count()


class AccountGroupSerializer(serializers.ModelSerializer):
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = AccountGroup
        fields = ["id", "name", "color", "account_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_account_count(self, obj):
        prefetched = getattr(obj, "account_count", None)
        if prefetched is not None:
            return prefetched
        return obj.accounts.count()


class CountrySerializer(serializers.ModelSerializer):
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = Country
        fields = ["id", "name", "color", "account_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_account_count(self, obj):
        prefetched = getattr(obj, "account_count", None)
        if prefetched is not None:
            return prefetched
        return obj.accounts.count()


class AccountSerializer(serializers.ModelSerializer):
    platform_label = serializers.CharField(source="get_platform_display", read_only=True)
    profile_id = serializers.PrimaryKeyRelatedField(
        queryset=Profile.objects.all(), source="profile", allow_null=True, required=False,
    )
    profile_name = serializers.CharField(source="profile.name", read_only=True, allow_null=True)
    profile_color = serializers.CharField(source="profile.color", read_only=True, allow_null=True)
    owner_id = serializers.PrimaryKeyRelatedField(
        queryset=Owner.objects.all(), source="owner", allow_null=True, required=False,
    )
    owner_name = serializers.CharField(source="owner.name", read_only=True, allow_null=True)
    owner_color = serializers.CharField(source="owner.color", read_only=True, allow_null=True)
    group_id = serializers.PrimaryKeyRelatedField(
        queryset=AccountGroup.objects.all(), source="group", allow_null=True, required=False,
    )
    group_name = serializers.CharField(source="group.name", read_only=True, allow_null=True)
    group_color = serializers.CharField(source="group.color", read_only=True, allow_null=True)
    country_id = serializers.PrimaryKeyRelatedField(
        queryset=Country.objects.all(), source="country", allow_null=True, required=False,
    )
    country_name = serializers.CharField(source="country.name", read_only=True, allow_null=True)
    country_color = serializers.CharField(source="country.color", read_only=True, allow_null=True)
    follower_delta = serializers.SerializerMethodField()
    like_delta = serializers.SerializerMethodField()
    view_delta = serializers.SerializerMethodField()
    post_delta = serializers.SerializerMethodField()
    link_click_delta = serializers.SerializerMethodField()
    is_platform_hidden = serializers.SerializerMethodField()
    is_profile_hidden = serializers.SerializerMethodField()
    audience_members_count = serializers.SerializerMethodField()
    refresh_pipeline = serializers.SerializerMethodField()
    refresh_pipeline_label = serializers.SerializerMethodField()
    apify_job_id = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id", "username", "platform", "platform_label",
            "profile_id", "profile_name", "profile_color",
            "owner_id", "owner_name", "owner_color",
            "group_id", "group_name", "group_color",
            "country_id", "country_name", "country_color",
            "display_name", "avatar_url", "bio",
            "follower_count", "like_count", "view_count", "post_count",
            "link_click_count",
            "profile_unavailable",
            "audience_last_synced_at",
            "audience_members_count",
            "follower_delta", "like_delta", "view_delta", "post_delta", "link_click_delta",
            "is_platform_hidden", "is_profile_hidden",
            "refresh_pipeline", "refresh_pipeline_label", "apify_job_id",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "audience_last_synced_at",
        ]

    def validate_username(self, value):
        value = str(value).strip().lstrip("@")
        return value

    def run_validators(self, value):
        """Существующий аккаунт при импорте — upsert в AccountViewSet.create, не unique-error."""
        if self.instance is None:
            uname = value.get("username")
            plat = value.get("platform")
            if (
                uname is not None
                and plat is not None
                and Account.objects.filter(username=uname, platform=plat).exists()
            ):
                for validator in self.validators:
                    if isinstance(validator, UniqueTogetherValidator):
                        fields = getattr(validator, "fields", ())
                        if fields == ("username", "platform"):
                            continue
                    validator(value, self)
                return
        super().run_validators(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        platform = attrs.get("platform")
        if platform is None and self.instance is not None:
            platform = self.instance.platform
        username = attrs.get("username")
        if username is not None and platform == Platform.RUMBLE:
            s = str(username).strip().lstrip("@")
            s = re.sub(r"^https?://(?:www\.)?rumble\.com/", "", s, flags=re.I)
            s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
            parts = [p for p in s.split("/") if p]
            if parts and parts[0].lower() in {"c", "user"}:
                parts = parts[1:]
            if parts and parts[-1].lower() == "about":
                parts = parts[:-1]
            if parts:
                attrs["username"] = parts[0]
        if username is not None and platform == Platform.REDDIT:
            s = str(username).strip()
            s = re.sub(r"^https?://(?:www\.)?reddit\.com/", "", s, flags=re.I)
            s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
            parts = [p for p in s.split("/") if p]
            # Expected canonical storage: subreddit name only, e.g. "OpenAI".
            if parts and parts[0].lower() == "r":
                parts = parts[1:]
            if parts:
                attrs["username"] = parts[0]
        if username is not None and platform == Platform.FACEBOOK:
            from platforms.facebook.profile_url import canonical_facebook_username_for_storage

            try:
                attrs["username"] = canonical_facebook_username_for_storage(str(username).strip())
            except ValueError as exc:
                raise serializers.ValidationError({"username": str(exc)}) from exc
        return attrs

    def _baseline_snap(self, obj):
        snaps = getattr(obj, "_yesterday_snaps", None)
        if snaps is not None:
            return snaps[0] if snaps else None
        period = int(self.context.get("account_delta_period_days", 1) or 1)
        if period not in (1, 7, 30):
            period = 1
        today = timezone.localdate()
        cutoff = today - timedelta(days=period)
        return obj.snapshots.filter(date__lte=cutoff).order_by("-date").first()

    def get_follower_delta(self, obj):
        annotated = getattr(obj, "_follower_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return obj.follower_count - snap.follower_count
        # Нет снимка не старше cutoff — baseline считаем нулевым.
        return obj.follower_count

    def get_like_delta(self, obj):
        # Facebook: сумма лайков по постам часто 0 при нестабильном парсе; отрицательная дельта
        # против вчерашнего снимка вводит в заблуждение — не отдаём дельту, пока лайков нет.
        if obj.platform == Platform.FACEBOOK and int(obj.like_count or 0) == 0:
            return None
        annotated = getattr(obj, "_like_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return obj.like_count - snap.like_count
        return obj.like_count

    def get_view_delta(self, obj):
        annotated = getattr(obj, "_view_delta", None)
        if annotated is not None:
            raw = annotated
        else:
            snap = self._baseline_snap(obj)
            raw = (
                int(obj.view_count or 0) - int(snap.view_count or 0)
                if snap
                else int(obj.view_count or 0)
            )
        if raw is not None and obj.platform in (Platform.INSTAGRAM, Platform.THREADS):
            return max(0, int(raw))
        return raw

    def get_post_delta(self, obj):
        annotated = getattr(obj, "_post_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return obj.post_count - snap.post_count
        return obj.post_count

    def get_link_click_delta(self, obj):
        annotated = getattr(obj, "_link_click_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return int(obj.link_click_count or 0) - int(snap.link_click_count or 0)
        return int(obj.link_click_count or 0)

    def get_is_platform_hidden(self, obj):
        hidden = self.context.get("hidden_platforms") or set()
        return obj.platform in hidden

    def get_is_profile_hidden(self, obj):
        return bool(getattr(obj.profile, "is_hidden", False))

    def _active_apify_job(self, obj):
        cache = getattr(self, "_apify_jobs_cache", None)
        if cache is None:
            from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus

            ids = []
            if isinstance(self.parent, serializers.ListSerializer):
                ids = [o.pk for o in self.parent.instance]
            elif obj.pk:
                ids = [obj.pk]
            cache = {}
            if ids:
                qs = ApifyRefreshJob.objects.filter(
                    account_id__in=ids,
                    status__in=[
                        ApifyRefreshJobStatus.QUEUED,
                        ApifyRefreshJobStatus.STARTING,
                        ApifyRefreshJobStatus.RUNNING,
                    ],
                ).order_by("-id")
                for job in qs:
                    if job.account_id not in cache:
                        cache[job.account_id] = job
            self._apify_jobs_cache = cache
        return cache.get(obj.pk)

    def get_refresh_pipeline(self, obj):
        job = self._active_apify_job(obj)
        return "apify" if job else None

    def get_refresh_pipeline_label(self, obj):
        job = self._active_apify_job(obj)
        if not job:
            return None
        if job.status == "queued":
            return "В очереди Apify"
        return "Сбор Apify…"

    def get_apify_job_id(self, obj):
        job = self._active_apify_job(obj)
        return job.pk if job else None

    def get_audience_members_count(self, obj):
        ann = getattr(obj, "audience_members_count", None)
        if ann is not None:
            return int(ann)
        if hasattr(obj, "audience_memberships"):
            return obj.audience_memberships.count()
        return 0


class PostSerializer(serializers.ModelSerializer):
    view_delta = serializers.SerializerMethodField()
    like_delta = serializers.SerializerMethodField()
    comment_delta = serializers.SerializerMethodField()
    scrape_not_found = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id", "external_id", "description", "hashtags", "thumbnail_url", "post_url",
            "view_count", "like_count", "comment_count", "share_count",
            "view_delta", "like_delta", "comment_delta",
            "posted_at", "updated_at", "missing_from_scrape_at", "scrape_not_found",
            "thumbnail_missing",
        ]
        read_only_fields = [
            "id",
            "updated_at",
            "missing_from_scrape_at",
            "scrape_not_found",
            "thumbnail_missing",
        ]

    def get_scrape_not_found(self, obj) -> bool:
        return obj.missing_from_scrape_at is not None

    def _baseline_snap(self, obj):
        snaps = getattr(obj, "_yesterday_snaps", None)
        if snaps is not None:
            return snaps[0] if snaps else None
        period = int(self.context.get("account_delta_period_days", 1) or 1)
        if period not in (1, 7, 30):
            period = 1
        today = timezone.localdate()
        cutoff = today - timedelta(days=period)
        return obj.snapshots.filter(date__lte=cutoff).order_by("-date").first()

    def get_view_delta(self, obj):
        annotated = getattr(obj, "_view_delta", None)
        if annotated is not None:
            raw = annotated
        else:
            snap = self._baseline_snap(obj)
            raw = (
                int(obj.view_count or 0) - int(snap.view_count or 0)
                if snap
                else int(obj.view_count or 0)
            )
        plat = self.context.get("parent_account_platform") or getattr(
            getattr(obj, "account", None), "platform", None
        )
        if raw is not None and plat in (Platform.INSTAGRAM, Platform.THREADS):
            return max(0, int(raw))
        return raw

    def get_like_delta(self, obj):
        annotated = getattr(obj, "_like_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return obj.like_count - snap.like_count
        return obj.like_count

    def get_comment_delta(self, obj):
        annotated = getattr(obj, "_comment_delta", None)
        if annotated is not None:
            return annotated
        snap = self._baseline_snap(obj)
        if snap:
            return obj.comment_count - snap.comment_count
        return obj.comment_count


class AudienceMemberPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudienceMemberPost
        fields = [
            "id",
            "external_id",
            "description",
            "thumbnail_url",
            "post_url",
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "posted_at",
        ]
        read_only_fields = fields


class AudienceMemberListSerializer(serializers.ModelSerializer):
    follows_tracked_accounts_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AudienceMember
        fields = [
            "id",
            "username",
            "external_id",
            "display_name",
            "avatar_url",
            "bio",
            "is_private",
            "follower_count",
            "following_count",
            "like_count",
            "profile_language",
            "timezone_name",
            "follower_network",
            "follows_tracked_accounts_count",
        ]
        read_only_fields = fields


class AudienceMemberDetailSerializer(serializers.ModelSerializer):
    follows_tracked_accounts_count = serializers.IntegerField(read_only=True)
    posts = AudienceMemberPostSerializer(many=True, read_only=True)

    class Meta:
        model = AudienceMember
        fields = AudienceMemberListSerializer.Meta.fields + ["posts"]
        read_only_fields = AudienceMemberListSerializer.Meta.fields + ["posts"]


class PlatformSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
