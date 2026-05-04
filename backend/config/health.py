"""Минимальный healthcheck-эндпоинт для Railway / k8s probes."""
from django.http import JsonResponse


def healthz(_request):
    return JsonResponse({"status": "ok"})
