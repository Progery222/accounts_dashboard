from .models import GlobalVisibilityConfig


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def _get_hidden_platforms() -> set[str]:
    try:
        cfg = GlobalVisibilityConfig.get()
        raw = getattr(cfg, "hidden_platforms", None) or []
        return {str(v).strip().lower() for v in raw if str(v).strip()}
    except Exception:
        return set()


def _apply_visibility_filters(
    qs,
    *,
    include_hidden_platforms: bool = False,
    include_hidden_profiles: bool = False,
):
    if not include_hidden_platforms:
        hidden_platforms = _get_hidden_platforms()
        if hidden_platforms:
            qs = qs.exclude(platform__in=hidden_platforms)
    if not include_hidden_profiles:
        qs = qs.exclude(profile__is_hidden=True)
    return qs
