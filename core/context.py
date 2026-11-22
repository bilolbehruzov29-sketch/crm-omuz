def sidebar(request):
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    ctx = {"my_balance": u.coin_balance if u.is_student else None}
    if u.is_admin:
        from .models import Redemption
        ctx["pending_count"] = Redemption.objects.filter(status="pending").count()
    return ctx
