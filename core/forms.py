from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import WEEKDAYS, Group, Reward, User


class PhoneLoginForm(AuthenticationForm):
    username = forms.CharField(label="Телефон", widget=forms.TextInput(attrs={"placeholder": "900 01 02 03", "autofocus": True}))
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput)

    def clean_username(self):
        return "".join(ch for ch in self.cleaned_data["username"] if ch.isdigit())


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


class PersonForm(forms.ModelForm):
    password = forms.CharField(label="Пароль", required=False, widget=forms.PasswordInput,
                               help_text="Оставьте пустым, чтобы не менять")

    class Meta:
        model = User
        fields = ["last_name", "first_name", "phone", "gender", "birth_date", "address", "branch",
                  "extra_phone", "extra_phone_note"]
        widgets = {"birth_date": DateInput()}

    role = User.Role.STUDENT

    def clean_phone(self):
        return "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())

    def clean(self):
        data = super().clean()
        if not self.instance.pk and not data.get("password"):
            self.add_error("password", "Для нового пользователя нужен пароль")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.pk:
            user.role = self.role
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class StudentForm(PersonForm):
    groups = forms.ModelMultipleChoiceField(label="Группы", queryset=Group.objects.all(), required=False,
                                            widget=forms.CheckboxSelectMultiple)
    role = User.Role.STUDENT

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields["groups"].initial = self.instance.study_groups.all()

    def save(self, commit=True):
        user = super().save(commit=True)
        user.study_groups.set(self.cleaned_data["groups"])
        return user


class TeacherForm(PersonForm):
    role = User.Role.TEACHER


class GroupForm(forms.ModelForm):
    field_order = ["name", "course", "branch", "start_date", "end_date", "time_from", "time_to", "day_choices",
                   "teachers", "students"]
    day_choices = forms.TypedMultipleChoiceField(label="Дни занятий", choices=WEEKDAYS, coerce=int,
                                                 widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Group
        fields = ["name", "course", "branch", "start_date", "end_date", "time_from", "time_to", "teachers", "students"]
        widgets = {
            "start_date": DateInput(), "end_date": DateInput(),
            "time_from": forms.TimeInput(attrs={"type": "time"}), "time_to": forms.TimeInput(attrs={"type": "time"}),
            "teachers": forms.CheckboxSelectMultiple, "students": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["day_choices"].initial = self.instance.day_list if self.instance.pk else [0, 1, 2, 3, 4, 5]

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "Конец раньше начала")
        return data

    def save(self, commit=True):
        self.instance.days = ",".join(str(d) for d in sorted(self.cleaned_data["day_choices"]))
        return super().save(commit)


class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ["title", "price", "icon", "image", "stock", "is_active"]


class GiveCoinsForm(forms.Form):
    student = forms.ModelChoiceField(label="Ученик", queryset=User.objects.none())
    amount = forms.IntegerField(label="Монеты", help_text="Сколько угодно. Минус — списать (только администратор).")
    reason = forms.CharField(label="За что", max_length=200, required=False,
                             widget=forms.TextInput(attrs={"placeholder": "Например: лучший проект недели"}))

    def __init__(self, *a, user=None, students=None, **kw):
        super().__init__(*a, **kw)
        self.user = user
        self.fields["student"].queryset = students

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError("Укажите число, не 0")
        if amount < 0 and not self.user.is_admin:
            raise forms.ValidationError("Учитель может только начислять монеты")
        return amount


class CourseForm(forms.ModelForm):
    class Meta:
        from .models import Course
        model = Course
        fields = ["name", "icon"]


class BranchForm(forms.ModelForm):
    class Meta:
        from .models import Branch
        model = Branch
        fields = ["name"]
