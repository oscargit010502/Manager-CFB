from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Case, Company, Document, DocumentRequirement, Partner, Procedure, ServiceItem


class SpanishModelForm(forms.ModelForm):
    """Consistent date controls and accessible, server-validated form inputs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("rows", 3)


class CaseForm(SpanishModelForm):
    class Meta:
        model = Case
        fields = [
            "deceased_name", "deceased_id", "birth_date", "death_date",
            "requester_name", "requester_id", "requester_phone", "requester_relationship",
            "payer_type", "partner", "payer_name", "authorization_number", "authorized_by",
            "authorized_on", "authorization_notes", "service_location", "notes",
        ]
        labels = {
            "deceased_name": "Nombre completo de la persona fallecida", "deceased_id": "Documento de identidad",
            "birth_date": "Fecha de nacimiento", "death_date": "Fecha de fallecimiento",
            "requester_name": "Nombre de quien solicita", "requester_id": "Documento del solicitante",
            "requester_phone": "Teléfono de contacto", "requester_relationship": "Parentesco o relación",
            "payer_type": "Tipo de pagador", "partner": "Empresa exequial", "payer_name": "Nombre del responsable de pago",
            "authorization_number": "Número de autorización", "authorized_by": "Persona que autoriza",
            "authorized_on": "Fecha de autorización", "authorization_notes": "Alcance de la autorización",
            "service_location": "Lugar del servicio", "notes": "Observaciones del expediente",
        }
        help_texts = {
            "payer_name": "Nombre de la empresa o particular responsable del pago.",
            "authorization_number": "Puede completarse después; es obligatorio para cerrar servicios de empresas.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["partner"].queryset = Partner.objects.filter(active=True)
        if self.instance.pk and self.instance.partner_id:
            from django.db.models import Q
            self.fields["partner"].queryset = Partner.objects.filter(Q(active=True) | Q(pk=self.instance.partner_id))

    def clean(self):
        data = super().clean()
        if data.get("payer_type") == "company" and not data.get("partner"):
            self.add_error("partner", "Selecciona la empresa que autoriza este servicio.")
        if data.get("payer_type") == "private" and data.get("partner"):
            self.add_error("partner", "Un servicio particular no debe tener empresa exequial.")
        if data.get("death_date") and data["death_date"] > timezone.localdate():
            self.add_error("death_date", "La fecha de fallecimiento no puede ser futura.")
        if data.get("birth_date") and data.get("death_date") and data["birth_date"] > data["death_date"]:
            self.add_error("birth_date", "El nacimiento no puede ser posterior al fallecimiento.")
        return data


class ServiceItemForm(SpanishModelForm):
    class Meta:
        model = ServiceItem
        fields = ["description", "quantity", "unit_price", "authorized", "notes"]
        labels = {"description": "Servicio o concepto", "quantity": "Cantidad", "unit_price": "Valor unitario (COP)",
                  "authorized": "Servicio autorizado", "notes": "Observaciones"}


class ProcedureForm(SpanishModelForm):
    class Meta:
        model = Procedure
        fields = ["title", "entity", "status", "reference", "due_on", "completed_on", "notes"]
        labels = {"title": "Nombre del trámite", "entity": "Entidad", "status": "Estado", "reference": "Número de radicado",
                  "due_on": "Fecha límite", "completed_on": "Fecha de finalización", "notes": "Observaciones"}

    def clean(self):
        data = super().clean()
        if data.get("status") == "done" and not data.get("completed_on"):
            data["completed_on"] = timezone.localdate()
        elif data.get("status") != "done" and data.get("completed_on"):
            self.add_error("completed_on", "Solo un trámite finalizado puede tener fecha de finalización.")
        if data.get("completed_on") and data["completed_on"] > timezone.localdate():
            self.add_error("completed_on", "La finalización no puede ser futura.")
        return data


class RequirementForm(SpanishModelForm):
    class Meta:
        model = DocumentRequirement
        fields = ["label", "required"]
        labels = {"label": "Documento esperado", "required": "Obligatorio para cerrar el expediente"}

    def clean_label(self):
        label = self.cleaned_data["label"]
        if self.instance.case_id and DocumentRequirement.objects.filter(case_id=self.instance.case_id, label=label).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Este requisito ya existe en el expediente.")
        return label


class DocumentForm(SpanishModelForm):
    class Meta:
        model = Document
        fields = ["title", "requirement", "file"]
        labels = {"title": "Descripción del archivo", "requirement": "Requisito que acredita", "file": "Archivo PDF"}
        help_texts = {"file": "PDF legible, sin contraseña, máximo 10 MB. Se conserva como documento privado."}
        widgets = {"file": forms.FileInput(attrs={"accept": ".pdf,application/pdf"})}

    def __init__(self, *args, case, **kwargs):
        kwargs.setdefault("instance", Document(case=case))
        super().__init__(*args, **kwargs)
        self.fields["requirement"].queryset = DocumentRequirement.objects.filter(case=case)
        self.metadata = None

    def clean_file(self):
        from .documents import validate_pdf
        file = self.cleaned_data["file"]
        self.metadata = validate_pdf(file)
        file.seek(0)
        return file


class PartnerForm(SpanishModelForm):
    class Meta:
        model = Partner
        fields = ["name", "contact_name", "phone", "email", "active"]
        labels = {"name": "Nombre de la empresa", "contact_name": "Persona de contacto", "phone": "Teléfono",
                  "email": "Correo electrónico", "active": "Empresa activa"}


class CompanyForm(SpanishModelForm):
    class Meta:
        model = Company
        fields = ["name", "legal_name", "tax_id", "address", "phone", "email", "bank_details", "logo"]
        labels = {"name": "Nombre comercial", "legal_name": "Razón social", "tax_id": "NIT", "address": "Dirección",
                  "phone": "Teléfono", "email": "Correo electrónico", "bank_details": "Información bancaria", "logo": "Logo"}
        help_texts = {"logo": "PNG o JPEG, máximo 2 MB.", "bank_details": "Registra únicamente las cuentas reales de la empresa."}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if not logo or "logo" not in self.changed_data:
            return logo
        if logo.size > 2 * 1024 * 1024:
            raise ValidationError("El logo no puede superar 2 MB.")
        from PIL import Image, UnidentifiedImageError
        try:
            image = Image.open(logo)
            if image.format not in ("PNG", "JPEG") or image.width * image.height > 20_000_000:
                raise ValidationError("Usa un logo PNG o JPEG de máximo 20 megapíxeles.")
            image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError("El archivo no es una imagen válida.")
        finally:
            logo.seek(0)
        return logo


class ReasonForm(forms.Form):
    reason = forms.CharField(label="Motivo", max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
