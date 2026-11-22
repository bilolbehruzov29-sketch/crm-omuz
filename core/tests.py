from datetime import date, timedelta

from django.test import TestCase

from . import services
from .models import CoinTransaction, Course, Group, LessonRecord, Redemption, Reward, User, WeekResult


class CoinRulesTest(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("1", "x", role="teacher")
        self.other_teacher = User.objects.create_user("2", "x", role="teacher")
        self.s = User.objects.create_user("3", "x", role="student", first_name="A")
        start = date.today() - timedelta(days=14)
        self.g = Group.objects.create(name="G", course=Course.objects.create(name="C"), start_date=start,
                                      end_date=start + timedelta(days=30), days="0,1,2,3,4,5,6")
        self.g.teachers.add(self.teacher)
        self.g.students.add(self.s)

    def set_week1(self, grades, exam=None, week_bonus=0):
        for d, gr in zip(self.g.week_dates(1), grades):
            LessonRecord.objects.update_or_create(group=self.g, student=self.s, date=d, defaults={"grade": gr})
        WeekResult.objects.update_or_create(group=self.g, student=self.s, week=1,
                                            defaults={"exam": exam, "week_bonus": week_bonus})

    def total(self):
        return services.compute_week(self.g, self.s, 1)["total"]

    def test_thresholds(self):
        self.assertEqual(services.coins_for_score(90)[0], 0)      # ровно 90 — не «больше 90»
        self.assertEqual(services.coins_for_score(90.1)[0], 3)
        self.assertEqual(services.coins_for_score(95)[0], 3)      # ровно 95 — ещё 3
        self.assertEqual(services.coins_for_score(95.5)[0], 5)
        self.assertEqual(services.coins_for_score(100)[0], 5)

    def test_close_week_awards_and_is_idempotent(self):
        self.set_week1([5] * 7)  # 100 баллов
        self.assertEqual(self.total(), 100)
        services.close_week(self.g, 1, by=self.teacher)
        services.close_week(self.g, 1, by=self.teacher)  # повторно — без двойного начисления
        self.assertEqual(self.s.coin_balance, 5)

    def test_correction_after_grade_change(self):
        self.set_week1([5] * 7)
        services.close_week(self.g, 1)
        # учитель понизил оценки: 32/35 = 91.4 → должно стать 3 монеты (коррекция −2)
        self.set_week1([5, 5, 5, 5, 4, 4, 4])
        services.refresh_closed_week(self.g, self.s, 1)
        self.assertEqual(self.s.coin_balance, 3)
        self.assertTrue(CoinTransaction.objects.filter(kind="week_correction", amount=-2).exists())

    def test_exam_and_bonus(self):
        self.set_week1([4] * 7, exam=100)  # 80*0.7 + 100*0.3 = 86
        self.assertEqual(self.total(), 86)
        self.set_week1([4] * 7, exam=100, week_bonus=6)  # 92 → 3 монеты
        services.close_week(self.g, 1)
        self.assertEqual(self.s.coin_balance, 3)

    def test_teacher_coins_and_redeem(self):
        services.give_coins(self.s, 50, "проект", self.teacher)
        r = Reward.objects.create(title="Мышь", price=40, stock=1)
        red = services.redeem(self.s, r.pk)
        self.assertEqual(self.s.coin_balance, 10)
        with self.assertRaises(services.RedeemError):
            services.redeem(self.s, r.pk)  # нет в наличии / не хватает
        services.set_redemption_status(red, Redemption.Status.REJECTED, self.teacher)
        self.assertEqual(self.s.coin_balance, 50)

    def test_permissions(self):
        url = f"/groups/{self.g.pk}/journal/"
        self.client.force_login(self.s)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"week": 1, "close": 1}).status_code, 403)
        self.assertEqual(self.client.get("/dashboard/").status_code, 403)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(url).status_code, 404)  # чужая группа
        self.client.force_login(self.teacher)
        resp = self.client.post(url, {"week": 1, "close": 1, **{f"grade_{self.s.pk}_{d:%Y%m%d}": 5 for d in self.g.week_dates(1)}})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.s.coin_balance, 5)
        # учитель не может списывать монеты
        resp = self.client.post("/coins/give/", {"student": self.s.pk, "amount": -5, "reason": "x"})
        self.assertEqual(self.s.coin_balance, 5)


class AdminManageTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("100", "x")
        self.t = User.objects.create_user("101", "x", role="teacher")
        self.s1 = User.objects.create_user("102", "x", role="student")
        self.s2 = User.objects.create_user("103", "x", role="student")
        self.c = Course.objects.create(name="C")
        self.g = Group.objects.create(name="G", course=self.c, start_date=date.today(), end_date=date.today() + timedelta(days=30))
        self.client.force_login(self.admin)

    def test_members(self):
        url = f"/groups/{self.g.pk}/"
        self.client.post(url, {"action": "add_students", "ids": [self.s1.pk, self.s2.pk]})
        self.assertEqual(self.g.students.count(), 2)
        self.client.post(url, {"action": "remove_student", "ids": [self.s1.pk]})
        self.assertEqual(list(self.g.students.all()), [self.s2])
        self.client.post(url, {"action": "add_teachers", "ids": [self.t.pk]})
        self.assertTrue(self.g.teachers.filter(pk=self.t.pk).exists())
        self.client.post(url, {"action": "remove_teacher", "ids": [self.t.pk]})
        self.assertFalse(self.g.teachers.exists())

    def test_delete_and_protect(self):
        self.assertEqual(self.client.post(f"/delete/course/{self.c.pk}/").status_code, 302)
        self.assertTrue(Course.objects.filter(pk=self.c.pk).exists())  # курс занят группой
        self.client.post(f"/delete/group/{self.g.pk}/")
        self.assertFalse(Group.objects.exists())
        self.client.post(f"/delete/course/{self.c.pk}/")
        self.assertFalse(Course.objects.exists())
        self.client.post(f"/delete/student/{self.s1.pk}/")
        self.assertFalse(User.objects.filter(pk=self.s1.pk).exists())
        r = Reward.objects.create(title="R", price=1)
        services.give_coins(self.s2, 5, "", self.admin)
        services.redeem(self.s2, r.pk)
        self.client.post(f"/delete/reward/{r.pk}/")
        r.refresh_from_db()
        self.assertFalse(r.is_active)  # обменянную награду скрываем, а не удаляем
        self.assertEqual(self.client.get(f"/delete/group/1/").status_code, 405)  # только POST

    def test_block(self):
        self.client.post(f"/users/{self.s1.pk}/toggle/")
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.is_active)
        self.assertFalse(self.client.login(phone="102", password="x"))

    def test_teacher_cannot_manage(self):
        self.g.teachers.add(self.t)
        self.client.force_login(self.t)
        self.assertEqual(self.client.post(f"/groups/{self.g.pk}/", {"action": "add_students", "ids": [self.s1.pk]}).status_code, 403)
        self.assertEqual(self.client.post(f"/delete/group/{self.g.pk}/").status_code, 403)
        self.assertEqual(self.client.get("/catalog/").status_code, 403)
