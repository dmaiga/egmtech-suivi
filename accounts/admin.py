from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Rôle", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "role", "is_staff", "is_superuser", "is_active")
    list_filter = BaseUserAdmin.list_filter + ("role",)
