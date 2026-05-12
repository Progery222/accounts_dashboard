from django.contrib import admin

from .models import Account, AccountAudienceMembership, AudienceMember, GlobalVisibilityConfig, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "mirror_dashboard_id", "is_hidden", "updated_at")
    search_fields = ("name", "description")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "platform", "profile", "mirror_dashboard_id", "follower_count", "updated_at")
    list_filter = ("platform",)
    search_fields = ("username", "display_name", "bio")


@admin.register(AudienceMember)
class AudienceMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "platform", "follower_count", "updated_at")
    list_filter = ("platform",)
    search_fields = ("username", "display_name")


@admin.register(AccountAudienceMembership)
class AccountAudienceMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "member", "last_synced_at")
    autocomplete_fields = ("account", "member")


@admin.register(GlobalVisibilityConfig)
class GlobalVisibilityConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "hidden_platforms")
