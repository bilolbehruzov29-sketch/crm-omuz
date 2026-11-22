"""Бизнес-логика: недельный балл, автоматические монеты, ручные монеты, обмен наград.

Недельный балл (0–100):
  * каждое занятие оценивается 0–5; отсутствие = 0;
  * процент за занятия = сумма оценок / (5 × число прошедших занятий) × 100;
  * если учитель поставил экзамен недели (0–100): балл = 70% занятия + 30% экзамен;
  * плюс бонусные баллы (за занятия и за неделю), итог обрезается до 0–100.

Монеты за неделю (правила в settings.WEEKLY_COIN_RULES):
  * балл > 95  → 5 монет «Отличный балл недели»
  * балл > 90  → 3 монеты «Хороший балл недели»
Закрытие недели можно повторять: начисляется только разница, двойных монет не бывает.
"""
from datetime import date

from django.conf import settings
from django.db import transaction

from .models import CoinTransaction, LessonRecord, Redemption, Reward, User, WeekResult

LESSON_WEIGHT_WITH_EXAM = 0.7
EXAM_WEIGHT = 0.3


def coins_for_score(total):
    for threshold, coins, label in settings.WEEKLY_COIN_RULES:
        if total > threshold:
            return coins, label
    return 0, ""


def compute_week(group, student, week, records=None, result=None, today=None):
    today = today or date.today()
    dates = group.week_dates(week)
    past = [d for d in dates if d <= today]
    if records is None:
        records = {r.date: r for r in LessonRecord.objects.filter(group=group, student=student, date__in=dates)}
    if result is None:
        result = WeekResult.objects.filter(group=group, student=student, week=week).first()

    grades_sum = sum((records[d].grade or 0) for d in past if d in records and records[d].attendance != "absent")
    lesson_bonus = sum(records[d].bonus for d in dates if d in records)
    exam = result.exam if result else None
    week_bonus = result.week_bonus if result else 0

    lesson_pct = grades_sum / (5 * len(past)) * 100 if past else 0
    base = lesson_pct * LESSON_WEIGHT_WITH_EXAM + exam * EXAM_WEIGHT if exam is not None else lesson_pct
    total = round(max(0, min(100, base + lesson_bonus + week_bonus)), 1)
    return {
        "dates": dates,
        "records": records,
        "lesson_pct": round(lesson_pct, 1),
        "bonus": lesson_bonus + week_bonus,
        "week_bonus": week_bonus,
        "exam": exam,
        "total": total,
        "closed": bool(result and result.closed),
        "coins": result.coins_awarded if result else 0,
    }


@transaction.atomic
def close_week(group, week, by=None, students=None):
    """Считает итог недели и начисляет/корректирует монеты. Возвращает число начисленных монет."""
    given = 0
    for student in (students or group.students.all()):
        res, _ = WeekResult.objects.select_for_update().get_or_create(group=group, student=student, week=week)
        data = compute_week(group, student, week, result=res)
        want, label = coins_for_score(data["total"])
        delta = want - res.coins_awarded
        if delta:
            if res.coins_awarded == 0 and delta > 0:
                kind = (CoinTransaction.Kind.WEEK_EXCELLENT if want == max(r[1] for r in settings.WEEKLY_COIN_RULES)
                        else CoinTransaction.Kind.WEEK_GOOD)
                reason = f"{label} ({group.name}, неделя {week}: {data['total']} б.)"
            else:
                kind = CoinTransaction.Kind.WEEK_CORRECTION
                reason = f"Пересчёт: {group.name}, неделя {week}: {data['total']} б."
            CoinTransaction.objects.create(student=student, amount=delta, kind=kind, reason=reason,
                                           group=group, created_by=by)
            given += delta
        res.total = data["total"]
        res.closed = True
        res.coins_awarded = want
        res.save()
    return given


def refresh_closed_week(group, student, week, by=None):
    """Если неделя уже закрыта, а учитель поменял оценки — пересчитать монеты."""
    if WeekResult.objects.filter(group=group, student=student, week=week, closed=True).exists():
        close_week(group, week, by=by, students=[student])


def give_coins(student, amount, reason, by, group=None):
    kind = CoinTransaction.Kind.ADMIN if by.is_admin else CoinTransaction.Kind.TEACHER
    return CoinTransaction.objects.create(student=student, amount=amount, kind=kind,
                                          reason=reason or "", group=group, created_by=by)


class RedeemError(Exception):
    pass


@transaction.atomic
def redeem(student, reward_id):
    User.objects.select_for_update().get(pk=student.pk)  # блокируем, чтобы не потратить монеты дважды
    reward = Reward.objects.select_for_update().get(pk=reward_id)
    if not reward.in_stock:
        raise RedeemError("Награда недоступна")
    if student.coin_balance < reward.price:
        raise RedeemError("Недостаточно монет")
    r = Redemption.objects.create(student=student, reward=reward, price=reward.price)
    CoinTransaction.objects.create(student=student, amount=-reward.price, kind=CoinTransaction.Kind.REDEEM,
                                   reason=f"Обмен: {reward.title}")
    if reward.stock is not None:
        reward.stock -= 1
        reward.save(update_fields=["stock"])
    return r


@transaction.atomic
def set_redemption_status(redemption, status, by):
    r = Redemption.objects.select_for_update().get(pk=redemption.pk)
    if r.status != Redemption.Status.PENDING:
        return r
    r.status = status
    r.save(update_fields=["status"])
    if status == Redemption.Status.REJECTED:
        CoinTransaction.objects.create(student=r.student, amount=r.price, kind=CoinTransaction.Kind.REFUND,
                                       reason=f"Возврат: {r.reward.title}", created_by=by)
        if r.reward.stock is not None:
            Reward.objects.filter(pk=r.reward_id).update(stock=r.reward.stock + 1)
    return r
