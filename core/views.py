import json
from calendar import monthrange
from datetime import date, timedelta

from django.conf import settings

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import GiveCoinsForm, GroupForm, RewardForm, StudentForm, TeacherForm
from .models import (WEEKDAY_NAMES, CoinTransaction, Course, Group, LessonRecord, Redemption, Reward, User,
                     WeekResult)
from .permissions import can_edit_group, role_required, visible_groups, visible_students

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
          "Ноябрь", "Декабрь"]


def paginate(request, qs, per_page=12):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


@login_required
def home(request):
    u = request.user
    if u.is_admin:
        return redirect("dashboard")
    if u.is_teacher:
        return redirect("groups")
    return redirect("profile")


# ------------------------------------------------------------------ профиль ученика
@login_required
def profile(request, pk=None):
    me = request.user
    if pk is None:
        if not me.is_student:
            return redirect("home")
        student = me
    else:
        student = get_object_or_404(visible_students(me), pk=pk)

    groups = list(student.study_groups.select_related("course").order_by("-start_date"))
    group = None
    if groups:
        gid = request.GET.get("group")
        group = next((g for g in groups if str(g.pk) == gid), None) or next((g for g in groups if g.is_active), groups[0])

    try:
        y, m = map(int, request.GET.get("month", "").split("-"))
        month = date(y, m, 1)
    except ValueError:
        month = (date.today() if group is None or group.is_active else group.start_date).replace(day=1)
    prev_m = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_m = month.replace(day=monthrange(month.year, month.month)[1]) + timedelta(days=1)

    stats, rows = None, []
    if group:
        month_end = next_m - timedelta(days=1)
        dates = [d for d in group.lesson_dates(until=date.today()) if month <= d <= month_end]
        recs = {r.date: r for r in LessonRecord.objects.filter(group=group, student=student, date__in=dates)}
        lesson_min = (group.time_to.hour * 60 + group.time_to.minute) - (group.time_from.hour * 60 + group.time_from.minute)
        present = late = absent = present_min = late_min = 0
        for d in dates:
            r = recs.get(d)
            if r is None:
                rows.append({"date": d, "rec": None})
                continue
            if r.attendance == "absent":
                absent += 1
            else:
                present += 1
                present_min += lesson_min - r.late_minutes
                if r.attendance == "late":
                    late += 1
                    late_min += r.late_minutes
            rows.append({"date": d, "rec": r, "minutes": lesson_min - r.late_minutes})
        marked = present + absent
        stats = {
            "present": present, "absent": absent, "late": late,
            "present_time": f"{present_min // 60} ч {present_min % 60} мин",
            "absent_time": f"{absent * lesson_min // 60} ч {absent * lesson_min % 60} мин",
            "late_time": f"{late_min // 60} ч {late_min % 60} мин",
            "rate": round(present / marked * 100, 1) if marked else 0,
        }

    return render(request, "core/profile.html", {
        "student": student, "groups": groups, "group": group, "stats": stats, "rows": rows,
        "month": month, "month_label": f"{MONTHS[month.month - 1]} {month.year}",
        "prev_month": prev_m.strftime("%Y-%m"), "next_month": next_m.strftime("%Y-%m"),
        "schedule": [(WEEKDAY_NAMES[d], group) for d in group.day_list] if group else [],
        "balance": student.coin_balance,
    })


# ------------------------------------------------------------------ группы
@login_required
def groups(request):
    qs = visible_groups(request.user).annotate(n_students=Count("students", distinct=True))
    q, status, course, teacher = (request.GET.get(k, "") for k in ("q", "status", "course", "teacher"))
    if q:
        qs = qs.filter(name__icontains=q)
    if course:
        qs = qs.filter(course_id=course)
    if teacher:
        qs = qs.filter(teachers=teacher)
    today = date.today()
    if status == "active":
        qs = qs.filter(start_date__lte=today, end_date__gte=today)
    elif status == "finished":
        qs = qs.filter(end_date__lt=today)
    elif status == "soon":
        qs = qs.filter(start_date__gt=today)
    return render(request, "core/groups.html", {
        "page": paginate(request, qs.distinct()), "courses": Course.objects.all(),
        "teachers": User.objects.filter(role=User.Role.TEACHER),
        "f": {"q": q, "status": status, "course": course, "teacher": teacher},
    })


