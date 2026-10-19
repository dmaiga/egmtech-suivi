from django.contrib.auth.mixins import UserPassesTestMixin


class ManageFormsRequiredMixin(UserPassesTestMixin):
    """Équivalent class-based view de forms_cms.decorators.manage_forms_required."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.has_perm("forms_cms.manage_forms"))
