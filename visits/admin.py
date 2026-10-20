from django.contrib import admin

from .models import Mission, Visit, VisitPhoto


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("superviseur", "site", "attached_form", "created_by", "created_at")
    list_filter = ("site__client",)
    search_fields = ("superviseur__username", "site__nom")


class VisitPhotoInline(admin.TabularInline):
    model = VisitPhoto
    extra = 0
    readonly_fields = ("field_key", "legende", "image", "created_at")


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("mission", "auteur", "statut", "date_debut", "date_soumission")
    list_filter = ("statut",)
    inlines = [VisitPhotoInline]