@login_required
def journal(request, pk):
    group = get_object_or_404(visible_groups(request.user), pk=pk)
    editable = can_edit_group(request.user, group)
    students = list(group.students.all())
    last_week = group.current_week if group.is_active or date.today() < group.start_date else group.total_weeks
    weeks = list(range(1, last_week + 1))

    if request.method == "POST":
        if not editable:
            raise PermissionDenied
        week = int(request.POST["week"])
        _save_week(request, group, students, week)
        if "close" in request.POST:
            given = services.close_week(group, week, by=request.user)
            messages.success(request, f"Неделя {week} закрыта. Начислено монет: {given}.")
        else:
            for s in students:
                services.refresh_closed_week(group, s, week, by=request.user)
            messages.success(request, "Журнал сохранён.")
        return redirect(f"{request.path}?week={week}#week-{week}")

    all_recs = {}
    for r in LessonRecord.objects.filter(group=group):
        all_recs.setdefault((r.student_id, group.week_of(r.date)), {})[r.date] = r
    results = {(r.student_id, r.week): r for r in WeekResult.objects.filter(group=group)}

    week_tables = []
    series = {s.pk: [] for s in students}
    for w in weeks:
        rows = []
        for s in students:
            data = services.compute_week(group, s, w, records=all_recs.get((s.pk, w), {}), result=results.get((s.pk, w)))
            series[s.pk].append(data["total"])
            rows.append({"student": s, **data,
                         "cells": [(d, data["records"].get(d)) for d in data["dates"]]})
        rows.sort(key=lambda r: -r["total"])
        s0, e0 = group.week_range(w)
        week_tables.append({"week": w, "dates": group.week_dates(w), "rows": rows, "start": s0, "end": e0,
                            "closed": all(r["closed"] for r in rows) if rows else False})

    palette = ["#6366f1", "#ec4899", "#10b981", "#f59e0b", "#0ea5e9", "#a855f7", "#f43f5e", "#14b8a6"]
    chart = {
        "labels": [f"Неделя {w}" for w in weeks] + ["Среднее"],
        "datasets": [{
            "label": s.short_name,
            "data": series[s.pk] + [round(sum(series[s.pk]) / len(series[s.pk]), 1) if series[s.pk] else 0],
            "borderColor": palette[i % len(palette)], "backgroundColor": palette[i % len(palette)],
        } for i, s in enumerate(students)],
    }
    open_week = int(request.GET.get("week", last_week))
    return render(request, "core/journal.html", {
        "group": group, "editable": editable, "weeks": list(reversed(week_tables)),
        "chart_json": json.dumps(chart), "open_week": open_week, "today": date.today(),
        "rules": settings.WEEKLY_COIN_RULES,
    })


def _int_or_none(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return None


def _save_week(request, group, students, week):
    P = request.POST
    for s in students:
        for d in group.week_dates(week):
            key = f"{s.pk}_{d:%Y%m%d}"
            att = P.get(f"att_{key}")
            grade = _int_or_none(P.get(f"grade_{key}"), 0, 5)
            bonus = _int_or_none(P.get(f"bonus_{key}"), -100, 100) or 0
            if att is None and grade is None and not bonus:
                continue
            LessonRecord.objects.update_or_create(
                group=group, student=s, date=d,
                defaults={"attendance": att or "present", "grade": grade, "bonus": bonus,
                          "late_minutes": _int_or_none(P.get(f"late_{key}"), 0, 600) or 0})
        res, _ = WeekResult.objects.get_or_create(group=group, student=s, week=week)
        res.exam = _int_or_none(P.get(f"exam_{s.pk}"), 0, 100)
        res.week_bonus = _int_or_none(P.get(f"wbonus_{s.pk}"), -100, 100) or 0
        res.total = services.compute_week(group, s, week, result=res)["total"]
        res.save()


# ------------------------------------------------------------------ ученики / учителя
@login_required
def students(request):
    if request.user.is_student:
        return redirect("profile")
    qs = visible_students(request.user).select_related("branch").prefetch_related("study_groups")
    q, group = request.GET.get("q", ""), request.GET.get("group", "")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q))
    if group:
        qs = qs.filter(study_groups=group)
    qs = qs.annotate(balance=Sum("coin_transactions__amount"))
    return render(request, "core/students.html", {
        "page": paginate(request, qs), "groups": visible_groups(request.user), "f": {"q": q, "group": group},
    })


