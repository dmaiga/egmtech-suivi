import copy

from core.services import log

from .models import AttachedForm, ExpectedVisits


def attach_template_to_client(user, client, template):
    """Attache `template` à `client` en copiant son schéma au moment présent."""

    attached = AttachedForm.objects.create(
        client=client,
        template=template,
        nom=template.nom,
        schema=copy.deepcopy(template.schema),
    )
    log(user, "attachement_formulaire", attached, detail={"client_id": client.pk, "template_id": template.pk})
    return attached


def toggle_attached_form(user, attached_form):
    attached_form.actif = not attached_form.actif
    attached_form.save(update_fields=["actif"])
    action = "activation_formulaire_attache" if attached_form.actif else "desactivation_formulaire_attache"
    log(user, action, attached_form, detail={"client_id": attached_form.client_id})
    return attached_form


def set_expected_visits(user, attached_form, site, nombre_prevu):
    """Crée ou met à jour le nombre de visites prévues pour un site, en journalisant le changement."""

    expected, created = ExpectedVisits.objects.get_or_create(
        site=site, attached_form=attached_form, defaults={"nombre_prevu": nombre_prevu}
    )
    if created:
        log(
            user,
            "creation_prevision_visites",
            expected,
            detail={"site_id": site.pk, "attached_form_id": attached_form.pk, "nombre_prevu": nombre_prevu},
        )
        return expected

    if expected.nombre_prevu != nombre_prevu:
        ancien = expected.nombre_prevu
        expected.nombre_prevu = nombre_prevu
        expected.save(update_fields=["nombre_prevu"])
        log(
            user,
            "modification_prevision_visites",
            expected,
            detail={
                "site_id": site.pk,
                "attached_form_id": attached_form.pk,
                "ancien": ancien,
                "nouveau": nombre_prevu,
            },
        )
    return expected
