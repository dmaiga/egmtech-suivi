from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Rôle et client", {"fields": ("role", "client")}),
    )
    list_display = ("username", "email", "role", "client", "is_staff", "is_superuser", "is_active")
    list_filter = BaseUserAdmin.list_filter + ("role", "client")
