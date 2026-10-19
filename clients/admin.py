from django.contrib import admin

from .models import Client, Site


class SiteInline(admin.TabularInline):
    model = Site
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif")
    list_filter = ("actif",)
    search_fields = ("nom",)
    inlines = [SiteInline]


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "client", "ville")
    list_filter = ("client",)
    search_fields = ("nom", "code", "ville")