@role_required("admin")
def teachers(request):
    qs = User.objects.filter(role=User.Role.TEACHER).annotate(n_groups=Count("teaching_groups"))
    q = request.GET.get("q", "")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q))
    return render(request, "core/teachers.html", {"page": paginate(request, qs), "f": {"q": q}})


def _crud(request, form_class, instance, title, back, initial=None, kind=None, **form_kw):
    form = form_class(request.POST or None, request.FILES or None, instance=instance, initial=initial, **form_kw)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Сохранено.")
        return redirect(back)
    return render(request, "core/form.html", {"form": form, "title": title, "back": back, "obj": instance,
                                              "kind": kind})


@role_required("admin")
def student_edit(request, pk=None):
    obj = get_object_or_404(User, pk=pk, role=User.Role.STUDENT) if pk else None
    initial = {"groups": [request.GET["group"]]} if request.GET.get("group", "").isdigit() else None
    back = request.GET.get("next") or "students"
    form = StudentForm(request.POST or None, instance=obj, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Сохранено.")
        return redirect(back)
    return render(request, "core/form.html", {"form": form, "title": "Ученик" if obj else "Новый ученик",
                                              "back": "students", "obj": obj, "kind": "student"})


@role_required("admin")
def teacher_edit(request, pk=None):
    obj = get_object_or_404(User, pk=pk, role=User.Role.TEACHER) if pk else None
    return _crud(request, TeacherForm, obj, "Учитель" if obj else "Новый учитель", "teachers", kind="teacher")


@role_required("admin")
def group_edit(request, pk=None):
    obj = get_object_or_404(Group, pk=pk) if pk else None
    return _crud(request, GroupForm, obj, "Группа" if obj else "Новая группа", "groups", kind="group")


@role_required("admin")
def reward_edit(request, pk=None):
    obj = get_object_or_404(Reward, pk=pk) if pk else None
    return _crud(request, RewardForm, obj, "Награда" if obj else "Новая награда", "rewards", kind="reward")


# ------------------------------------------------------------------ монеты и награды
@login_required
def rewards(request):
    me = request.user
    if request.method == "POST" and "reward" in request.POST:
        if not me.is_student:
            raise PermissionDenied
        try:
            services.redeem(me, int(request.POST["reward"]))
            messages.success(request, "Заявка на обмен отправлена! Администратор выдаст награду.")
        except services.RedeemError as e:
            messages.error(request, str(e))
        return redirect("rewards")

    qs = Reward.objects.all() if me.is_admin else Reward.objects.filter(is_active=True)
    q, lo, hi = request.GET.get("q", ""), request.GET.get("min", ""), request.GET.get("max", "")
    if q:
        qs = qs.filter(title__icontains=q)
    if lo.isdigit():
        qs = qs.filter(price__gte=int(lo))
    if hi.isdigit():
        qs = qs.filter(price__lte=int(hi))
    ctx = {"page": paginate(request, qs), "f": {"q": q, "min": lo, "max": hi}}
    if me.is_student:
        ctx.update(balance=me.coin_balance, history=me.coin_transactions.all()[:30],
                   my_redemptions=me.redemptions.select_related("reward"))
    return render(request, "core/rewards.html", ctx)


@role_required("teacher")
def give_coins(request):
    students_qs = visible_students(request.user)
    form = GiveCoinsForm(request.POST or None, user=request.user, students=students_qs,
                         initial={"student": request.GET.get("student")})
    if request.method == "POST" and form.is_valid():
        s = form.cleaned_data["student"]
        services.give_coins(s, form.cleaned_data["amount"], form.cleaned_data["reason"], request.user)
        messages.success(request, f"{s}: {form.cleaned_data['amount']:+d} монет.")
        return redirect("give_coins")
    recent = CoinTransaction.objects.select_related("student", "created_by").filter(
        kind__in=["teacher", "admin"])
    if not request.user.is_admin:
        recent = recent.filter(created_by=request.user)
    return render(request, "core/give_coins.html", {"form": form, "recent": recent[:20]})


@role_required("admin")
def redemptions(request):
    if request.method == "POST":
        r = get_object_or_404(Redemption, pk=request.POST["id"])
        status = Redemption.Status.APPROVED if request.POST["action"] == "approve" else Redemption.Status.REJECTED
        services.set_redemption_status(r, status, request.user)
        messages.success(request, f"{r.student}: {r.reward} — {Redemption.Status(status).label.lower()}.")
        return redirect("redemptions")
    qs = Redemption.objects.select_related("student", "reward")
    st = request.GET.get("status", "pending")
    if st:
        qs = qs.filter(status=st)
    return render(request, "core/redemptions.html", {"page": paginate(request, qs, 20), "status": st})


@role_required("admin")
def transactions(request):
    qs = CoinTransaction.objects.select_related("student", "created_by", "group")
    kind = request.GET.get("kind", "")
    if kind:
        qs = qs.filter(kind=kind)
    return render(request, "core/transactions.html", {
        "page": paginate(request, qs, 30), "kinds": CoinTransaction.Kind.choices, "kind": kind})


@role_required("admin")
def dashboard(request):
    today = date.today()
    active = Group.objects.filter(start_date__lte=today, end_date__gte=today)
    top = (User.objects.filter(role=User.Role.STUDENT).annotate(balance=Sum("coin_transactions__amount"))
           .filter(balance__gt=0).order_by("-balance")[:10])
    return render(request, "core/dashboard.html", {
        "counts": {
            "students": User.objects.filter(role=User.Role.STUDENT).count(),
            "teachers": User.objects.filter(role=User.Role.TEACHER).count(),
            "groups": Group.objects.count(), "active": active.count(),
            "coins": CoinTransaction.objects.filter(amount__gt=0).aggregate(s=Sum("amount"))["s"] or 0,
            "pending": Redemption.objects.filter(status="pending").count(),
        },
        "active_groups": active.select_related("course").prefetch_related("teachers").annotate(n=Count("students")),
        "top": top,
        "recent": CoinTransaction.objects.select_related("student")[:10],
    })


# ------------------------------------------------------------------ админ: управление
from django.db.models import ProtectedError  # noqa: E402
from django.views.decorators.http import require_POST  # noqa: E402

from .forms import BranchForm, CourseForm  # noqa: E402
from .models import Branch  # noqa: E402

DELETABLE = {
    "group": (lambda: Group.objects.all(), "groups", "Группа «{}» удалена"),
    "student": (lambda: User.objects.filter(role=User.Role.STUDENT), "students", "Ученик «{}» удалён"),
    "teacher": (lambda: User.objects.filter(role=User.Role.TEACHER), "teachers", "Учитель «{}» удалён"),
    "reward": (lambda: Reward.objects.all(), "rewards", "Награда «{}» удалена"),
    "course": (lambda: Course.objects.all(), "catalog", "Курс «{}» удалён"),
    "branch": (lambda: Branch.objects.all(), "catalog", "Филиал «{}» удалён"),
}


@role_required("admin")
@require_POST
def delete_object(request, kind, pk):
    if kind not in DELETABLE:
        raise PermissionDenied
    qs, back, label = DELETABLE[kind]
    obj = get_object_or_404(qs(), pk=pk)
    name = str(obj)
    try:
        obj.delete()
        messages.success(request, label.format(name) + ".")
    except ProtectedError:
        if kind == "reward":
            obj.is_active = False
            obj.save(update_fields=["is_active"])
            messages.warning(request, f"«{name}» уже обменивали, поэтому награда скрыта, а не удалена.")
        else:
            messages.error(request, f"Нельзя удалить «{name}»: он используется (например, в группах).")
    return redirect(request.POST.get("next") or back)


@role_required("admin")
@require_POST
def toggle_active(request, pk):
    u = get_object_or_404(User.objects.exclude(pk=request.user.pk), pk=pk)
    u.is_active = not u.is_active
    u.save(update_fields=["is_active"])
    messages.success(request, f"{u}: {'доступ открыт' if u.is_active else 'вход заблокирован'}.")
    return redirect(request.POST.get("next") or "students")


@login_required
def group_detail(request, pk):
    group = get_object_or_404(visible_groups(request.user), pk=pk)
    if request.user.is_student:
        return redirect("journal", pk=pk)
    admin = request.user.is_admin
    if request.method == "POST":
        if not admin:
            raise PermissionDenied
        action = request.POST.get("action")
        ids = request.POST.getlist("ids")
        if action == "add_students":
            added = User.objects.filter(role=User.Role.STUDENT, pk__in=ids)
            group.students.add(*added)
            messages.success(request, f"Добавлено учеников: {added.count()}.")
        elif action == "remove_student":
            group.students.remove(*User.objects.filter(pk__in=ids))
            messages.success(request, "Ученик убран из группы.")
        elif action == "add_teachers":
            group.teachers.add(*User.objects.filter(role=User.Role.TEACHER, pk__in=ids))
            messages.success(request, "Учитель назначен.")
        elif action == "remove_teacher":
            group.teachers.remove(*User.objects.filter(pk__in=ids))
            messages.success(request, "Учитель снят с группы.")
        return redirect("group_detail", pk=pk)

    members = group.students.annotate(balance=Sum("coin_transactions__amount"))
    member_rows = []
    for s in members:
        res = WeekResult.objects.filter(group=group, student=s).order_by("-week").first()
        avg = WeekResult.objects.filter(group=group, student=s).aggregate(a=Avg("total"))["a"]
        member_rows.append({"s": s, "last": res.total if res else None, "avg": round(avg, 1) if avg else None})
    return render(request, "core/group_detail.html", {
        "group": group, "admin": admin, "members": member_rows,
        "available_students": User.objects.filter(role=User.Role.STUDENT, is_active=True).exclude(study_groups=group),
        "available_teachers": User.objects.filter(role=User.Role.TEACHER).exclude(teaching_groups=group),
        "week": group.current_week,
    })


@role_required("admin")
def catalog(request):
    course_form = CourseForm(prefix="c")
    branch_form = BranchForm(prefix="b")
    if request.method == "POST":
        if "add_course" in request.POST:
            course_form = CourseForm(request.POST, prefix="c")
            if course_form.is_valid():
                course_form.save()
                messages.success(request, "Курс добавлен.")
                return redirect("catalog")
        elif "add_branch" in request.POST:
            branch_form = BranchForm(request.POST, prefix="b")
            if branch_form.is_valid():
                branch_form.save()
                messages.success(request, "Филиал добавлен.")
                return redirect("catalog")
    return render(request, "core/catalog.html", {
        "courses": Course.objects.annotate(n=Count("group")),
        "branches": Branch.objects.annotate(n=Count("group", distinct=True), people=Count("user", distinct=True)),
        "course_form": course_form, "branch_form": branch_form,
    })


@role_required("admin")
def course_edit(request, pk):
    return _crud(request, CourseForm, get_object_or_404(Course, pk=pk), "Курс", "catalog", kind="course")


@role_required("admin")
def branch_edit(request, pk):
    return _crud(request, BranchForm, get_object_or_404(Branch, pk=pk), "Филиал", "catalog", kind="branch")
