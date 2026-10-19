from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import ActivityLog
from .services import log

User = get_user_model()


class ActivityLogHelperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="manager1", password="pass12345", role="manager")

    def test_log_creates_entry_with_expected_fields(self):
        entry = log(self.user, "validation", self.user, detail={"note": "ok"})

        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.action, "validation")
        self.assertEqual(entry.object_type, "User")
        self.assertEqual(entry.object_id, str(self.user.pk))
        self.assertEqual(entry.detail, {"note": "ok"})

    def test_log_without_detail_defaults_to_empty_dict(self):
        entry = log(self.user, "creation", self.user)
        self.assertEqual(entry.detail, {})

    def test_log_with_anonymous_user_stores_null_user(self):
        from django.contrib.auth.models import AnonymousUser

        entry = log(AnonymousUser(), "creation", self.user)
        self.assertIsNone(entry.user)
