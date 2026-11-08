from django.contrib import admin

from .models import ContactClient, ProfilEmetteur


@admin.register(ProfilEmetteur)
class ProfilEmetteurAdmin(admin.ModelAdmin):
    # Logo et cachet se gèrent dans l'application (conversion PNG, accès protégé) :
    # l'admin les exposerait par un lien direct et sans conversion.
    exclude = ("logo", "cachet")

    def has_add_permission(self, request):
        return not ProfilEmetteur.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ContactClient)
class ContactClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "telephone", "email", "actif", "created_at")
    list_filter = ("actif",)
    search_fields = ("nom", "telephone", "email")

    def has_delete_permission(self, request, obj=None):
        return False
