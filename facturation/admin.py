from django.contrib import admin

from . import services
from .models import ContactClient, Document, HistoriqueStatut, LigneDocument, Produit, ProfilEmetteur, SequenceNumero


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


class LectureSeuleMixin:
    """Consultation uniquement : ni ajout, ni modification, ni suppression."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("designation", "prix_unitaire", "actif")
    list_filter = ("actif",)
    search_fields = ("designation",)

    def has_delete_permission(self, request, obj=None):
        return False


class LigneDocumentInline(LectureSeuleMixin, admin.TabularInline):
    # Les lignes passent par les services (rang, total de ligne, totaux du document).
    model = LigneDocument
    fields = ("rang", "designation", "quantite", "prix_unitaire", "total", "produit")
    readonly_fields = fields
    extra = 0


class HistoriqueStatutInline(LectureSeuleMixin, admin.TabularInline):
    model = HistoriqueStatut
    fields = ("date", "ancien_statut", "nouveau_statut", "utilisateur")
    readonly_fields = fields
    extra = 0


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "type", "statut", "contact_nom", "total_ttc", "date_emission")
    list_filter = ("type", "statut")
    search_fields = ("numero", "contact_nom", "objet")
    inlines = [LigneDocumentInline, HistoriqueStatutInline]
    # Statut, numéro, totaux et dates ne changent que par les services (transitions, émission).
    readonly_fields = (
        "type", "numero", "statut", "contact_nom", "contact_telephone", "contact_adresse",
        "date_emission", "date_validite", "total_ht", "total_tva", "total_ttc", "source",
        "cree_par", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and not obj.est_brouillon:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        champs = {champ: form.cleaned_data[champ] for champ in form.changed_data
                  if champ in services.CHAMPS_BROUILLON_MODIFIABLES}
        if champs:
            services.modifier_brouillon(obj, request.user, **champs)


@admin.register(SequenceNumero)
class SequenceNumeroAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ("type", "annee", "dernier")


@admin.register(HistoriqueStatut)
class HistoriqueStatutAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ("document", "ancien_statut", "nouveau_statut", "date", "utilisateur")
    list_filter = ("nouveau_statut",)
