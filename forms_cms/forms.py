import json

from django import forms

from .models import FormTemplate
from .schema import validate_schema


class FormTemplateImportForm(forms.ModelForm):
    schema_json = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 16, "class": "font-mono text-xs"}),
        label="Schéma (JSON)",
    )

    class Meta:
        model = FormTemplate
        fields = ["nom", "description"]

    def clean_schema_json(self):
        raw = self.cleaned_data["schema_json"]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"JSON invalide : {exc}")

        errors = validate_schema(data)
        if errors:
            raise forms.ValidationError(errors)
        return data

    def save(self, commit=True):
        self.instance.schema = self.cleaned_data["schema_json"]
        return super().save(commit=commit)
