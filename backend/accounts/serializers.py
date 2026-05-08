from rest_framework import serializers
from django.utils import timezone
import re
from .models import Account, Platform, Post, Profile


class ProfileSerializer(serializers.ModelSerializer):
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["id", "name", "description", "color", "avatar_url", "is_hidden", "account_count", "created_at", "updated_at"]
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
    follower_delta = serializers.SerializerMethodField()
    like_delta = serializers.SerializerMethodField()
    view_delta = serializers.SerializerMethodField()
    post_delta = serializers.SerializerMethodField()
    is_platform_hidden = serializers.SerializerMethodField()
    is_profile_hidden = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id", "username", "platform", "platform_label",
            "profile_id", "profile_name", "profile_color",
            "display_name", "avatar_url", "bio",
            "follower_count", "like_count", "view_count", "post_count",
            "profile_unavailable",
            "follower_delta", "like_delta", "view_delta", "post_delta",
            "is_platform_hidden", "is_profile_hidden",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "profile_unavailable"]

    def validate_username(self, value):
        value = str(value).strip().lstrip("@")
        return value

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
        return attrs

    def _yesterday_snap(self, obj):
        snaps = getattr(obj, "_yesterday_snaps", None)
        if snaps is not None:
            return snaps[0] if snaps else None
        today = timezone.now().date()
        return obj.snapshots.filter(date__lt=today).order_by("-date").first()

    def get_follower_delta(self, obj):
        annotated = getattr(obj, "_follower_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.follower_count - snap.follower_count if snap else None

    def get_like_delta(self, obj):
        annotated = getattr(obj, "_like_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.like_count - snap.like_count if snap else None

    def get_view_delta(self, obj):
        annotated = getattr(obj, "_view_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.view_count - snap.view_count if snap else None

    def get_post_delta(self, obj):
        annotated = getattr(obj, "_post_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.post_count - snap.post_count if snap else None

    def get_is_platform_hidden(self, obj):
        hidden = self.context.get("hidden_platforms") or set()
        return obj.platform in hidden

    def get_is_profile_hidden(self, obj):
        return bool(getattr(obj.profile, "is_hidden", False))


class PostSerializer(serializers.ModelSerializer):
    view_delta = serializers.SerializerMethodField()
    like_delta = serializers.SerializerMethodField()
    comment_delta = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id", "external_id", "description", "hashtags", "thumbnail_url", "post_url",
            "view_count", "like_count", "comment_count", "share_count",
            "view_delta", "like_delta", "comment_delta",
            "posted_at", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def _yesterday_snap(self, obj):
        snaps = getattr(obj, "_yesterday_snaps", None)
        if snaps is not None:
            return snaps[0] if snaps else None
        today = timezone.now().date()
        return obj.snapshots.filter(date__lt=today).order_by("-date").first()

    def get_view_delta(self, obj):
        annotated = getattr(obj, "_view_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.view_count - snap.view_count if snap else None

    def get_like_delta(self, obj):
        annotated = getattr(obj, "_like_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.like_count - snap.like_count if snap else None

    def get_comment_delta(self, obj):
        annotated = getattr(obj, "_comment_delta", None)
        if annotated is not None:
            return annotated
        snap = self._yesterday_snap(obj)
        return obj.comment_count - snap.comment_count if snap else None


class PlatformSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
