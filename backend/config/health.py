"""Минимальный healthcheck-эндпоинт для Railway / k8s probes."""
from django.db import connection
from django.http import JsonResponse, HttpResponse


def healthz(_request):
    return JsonResponse({"status": "ok"})


def healthz_ready(_request):
    """
    Проверка готовности: живое соединение с БД.
    Используйте для оркестраторов; лёгкий /healthz/ без БД оставляем для прокси.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            if row is None or row[0] != 1:
                raise RuntimeError("unexpected SELECT 1 result")
    except Exception as exc:
        payload = {"status": "unready", "database": "error", "detail": str(exc)[:300]}
        return JsonResponse(payload, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


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
        path = request.path
        if path == "/healthz" or path == "/healthz/":
            return HttpResponse(b'{"status":"ok"}', content_type="application/json")
        if path == "/healthz/ready" or path == "/healthz/ready/":
            return healthz_ready(request)
        return self.get_response(request)
