"""Определение текущего домена по адресу запроса и сужение выборок по нему.

Домен можно задать двумя способами, и оба работают одновременно:

- **путём** — ``/reiz/api/accounts/`` или заголовком ``X-Domain: reiz``;
- **поддоменом** — ``reiz.example.com``.

Так сделано намеренно. Приложение стоит за Cloudflare Tunnel, где список
публичных хостов живёт в панели Cloudflare, а не на сервере: пока поддомены
там не заведены, всё работает по путям, а после — само заработает и по
поддоменам, без правок кода.

Отдельно стоит ``efir``: это не арендатор, а сводный эфир по всем доменам.
"""

from django.db.models import Q

from .models import AGGREGATE_DOMAIN_SLUG, Domain

__all__ = ["AGGREGATE_DOMAIN_SLUG", "DomainScope", "resolve", "narrow", "slug_from_request"]

#: Хосты, у которых первая часть — не поддомен-арендатор, а само приложение.
_BARE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "testserver"}


class DomainScope:
    """Что показывать: конкретный домен, сводный эфир или всё сразу.

    - ``domain`` — строка ``Domain`` или ``None``;
    - ``aggregate`` — True для ``efir``: показываем все домены;
    - ``unknown`` — в адресе был домен, которого нет в базе.
    """

    __slots__ = ("domain", "aggregate", "unknown", "slug")

    def __init__(self, domain=None, aggregate=False, unknown=None, slug=None):
        self.domain = domain
        self.aggregate = aggregate
        self.unknown = unknown
        self.slug = slug

    @property
    def scoped(self):
        """Нужно ли вообще сужать выборку."""
        return self.domain is not None

    def __repr__(self):
        if self.aggregate:
            return "<DomainScope efir: все домены>"
        if self.unknown:
            return f"<DomainScope неизвестный: {self.unknown}>"
        return f"<DomainScope {self.domain.slug if self.domain else 'все'}>"


def slug_from_request(request):
    """Достаём slug из адреса: заголовок, путь, затем поддомен."""
    header = (request.headers.get("X-Domain") or "").strip().lower()
    if header:
        return header

    # /reiz/... — первый кусок пути, если это не служебные разделы.
    path = (request.path or "").strip("/")
    if path:
        first = path.split("/", 1)[0].lower()
        if first and first not in {"api", "admin", "media", "static", "healthz"}:
            return first

    host = (request.get_host() or "").split(":")[0].lower()
    if host and host not in _BARE_HOSTS:
        parts = host.split(".")
        # Поддомен есть только когда частей больше двух: reiz.example.com.
        if len(parts) > 2:
            return parts[0]
    return ""


def resolve(request):
    """Определяем домен запроса. Никогда не бросает — при промахе вернёт «всё»."""
    slug = slug_from_request(request)
    if not slug:
        return DomainScope()
    if slug == AGGREGATE_DOMAIN_SLUG:
        return DomainScope(aggregate=True, slug=slug)
    domain = Domain.objects.filter(slug=slug, is_active=True).first()
    if domain is None:
        # Неизвестный кусок адреса не должен молча показывать чужие данные,
        # но и падать не должен: помечаем и отдаём общий набор.
        return DomainScope(unknown=slug, slug=slug)
    return DomainScope(domain=domain, slug=slug)


def narrow(queryset, scope, field="domain"):
    """Сужаем выборку до домена.

    Записи без домена («не распределено») видны везде — иначе миграция на
    боевой базе разом спрятала бы всё, что уже есть, и дашборд стал бы пустым.
    По мере раскладывания по доменам каждый из них сужается сам собой.
    """
    if scope is None or not scope.scoped:
        return queryset
    return queryset.filter(Q(**{field: scope.domain}) | Q(**{f"{field}__isnull": True}))
