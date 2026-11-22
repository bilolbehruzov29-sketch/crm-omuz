from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """roles: 'admin', 'teacher', 'student'. Админ (superuser) проходит всегда."""
    def deco(view):
        @login_required
        @wraps(view)
        def wrapper(request, *a, **kw):
            u = request.user
            if u.is_admin or u.role in roles:
                return view(request, *a, **kw)
            raise PermissionDenied
        return wrapper
    return deco


def visible_groups(user):
    from .models import Group
    qs = Group.objects.select_related("course", "branch").prefetch_related("teachers", "students")
    if user.is_admin:
        return qs
    if user.is_teacher:
        return qs.filter(teachers=user)
    return qs.filter(students=user)


def visible_students(user):
    from .models import User
    qs = User.objects.filter(role=User.Role.STUDENT, is_superuser=False)
    if user.is_admin:
        return qs
    if user.is_teacher:
        return qs.filter(study_groups__teachers=user).distinct()
    return qs.filter(pk=user.pk)


def can_edit_group(user, group):
    return user.is_admin or (user.is_teacher and group.teachers.filter(pk=user.pk).exists())
