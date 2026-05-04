"""Минимальный healthcheck-эндпоинт для Railway / k8s probes."""
from django.http import JsonResponse, HttpResponse


def healthz(_request):
    return JsonResponse({"status": "ok"})


_HEALTH_PATHS = {"/healthz", "/healthz/"}


class HealthcheckMiddleware:
    """
    Отдаёт 200 OK на /healthz и /healthz/ ДО любых других middleware (включая
    SecurityMiddleware/CommonMiddleware с ALLOWED_HOSTS-проверкой).

    Зачем: Railway healthcheck стучится во внутренний proxy с Host-заголовком,
    которого нет в ALLOWED_HOSTS, и Django режет 400 «DisallowedHost». Эта
    middleware перехватывает только /healthz, всё остальное идёт обычным
    путём (с проверкой ALLOWED_HOSTS).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in _HEALTH_PATHS:
            return HttpResponse(b'{"status":"ok"}', content_type="application/json")
        return self.get_response(request)
