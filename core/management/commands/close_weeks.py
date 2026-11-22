"""Автоматически закрывает все прошедшие недели и начисляет монеты.
Запускать по расписанию (cron), например каждое воскресенье в 23:00:
    python manage.py close_weeks
"""
from datetime import date

from django.core.management.base import BaseCommand

from core.models import Group
from core.services import close_week


class Command(BaseCommand):
    help = "Закрыть прошедшие недели и начислить монеты за недельный балл"

    def handle(self, *args, **opts):
        today, total = date.today(), 0
        for g in Group.objects.filter(start_date__lte=today):
            for w in range(1, g.total_weeks + 1):
                if g.week_range(w)[1] < today:
                    total += close_week(g, w)
        self.stdout.write(self.style.SUCCESS(f"Готово. Начислено монет: {total}"))
