"""Внешний API v1: стабильный контракт под Bearer-ключ."""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.api_auth import BearerApiKeyAuthentication, RequireActionScopes, RequireScopes
from accounts.models import ApifyRefreshJob
from accounts.views import AccountViewSet, compute_summary, domain_list, views_anchors


class ExternalAccountViewSet(AccountViewSet):
    """Подмножество AccountViewSet для интеграций."""

    authentication_classes = [BearerApiKeyAuthentication]
    permission_classes = [RequireActionScopes]
    http_method_names = ["get", "post", "patch", "head", "options"]

    action_scopes = {
        "list": ("read",),
        "retrieve": ("read",),
        "posts": ("read",),
        "create": ("write",),
        "partial_update": ("write",),
        "refresh": ("refresh",),
        "bulk_refresh": ("refresh",),
        "export_snapshot": ("export",),
    }

    _blocked_extra_actions = frozenset({
        "bulk_delete",
        "bulk_update",
        "refresh_link_clicks",
        "import_snapshot",
        "refresh_all",
        "delete_post",
    })

    @classmethod
    def get_extra_actions(cls):
        return [
            act
            for act in super().get_extra_actions()
            if act.__name__ not in cls._blocked_extra_actions
        ]


class V1SummaryView(APIView):
    authentication_classes = [BearerApiKeyAuthentication]
    permission_classes = [RequireScopes]
    required_scopes = ("read",)

    def get(self, request, *args, **kwargs):
        return Response(compute_summary(request))


class V1ViewsAnchorsView(APIView):
    authentication_classes = [BearerApiKeyAuthentication]
    permission_classes = [RequireScopes]
    required_scopes = ("read",)

    def get(self, request, *args, **kwargs):
        return views_anchors(request._request)


class V1DomainListView(APIView):
    authentication_classes = [BearerApiKeyAuthentication]
    permission_classes = [RequireScopes]
    required_scopes = ("read",)

    def get(self, request, *args, **kwargs):
        return domain_list(request._request)


class V1JobDetailView(APIView):
    """Статус Apify-задачи после POST …/refresh/ → 202 + job_id."""

    authentication_classes = [BearerApiKeyAuthentication]
    permission_classes = [RequireScopes]
    required_scopes = ("refresh",)

    def get(self, request, pk: int, *args, **kwargs):
        from rest_framework import status

        job = ApifyRefreshJob.objects.select_related("account").filter(pk=pk).first()
        if job is None:
            return Response({"detail": "Задача не найдена."}, status=status.HTTP_404_NOT_FOUND)
        key = request.auth
        if getattr(key, "domain_id", None):
            acc_domain_id = job.account.domain_id if job.account_id else None
            if acc_domain_id != key.domain_id:
                return Response({"detail": "Задача не найдена."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "id": job.pk,
                "account_id": job.account_id,
                "platform": job.platform,
                "username": job.username_snapshot,
                "status": job.status,
                "apify_run_id": job.apify_run_id or None,
                "trigger": job.trigger,
                "error_message": job.error_message or None,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "created_at": job.created_at,
            }
        )
