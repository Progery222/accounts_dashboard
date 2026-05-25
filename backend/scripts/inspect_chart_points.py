from accounts.models import AutoRefreshPoint

pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
print("count", len(pts))
if not pts:
    raise SystemExit(0)
print("min", pts[0].measured_at)
print("max", pts[-1].measured_at)
vals = [p.view_count_total for p in pts]
print("total unique", len(set(vals)), "min", min(vals), "max", max(vals))
print("first5", vals[:5])
print("last5", vals[-5:])
day = [p.view_delta_from_day_start for p in pts]
print("day_delta unique", len(set(day)), "max", max(day) if day else None)
