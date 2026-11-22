"""Заполняет базу демо-данными: python manage.py seed_demo"""
import random
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand

from core.models import Branch, Course, Group, LessonRecord, Reward, User, WeekResult
from core.services import close_week, give_coins

STUDENTS = [("Каримов", "Али", "m", 95), ("Рахимова", "Мадина", "f", 90), ("Назаров", "Сино", "m", 80),
            ("Юсупова", "Фарида", "f", 70), ("Саидов", "Умед", "m", 60), ("Олимова", "Нигина", "f", 88),
            ("Шарипов", "Далер", "m", 75), ("Ахмедова", "Зарина", "f", 92)]


class Command(BaseCommand):
    help = "Создать демо-данные (админ, учитель, ученики, группы, журнал, награды)"

    def handle(self, *args, **opts):
        random.seed(7)
        branch, _ = Branch.objects.get_or_create(name="Центральный")
        django_c, _ = Course.objects.get_or_create(name="Django", defaults={"icon": "🟩"})
        python_c, _ = Course.objects.get_or_create(name="Python", defaults={"icon": "🐍"})

        def person(phone, pwd, role, last, first, **kw):
            u, created = User.objects.get_or_create(phone=phone, defaults={
                "role": role, "last_name": last, "first_name": first, "branch": branch, **kw})
            if created:
                u.set_password(pwd)
                if role == User.Role.ADMIN:
                    u.is_staff = u.is_superuser = True
                u.save()
            return u

        person("900000001", "admin123", User.Role.ADMIN, "Админов", "Админ")
        teacher = person("900000002", "teacher123", User.Role.TEACHER, "Давлатов", "Юсуф")
        teacher2 = person("900000003", "teacher123", User.Role.TEACHER, "Мирзоева", "Шахноза")
        front_c, _ = Course.objects.get_or_create(name="Frontend", defaults={"icon": "🎨"})
        students = [person(f"90000001{i}", "student123", User.Role.STUDENT, last, first, gender=g,
                           birth_date=date(2010 + i % 3, 3 + i, 10 + i), address=f"ул. Рудаки {10 + i}",
                           extra_phone=f"93000000{i}", extra_phone_note="мама")
                    for i, (last, first, g, _) in enumerate(STUDENTS)]

        today = date.today()
        old = self._group("Python 2 (прошлый месяц)", python_c, branch, today - timedelta(days=60), today - timedelta(days=31))
        cur = self._group("Django MVT 16:00-18:00", django_c, branch, today - timedelta(days=20), today + timedelta(days=10))
        nxt = self._group("Frontend React 14:00-16:00", front_c, branch, today + timedelta(days=5), today + timedelta(days=40))
        nxt.teachers.add(teacher2)
        nxt.students.add(*students[5:])
        for g, members in ((old, students[:5]), (cur, students[:6])):
            g.teachers.add(teacher)
            g.students.add(*members)
            for s, (_, _, _, skill) in zip(members, STUDENTS):
                for d in g.lesson_dates(until=today - timedelta(days=1)):
                    roll = random.random()
                    att = "absent" if roll < 0.04 else "late" if roll < 0.1 else "present"
                    grade = None if att == "absent" else max(0, min(5, round(random.gauss(skill / 20, 0.6))))
                    LessonRecord.objects.get_or_create(group=g, student=s, date=d, defaults={
                        "attendance": att, "grade": grade, "late_minutes": 10 if att == "late" else 0})
            for w in range(1, g.total_weeks + 1):
                if g.week_range(w)[1] < today:
                    for s in members:
                        WeekResult.objects.get_or_create(group=g, student=s, week=w,
                                                         defaults={"exam": random.randint(70, 100)})
                    close_week(g, w, by=teacher)

        if not students[2].coin_transactions.filter(kind="teacher").exists():
            give_coins(students[2], 10, "Лучший проект недели", teacher)

        for title, price, icon in [("Скидка на курс 10%", 40, "🏷️"), ("Скидка на курс 20%", 75, "🏷️"),
                                   ("Игровые наушники", 50, "🎧"), ("Сумка с логотипом", 60, "👜"),
                                   ("Рюкзак для ноутбука", 55, "🎒"), ("Беспроводная мышь", 40, "🖱️"),
                                   ("Стикерпак", 5, "✨"), ("Кружка", 15, "☕")]:
            Reward.objects.get_or_create(title=title, defaults={"price": price, "icon": icon})

        from core.models import Redemption
        from core.services import redeem
        if not Redemption.objects.exists():
            redeem(students[0], Reward.objects.get(title="Стикерпак").pk)

        self.stdout.write(self.style.SUCCESS(
            "Демо готово.\n  Админ:   900000001 / admin123\n  Учитель: 900000002 / teacher123\n"
            "  Ученик:  900000010 / student123 (и 900000011…900000014)"))

    def _group(self, name, course, branch, start, end):
        g, _ = Group.objects.get_or_create(name=name, defaults={
            "course": course, "branch": branch, "start_date": start, "end_date": end,
            "time_from": time(16), "time_to": time(18)})
        return g
