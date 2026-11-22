from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import PhoneLoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html", authentication_form=PhoneLoginForm,
                                                redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("students/", views.students, name="students"),
    path("students/new/", views.student_edit, name="student_new"),
    path("students/<int:pk>/", views.profile, name="student_profile"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("teachers/", views.teachers, name="teachers"),
    path("teachers/new/", views.teacher_edit, name="teacher_new"),
    path("teachers/<int:pk>/edit/", views.teacher_edit, name="teacher_edit"),
    path("groups/", views.groups, name="groups"),
    path("groups/new/", views.group_edit, name="group_new"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:pk>/journal/", views.journal, name="journal"),
    path("delete/<str:kind>/<int:pk>/", views.delete_object, name="delete"),
    path("users/<int:pk>/toggle/", views.toggle_active, name="toggle_active"),
    path("catalog/", views.catalog, name="catalog"),
    path("catalog/course/<int:pk>/", views.course_edit, name="course_edit"),
    path("catalog/branch/<int:pk>/", views.branch_edit, name="branch_edit"),
    path("rewards/", views.rewards, name="rewards"),
    path("rewards/new/", views.reward_edit, name="reward_new"),
    path("rewards/<int:pk>/edit/", views.reward_edit, name="reward_edit"),
    path("coins/give/", views.give_coins, name="give_coins"),
    path("coins/history/", views.transactions, name="transactions"),
    path("redemptions/", views.redemptions, name="redemptions"),
]
