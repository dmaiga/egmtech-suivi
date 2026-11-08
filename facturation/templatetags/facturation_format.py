"""Présentation des montants et des dates de la facturation : {% load facturation_format %}."""

from datetime import date, datetime

from django import template
from django.utils import timezone

register = template.Library()

ESPACE_INSECABLE = " "


@register.filter
def fcfa(montant):
    """1234500 -> « 1 234 500 FCFA » (espaces insécables). Vide si ce n'est pas un entier."""
    if isinstance(montant, bool) or not isinstance(montant, int):
        return ""
    return f"{montant:,}".replace(",", ESPACE_INSECABLE) + f"{ESPACE_INSECABLE}FCFA"


@register.filter
def date_fr(valeur):
    """Date ou date-heure -> « jj/mm/aaaa » (date-heure ramenée au fuseau local). Vide sinon."""
    if isinstance(valeur, datetime):
        valeur = timezone.localtime(valeur) if timezone.is_aware(valeur) else valeur
        return valeur.strftime("%d/%m/%Y")
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    return ""
