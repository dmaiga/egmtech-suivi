from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    """Journal d'activité, en lecture seule dans l'admin. Ne pas modifier a posteriori."""

    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        # Historique d'une visite affiché à chaque ouverture du détail.
        indexes = [models.Index(fields=["object_type", "object_id"], name="activitylog_objet_idx")]

    def __str__(self):
        return f"{self.action} - {self.object_type}#{self.object_id}"
