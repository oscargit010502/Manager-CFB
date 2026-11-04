import io
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from core.models import AuditEvent, Case, Cost, Document, DocumentRequirement, Invoice, Partner, Procedure, ServiceItem


def sample_pdf(name="certificado.pdf"):
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/pdf")


class OperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = get_user_model().objects.create_user(username="operador", password="test-password-928")
        cls.operator.user_permissions.add(*Permission.objects.filter(codename__in=["view_case", "manage_operations"]))
        cls.reader = get_user_model().objects.create_user(username="consulta", password="test-password-928")
        cls.reader.user_permissions.add(Permission.objects.get(codename="view_case", content_type__app_label="core"))
        cls.admin = get_user_model().objects.create_superuser(username="admin", password="test-password-928", email="admin@example.test")
        cls.partner = Partner.objects.create(name="Empresa de prueba")

    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.storage.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.client.force_login(self.operator)
        self.case = Case.objects.create(deceased_name="Persona ficticia", death_date=timezone.localdate(),
            requester_name="Solicitante de prueba", payer_type="private", payer_name="Pagador de prueba", created_by=self.operator)

    def case_data(self, **updates):
        values = dict(deceased_name="Persona de prueba", deceased_id="DEMO-123", death_date=str(timezone.localdate()),
                      requester_name="Familiar de prueba", requester_phone="3000000000", payer_type="private", payer_name="Familiar de prueba")
        values.update(updates)
        return values

    def test_create_bootstraps_required_documents_and_registry_procedure(self):
        response = self.client.post(reverse("case_create"), self.case_data())
        self.assertEqual(response.status_code, 302)
        case = Case.objects.exclude(pk=self.case.pk).get()
        self.assertEqual(case.requirements.filter(required=True).count(), 2)
        self.assertEqual(case.procedures.get().entity, "registry")
        self.assertTrue(case.audit_events.filter(action="Expediente creado").exists())

    def test_company_requires_partner_but_can_start_with_pending_authorization(self):
        response = self.client.post(reverse("case_create"), self.case_data(payer_type="company"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Case.objects.count(), 1)
        response = self.client.post(reverse("case_create"), self.case_data(payer_type="company", partner=self.partner.pk))
        self.assertEqual(response.status_code, 302)
        case = Case.objects.exclude(pk=self.case.pk).get()
        self.assertEqual(case.requirements.count(), 3)

    def test_future_death_is_rejected(self):
        response = self.client.post(reverse("case_create"), self.case_data(death_date=str(timezone.localdate() + timedelta(days=1))))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Case.objects.count(), 1)

    def test_viewer_cannot_modify_operational_records(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(reverse("case_edit", args=[self.case.pk]), self.case_data()).status_code, 403)
        self.assertEqual(self.client.post(reverse("case_close", args=[self.case.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("case_detail", args=[self.case.pk])).status_code, 200)

    def test_upload_persists_pdf_and_marks_requirement_received(self):
        requirement = DocumentRequirement.objects.create(case=self.case, label="Certificado", required=True)
        response = self.client.post(reverse("document_upload", args=[self.case.pk]),
            {"title": "Certificado de prueba", "requirement": requirement.pk, "file": sample_pdf()})
        self.assertEqual(response.status_code, 302)
        document = Document.objects.get()
        self.assertEqual(document.requirement, requirement)
        self.assertTrue(document.file.storage.exists(document.file.name))
        self.assertEqual(len(document.sha256), 64)
        self.assertEqual(self.case.missing_documents, [])
        response = self.client.get(reverse("document_download", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual({part.strip() for part in response["Cache-Control"].split(",")}, {"private", "no-store"})

    def test_upload_rejects_fake_pdf_and_foreign_requirement(self):
        foreign = Case.objects.create(deceased_name="Otra persona", death_date=timezone.localdate(),
            requester_name="Otro solicitante", payer_type="private", payer_name="Otro pagador", created_by=self.operator)
        requirement = DocumentRequirement.objects.create(case=foreign, label="Otro requisito")
        response = self.client.post(reverse("document_upload", args=[self.case.pk]),
            {"title": "PDF falso", "file": SimpleUploadedFile("falso.pdf", b"<html>no pdf</html>")})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("document_upload", args=[self.case.pk]),
            {"title": "PDF ajeno", "requirement": requirement.pk, "file": sample_pdf()})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.exists())

    def test_document_download_requires_authentication(self):
        self.client.post(reverse("document_upload", args=[self.case.pk]), {"title": "Privado", "file": sample_pdf()})
        document = Document.objects.get()
        self.client.logout()
        self.assertEqual(self.client.get(reverse("document_download", args=[document.pk])).status_code, 302)

    def test_duplicate_requirement_is_form_error_not_server_error(self):
        DocumentRequirement.objects.create(case=self.case, label="Certificado")
        response = self.client.post(reverse("requirement_add", args=[self.case.pk]), {"label": "Certificado", "required": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.case.requirements.count(), 1)

    def test_service_requires_authorization_and_idempotent_explicit_state(self):
        item = ServiceItem.objects.create(case=self.case, description="Traslado", authorized=False)
        self.client.post(reverse("service_toggle", args=[item.pk]), {"performed": "1"})
        item.refresh_from_db()
        self.assertFalse(item.performed)
        item.authorized = True
        item.save()
        self.client.post(reverse("service_toggle", args=[item.pk]), {"performed": "1"})
        item.refresh_from_db()
        first_performed_at = item.performed_at
        self.client.post(reverse("service_toggle", args=[item.pk]), {"performed": "1"})
        item.refresh_from_db()
        self.assertTrue(item.performed)
        self.assertIsNotNone(item.performed_at)
        self.assertEqual(item.performed_at, first_performed_at)

    def test_company_performance_requires_case_authorization(self):
        self.case.payer_type = "company"
        self.case.partner = self.partner
        self.case.save()
        item = ServiceItem.objects.create(case=self.case, description="Traslado", authorized=True)
        self.client.post(reverse("service_toggle", args=[item.pk]), {"performed": "1"})
        item.refresh_from_db()
        self.assertFalse(item.performed)

    def test_close_requires_documents_procedures_and_service_completion(self):
        requirement = DocumentRequirement.objects.create(case=self.case, label="Certificado")
        procedure = Procedure.objects.create(case=self.case, title="Registro")
        item = ServiceItem.objects.create(case=self.case, description="Traslado", authorized=True)
        self.client.post(reverse("case_close", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "open")
        self.client.post(reverse("document_upload", args=[self.case.pk]), {"title": "Certificado", "requirement": requirement.pk, "file": sample_pdf()})
        self.client.post(reverse("procedure_update", args=[procedure.pk]), {"title": "Registro", "entity": "registry", "status": "done"})
        self.client.post(reverse("service_toggle", args=[item.pk]), {"performed": "1"})
        self.client.post(reverse("case_close", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "closed")
        self.assertTrue(self.case.audit_events.filter(action="Expediente cerrado").exists())

    def test_close_with_receivable_allowed_but_operations_immutable(self):
        ServiceItem.objects.create(case=self.case, description="Traslado", authorized=True, performed=True, performed_at=timezone.now())
        Invoice.objects.create(case=self.case, number="TEST-1", issued_on=timezone.localdate(), due_on=timezone.localdate(),
            description="Servicio", amount=Decimal("100000"), created_by=self.operator)
        self.client.post(reverse("case_close", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "closed")
        self.client.post(reverse("case_edit", args=[self.case.pk]), self.case_data(deceased_name="Cambio bloqueado"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.deceased_name, "Persona ficticia")

    def test_cancellation_requires_reason_and_no_active_costs(self):
        self.client.post(reverse("case_cancel", args=[self.case.pk]), {"reason": ""})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "open")
        Cost.objects.create(case=self.case, description="Traslado", amount=Decimal("1000"), incurred_on=timezone.localdate(), created_by=self.operator)
        self.client.post(reverse("case_cancel", args=[self.case.pk]), {"reason": "Prueba"})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "open")

    def test_status_actions_are_post_only_and_reopening_admin_only(self):
        self.assertEqual(self.client.get(reverse("case_start", args=[self.case.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("case_close", args=[self.case.pk])).status_code, 405)
        self.client.post(reverse("case_cancel", args=[self.case.pk]), {"reason": "No se requiere el servicio"})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "cancelled")
        self.assertEqual(self.client.post(reverse("case_reopen", args=[self.case.pk]), {"reason": "Corrección"}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse("case_reopen", args=[self.case.pk]), {"reason": "Se retomó el servicio"})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "open")
        self.assertTrue(self.case.audit_events.filter(action="Expediente reabierto").exists())

    def test_configuration_admin_only_and_rejects_nonimage_logo(self):
        self.assertEqual(self.client.get(reverse("company_settings")).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("company_settings"), {"name": "Casa Funeraria Baranoa", "logo": SimpleUploadedFile("fake.png", b"bad-image")})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El archivo no es una imagen válida")

    def test_partner_catalog_read_access_and_operator_edit(self):
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(reverse("partner_list")), self.partner.name)
        self.assertEqual(self.client.post(reverse("partner_edit", args=[self.partner.pk]), {"name": "Cambio no autorizado"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("partner_create")).status_code, 403)
        self.client.force_login(self.operator)
        response = self.client.post(reverse("partner_edit", args=[self.partner.pk]),
            {"name": "Empresa de prueba actualizada", "contact_name": "Contacto ficticio", "phone": "3000000000", "email": "contacto@example.test", "active": "on"})
        self.assertRedirects(response, reverse("partner_list"))
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.contact_name, "Contacto ficticio")
        self.assertTrue(AuditEvent.objects.filter(action="Empresa actualizada", actor=self.operator).exists())
        self.client.logout()
        self.assertEqual(self.client.get(reverse("partner_list")).status_code, 302)

    def test_deactivate_partner_preserves_cases_and_excludes_new_selection(self):
        self.case.payer_type = "company"
        self.case.partner = self.partner
        self.case.save()
        response = self.client.post(reverse("partner_edit", args=[self.partner.pk]), {"name": self.partner.name})
        self.assertEqual(response.status_code, 302)
        self.partner.refresh_from_db()
        self.case.refresh_from_db()
        self.assertFalse(self.partner.active)
        self.assertEqual(self.case.partner_id, self.partner.pk)
        new_form = self.client.get(reverse("case_create")).context["form"]
        self.assertFalse(new_form.fields["partner"].queryset.filter(pk=self.partner.pk).exists())
        existing_form = self.client.get(reverse("case_edit", args=[self.case.pk])).context["form"]
        self.assertTrue(existing_form.fields["partner"].queryset.filter(pk=self.partner.pk).exists())
        response = self.client.post(reverse("case_create"), self.case_data(payer_type="company", partner=self.partner.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Case.objects.count(), 1)
