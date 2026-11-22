from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Sum


# ---------------------------------------------------------------- пользователи
class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        if not phone:
            raise ValueError("Нужен номер телефона")
        user = self.model(phone=phone, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        return self.create_user(phone, password, **extra)


class Branch(models.Model):
    name = models.CharField("Филиал", max_length=100)

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        TEACHER = "teacher", "Учитель"
        STUDENT = "student", "Ученик"

    class Gender(models.TextChoices):
        MALE = "m", "Мужской"
        FEMALE = "f", "Женский"

    username = None
    phone = models.CharField("Телефон", max_length=20, unique=True)
    role = models.CharField("Роль", max_length=10, choices=Role.choices, default=Role.STUDENT)
    gender = models.CharField("Пол", max_length=1, choices=Gender.choices, blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    address = models.CharField("Адрес", max_length=200, blank=True)
    branch = models.ForeignKey(Branch, verbose_name="Филиал", null=True, blank=True, on_delete=models.SET_NULL)
    extra_phone = models.CharField("Доп. телефон", max_length=20, blank=True)
    extra_phone_note = models.CharField("Чей доп. телефон", max_length=50, blank=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.get_full_name() or self.phone

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT and not self.is_superuser

    @property
    def short_name(self):
        return f"{self.first_name} {self.last_name[:1]}.".strip() if self.last_name else self.first_name

    @property
    def age(self):
        if not self.birth_date:
            return None
        t = date.today()
        b = self.birth_date
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))

    @property
    def coin_balance(self):
        return self.coin_transactions.aggregate(s=Sum("amount"))["s"] or 0


# ---------------------------------------------------------------- курсы и группы
class Course(models.Model):
    name = models.CharField("Курс", max_length=100)
    icon = models.CharField("Иконка (эмодзи)", max_length=8, default="📘")

    class Meta:
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"

    def __str__(self):
        return self.name


WEEKDAYS = [(0, "Пн"), (1, "Вт"), (2, "Ср"), (3, "Чт"), (4, "Пт"), (5, "Сб"), (6, "Вс")]
WEEKDAY_NAMES = dict(WEEKDAYS)


class Group(models.Model):
    name = models.CharField("Название", max_length=150)
    course = models.ForeignKey(Course, verbose_name="Курс", on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, verbose_name="Филиал", null=True, blank=True, on_delete=models.SET_NULL)
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name="Учителя", related_name="teaching_groups", blank=True,
        limit_choices_to={"role": "teacher"},
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name="Ученики", related_name="study_groups", blank=True,
        limit_choices_to={"role": "student"},
    )
    start_date = models.DateField("Начало")
    end_date = models.DateField("Конец")
    days = models.CharField("Дни занятий", max_length=20, default="0,1,2,3,4,5",
                            help_text="Номера дней через запятую: 0=Пн … 6=Вс")
    time_from = models.TimeField("С", default="16:00")
    time_to = models.TimeField("До", default="18:00")

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    # --- расписание
    @property
    def day_list(self):
        return [int(d) for d in self.days.split(",") if d.strip().isdigit()]

    @property
    def days_display(self):
        return ", ".join(WEEKDAY_NAMES[d] for d in self.day_list)

    @property
    def is_active(self):
        return self.start_date <= date.today() <= self.end_date

    @property
    def status(self):
        t = date.today()
        if t < self.start_date:
            return "Скоро"
        return "Активна" if t <= self.end_date else "Завершена"

    @property
    def has_lesson_today(self):
        return self.is_active and date.today().weekday() in self.day_list

    def lesson_dates(self, until=None):
        end = min(self.end_date, until) if until else self.end_date
        days = set(self.day_list)
        d, out = self.start_date, []
        while d <= end:
            if d.weekday() in days:
                out.append(d)
            d += timedelta(days=1)
        return out

    # --- недели: неделя 1 = первые 7 дней с начала группы
    def week_of(self, d):
        return (d - self.start_date).days // 7 + 1

    def week_range(self, week):
        start = self.start_date + timedelta(days=7 * (week - 1))
        return start, min(start + timedelta(days=6), self.end_date)

    def week_dates(self, week):
        s, e = self.week_range(week)
        return [d for d in self.lesson_dates() if s <= d <= e]

    @property
    def total_weeks(self):
        return self.week_of(self.end_date)

    @property
    def current_week(self):
        return max(1, min(self.week_of(date.today()), self.total_weeks))


# ---------------------------------------------------------------- журнал
class LessonRecord(models.Model):
    class Attendance(models.TextChoices):
        PRESENT = "present", "Присутствовал"
        LATE = "late", "Опоздал"
        ABSENT = "absent", "Отсутствовал"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="records")
    date = models.DateField()
    attendance = models.CharField(max_length=10, choices=Attendance.choices, default=Attendance.PRESENT)
    late_minutes = models.PositiveIntegerField(default=0)
    grade = models.PositiveSmallIntegerField("Оценка 0–5", null=True, blank=True)
    bonus = models.IntegerField("Бонус (баллы)", default=0)

    class Meta:
        unique_together = ("group", "student", "date")
        ordering = ["date"]
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал"


class WeekResult(models.Model):
    """Итог недели ученика: экзамен, общий балл и сколько монет уже начислено."""
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="week_results")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="week_results")
    week = models.PositiveSmallIntegerField()
    exam = models.PositiveSmallIntegerField("Экзамен 0–100", null=True, blank=True)
    week_bonus = models.IntegerField("Бонус недели", default=0)
    total = models.FloatField(default=0)
    closed = models.BooleanField(default=False)
    coins_awarded = models.IntegerField(default=0)

    class Meta:
        unique_together = ("group", "student", "week")
        ordering = ["week"]
        verbose_name = "Итог недели"
        verbose_name_plural = "Итоги недель"


# ---------------------------------------------------------------- монеты и награды
class CoinTransaction(models.Model):
    class Kind(models.TextChoices):
        WEEK_GOOD = "week_good", "Хороший балл недели"
        WEEK_EXCELLENT = "week_excellent", "Отличный балл недели"
        WEEK_CORRECTION = "week_correction", "Пересчёт недели"
        TEACHER = "teacher", "От учителя"
        ADMIN = "admin", "От администратора"
        REDEEM = "redeem", "Обмен на награду"
        REFUND = "refund", "Возврат за награду"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coin_transactions")
    amount = models.IntegerField("Монеты")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reason = models.CharField("Причина", max_length=200, blank=True)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Операция с монетами"
        verbose_name_plural = "Операции с монетами"

    @property
    def title(self):
        return self.reason or self.get_kind_display()


class Reward(models.Model):
    title = models.CharField("Название", max_length=150)
    price = models.PositiveIntegerField("Цена (монеты)")
    image = models.FileField("Картинка", upload_to="rewards/", blank=True)
    icon = models.CharField("Эмодзи (если нет картинки)", max_length=8, default="🎁")
    stock = models.PositiveIntegerField("Остаток", null=True, blank=True, help_text="Пусто = без ограничения")
    is_active = models.BooleanField("Доступна", default=True)

    class Meta:
        ordering = ["price"]
        verbose_name = "Награда"
        verbose_name_plural = "Награды"

    def __str__(self):
        return self.title

    @property
    def in_stock(self):
        return self.is_active and (self.stock is None or self.stock > 0)


class Redemption(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        APPROVED = "approved", "Выдано"
        REJECTED = "rejected", "Отклонено"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="redemptions")
    reward = models.ForeignKey(Reward, on_delete=models.PROTECT, related_name="redemptions")
    price = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Обмен"
        verbose_name_plural = "Обмены"
