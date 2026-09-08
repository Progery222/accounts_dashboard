"""Определение текущего домена по адресу запроса и сужение выборок по нему.

Домен задаётся **куском пути**: ``/reiz`` — только аккаунты reiz, пустой путь
— все аккаунты. Фронт передаёт разобранное значение заголовком ``X-Domain``,
чтобы не переписывать полсотни адресов запросов.

Поддомены сознательно не разбираем. Кроме того, что так попросили, на
``dashboard-new.atom-farm.com`` первая часть хоста — это само приложение, а не
арендатор: приняв её за домен, мы получили бы «домен не найден» на главной.

Отдельно стоит ``efir``: это не арендатор, а сводный эфир по всем доменам.
"""

from .models import AGGREGATE_DOMAIN_SLUG, Domain

__all__ = ["AGGREGATE_DOMAIN_SLUG", "DomainScope", "resolve", "narrow", "slug_from_request"]


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
    """Достаём slug: сначала заголовок от фронта, потом первый кусок пути."""
    header = (request.headers.get("X-Domain") or "").strip().lower()
    if header:
        return header

    # /reiz/... — первый кусок пути, если это не служебные разделы.
    path = (request.path or "").strip("/")
    if path:
        first = path.split("/", 1)[0].lower()
        if first and first not in {"api", "admin", "media", "static", "healthz"}:
            return first
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
    """Сужаем выборку до домена — строго.

    ``/reiz`` показывает только записи reiz. Нераспределённые (домен пустой)
    в домен не попадают: они видны на корне, где показывается всё.

    Неизвестный кусок адреса не отдаёт ничего. Отдавать в этом случае всю сеть
    опаснее: устаревшая ссылка вроде ``/emu`` молча показала бы полный дашборд,
    как будто так и задумано.
    """
    if scope is None:
        return queryset
    if scope.unknown:
        return queryset.none()
    if not scope.scoped:
        return queryset
    return queryset.filter(**{field: scope.domain})
