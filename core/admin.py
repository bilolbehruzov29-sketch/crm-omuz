from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.User)
class CrmUserAdmin(UserAdmin):
    ordering = ["last_name"]
    list_display = ["phone", "last_name", "first_name", "role", "branch"]
    list_filter = ["role", "branch"]
    search_fields = ["phone", "first_name", "last_name"]
    fieldsets = (
        (None, {"fields": ("phone", "password", "role")}),
        ("Данные", {"fields": ("last_name", "first_name", "gender", "birth_date", "address", "branch",
                               "extra_phone", "extra_phone_note")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "role", "password1", "password2")}),)


for m in [models.Branch, models.Course, models.Group, models.LessonRecord, models.WeekResult,
          models.CoinTransaction, models.Reward, models.Redemption]:
    admin.site.register(m)
