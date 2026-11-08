"""Exceptions métier de la facturation : le message est destiné à l'utilisateur."""


class ErreurFacturation(Exception):
    """Règle métier de la facturation non respectée."""


class MontantInvalide(ErreurFacturation):
    """Quantité, prix ou taux hors des règles (entier, bornes, multiple de 5)."""


class DocumentNonModifiable(ErreurFacturation):
    """Le document n'est plus un brouillon : ni lui ni ses lignes ne changent, il ne se supprime pas."""


class TransitionInterdite(ErreurFacturation):
    """Changement de statut non prévu par le cycle de vie du document."""


class ConversionImpossible(ErreurFacturation):
    """Le devis ne peut pas (ou plus) donner de facture."""
