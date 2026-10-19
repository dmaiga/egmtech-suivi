from django.contrib import admin

from .models import AttachedForm, ExpectedVisits, FormTemplate


@admin.register(FormTemplate)
class FormTemplateAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif", "updated_at")
    list_filter = ("actif",)
    search_fields = ("nom",)


@admin.register(AttachedForm)
class AttachedFormAdmin(admin.ModelAdmin):
    list_display = ("nom", "client", "template", "actif", "created_at")
    list_filter = ("client", "actif")
    search_fields = ("nom",)


@admin.register(ExpectedVisits)
class ExpectedVisitsAdmin(admin.ModelAdmin):
    list_display = ("site", "attached_form", "nombre_prevu")
    list_filter = ("attached_form__client",)
