from django.contrib import admin
from .models import (
    Account,
    Domain,
    Post,
    AccountSnapshot,
    PostSnapshot,
    Profile,
    Owner,
    AccountGroup,
    Country,
    ScrapeBackendConfig,
    ApifyRefreshJob,
)


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "account_count", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Аккаунтов")
    def account_count(self, obj):
        return obj.accounts.count()


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "domain", "color", "account_count", "created_at"]
    list_filter = ["domain"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Аккаунтов")
    def account_count(self, obj):
        return obj.accounts.count()


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ["name", "domain", "color", "account_count", "created_at"]
    list_filter = ["domain"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Аккаунтов")
    def account_count(self, obj):
        return obj.accounts.count()


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "domain", "color", "account_count", "created_at"]
    list_filter = ["domain"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Аккаунтов")
    def account_count(self, obj):
        return obj.accounts.count()


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "domain", "color", "account_count", "created_at"]
    list_filter = ["domain"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Аккаунтов")
    def account_count(self, obj):
        return obj.accounts.count()


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = [
        "username",
        "domain",
        "platform",
        "profile",
        "owner",
        "display_name",
        "avatar_missing",
        "is_archived",
        "is_banned",
        "follower_count",
        "post_count",
        "updated_at",
    ]
    # Домен первым: раскладывать аккаунты по доменам удобнее всего отсюда —
    # отфильтровать «Домен: —» и назначить пачкой.
    list_filter = ["domain", "platform", "avatar_missing", "is_archived", "is_banned"]
    search_fields = ["username", "display_name"]
    readonly_fields = ["created_at", "updated_at", "avatar_file"]
    ordering = ["-created_at"]
    # Домен правится прямо в списке: отфильтровали «Домен: —», проставили
    # на странице, сохранили. Раскладывать 1200 аккаунтов по одному больно,
    # а своя страница действия ради этого не нужна.
    list_editable = ["domain"]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = [
        "external_id",
        "account",
        "thumbnail_missing",
        "description_short",
        "view_count",
        "like_count",
        "comment_count",
        "posted_at",
        "updated_at",
    ]
    list_filter = ["account__platform"]
    search_fields = ["external_id", "description", "account__username"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-updated_at"]
    raw_id_fields = ["account"]

    @admin.display(description="Описание")
    def description_short(self, obj):
        return obj.description[:60] + "…" if len(obj.description) > 60 else obj.description


@admin.register(AccountSnapshot)
class AccountSnapshotAdmin(admin.ModelAdmin):
    list_display = ["account", "date", "follower_count", "post_count"]
    list_filter = ["date", "account__platform"]
    search_fields = ["account__username"]
    ordering = ["-date"]


@admin.register(PostSnapshot)
class PostSnapshotAdmin(admin.ModelAdmin):
    list_display = ["post", "date", "view_count", "like_count", "comment_count"]
    list_filter = ["date"]
    ordering = ["-date"]


@admin.register(ScrapeBackendConfig)
class ScrapeBackendConfigAdmin(admin.ModelAdmin):
    list_display = ["facebook_backend", "tiktok_backend", "instagram_backend", "updated_at"]


@admin.register(ApifyRefreshJob)
class ApifyRefreshJobAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "platform",
        "username_snapshot",
        "status",
        "trigger",
        "apify_run_id",
        "started_at",
        "finished_at",
    ]
    list_filter = ["status", "platform", "trigger"]
    search_fields = ["username_snapshot", "apify_run_id"]
    raw_id_fields = ["account"]
    readonly_fields = ["created_at", "updated_at"]
