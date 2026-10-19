from .models import ActivityLog


def log(user, action, obj, detail=None):
    """Enregistre une entrée dans le journal d'activité."""

    return ActivityLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        detail=detail or {},
    )
