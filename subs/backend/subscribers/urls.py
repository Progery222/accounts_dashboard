from django.urls import path

from . import views

urlpatterns = [
    path("profiles/", views.profiles_list, name="subscribers-profiles"),
    path("sync/dashboard/", views.sync_dashboard, name="subscribers-sync-dashboard"),
    path("sync/audience/stop/", views.sync_audience_stop, name="subscribers-sync-audience-stop"),
    path("sync/account/<int:pk>/audience/", views.sync_account_audience, name="subscribers-sync-account-audience"),
    path("members/export/last/refresh/", views.members_export_last_refresh, name="subscribers-members-export-last-refresh"),
    path("members/export/last/preview/", views.members_export_last_preview, name="subscribers-members-export-last-preview"),
    path("members/presumed-stats/", views.members_presumed_stats, name="subscribers-members-presumed-stats"),
    path(
        "members/export/last/presumed-stats/",
        views.members_export_last_presumed_stats,
        name="subscribers-members-export-last-presumed-stats",
    ),
    path("members/export/last.csv", views.members_export_last_csv, name="subscribers-members-export-last-csv"),
    path("members/export.csv", views.members_export_csv, name="subscribers-members-export-csv"),
    path("members/<int:pk>/", views.audience_member_retrieve_destroy, name="subscribers-member-detail-delete"),
    path("members/", views.members_list, name="subscribers-members"),
    path("", views.overview, name="subscribers-overview"),
]
