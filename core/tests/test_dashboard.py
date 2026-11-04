from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Case, Cost, DocumentRequirement, Invoice, Partner, Payment, Procedure
from core.templatetags.cfb import money


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser("admin-ui", "", "test-only-long-password")
        cls.viewer = get_user_model().objects.create_user("consulta-ui", password="test-only-long-password")
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_case"))
        cls.unprivileged = get_user_model().objects.create_user("sin-permisos", password="test-only-long-password")
        cls.today = timezone.localdate()
        cls.case = Case.objects.create(deceased_name="Nombre ficticio", deceased_id="123456", death_date=cls.today,
            requester_name="Solicitante de prueba", payer_name="Pagador ficticio", payer_type="private", created_by=cls.actor)

    def test_login_and_read_permissions_required(self):
        for name in ("dashboard", "case_list"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)
                self.client.force_login(self.unprivileged)
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
                self.client.logout()

    def test_viewer_sees_data_without_mutation_links(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Nombre ficticio")
        self.assertContains(response, "Cambiar contraseña")
        self.assertNotContains(response, reverse("case_create"))
        self.assertNotContains(response, reverse("company_settings"))
        self.assertEqual(response.context["active_cases"], 1)

    def test_dashboard_uses_current_financial_totals_and_overdue_balances(self):
        invoice = Invoice.objects.create(case=self.case, number="UI-001", description="Servicio",
            amount="120000.50", issued_on=self.today-timedelta(days=10), due_on=self.today-timedelta(days=1), created_by=self.actor)
        Payment.objects.create(invoice=invoice, amount="20000.25", paid_on=self.today, method="cash", created_by=self.actor)
        Payment.objects.create(invoice=invoice, amount="10000.00", paid_on=self.today, method="cash", created_by=self.actor,
            voided=True, void_reason="Corrección de prueba")
        Invoice.objects.create(case=self.case, number="UI-002", description="Anulada", amount="99999.00",
            issued_on=self.today-timedelta(days=3), due_on=self.today-timedelta(days=2), created_by=self.actor,
            status="void", void_reason="Corrección de prueba")
        Cost.objects.create(case=self.case, description="Traslado", amount="15000.00", incurred_on=self.today, created_by=self.actor)
        Cost.objects.create(case=self.case, description="Anulado", amount="9000.00", incurred_on=self.today, created_by=self.actor,
            voided=True, void_reason="Corrección de prueba")
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["billed_total"], Decimal("120000.50"))
        self.assertEqual(response.context["paid_total"], Decimal("20000.25"))
        self.assertEqual(response.context["balance_total"], Decimal("100000.25"))
        self.assertEqual(response.context["cost_total"], Decimal("15000.00"))
        self.assertEqual(response.context["margin_total"], Decimal("105000.50"))
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["overdue_total"], Decimal("100000.25"))
        self.assertContains(response, "$ 100.000,25")

    def test_pending_counts_exclude_closed_cases_and_optional_documents(self):
        closed = Case.objects.create(deceased_name="Otro ficticio", death_date=self.today, requester_name="Prueba",
            payer_type="private", payer_name="Prueba", created_by=self.actor, status="closed")
        for case in (self.case, closed):
            Procedure.objects.create(case=case, title="Registro civil", status="pending")
            DocumentRequirement.objects.create(case=case, label="Certificado", required=True)
        DocumentRequirement.objects.create(case=self.case, label="Opcional", required=False)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["pending_procedures"], 1)
        self.assertEqual(response.context["missing_documents"], 1)
        self.assertEqual(response.context["cases_missing_documents"], 1)

    def test_search_by_deceased_document_requester_payer_or_case_code(self):
        self.client.force_login(self.viewer)
        for query in ("Nombre ficticio", "123456", "Solicitante", "Pagador", self.case.code):
            with self.subTest(query=query):
                response = self.client.get(reverse("case_list"), {"q": query})
                self.assertEqual(list(response.context["cases"]), [self.case])
        self.assertContains(self.client.get(reverse("case_list"), {"q": "No existe"}), "No encontramos coincidencias")

    def test_company_search_and_filters(self):
        partner = Partner.objects.create(name="Exequial de prueba")
        company_case = Case.objects.create(deceased_name="Ficticio empresa", death_date=self.today-timedelta(days=1),
            requester_name="Prueba", payer_type="company", partner=partner, payer_name="Exequial", created_by=self.actor,
            authorization_number="AUT-PRUEBA", status="in_progress")
        self.client.force_login(self.viewer)
        for query in ("Exequial de prueba", "AUT-PRUEBA"):
            response = self.client.get(reverse("case_list"), {"q": query})
            self.assertEqual(list(response.context["cases"]), [company_case])
        response = self.client.get(reverse("case_list"), {"payer": "company", "status": "active"})
        self.assertEqual(list(response.context["cases"]), [company_case])
        response = self.client.get(reverse("case_list"), {"after": self.today.isoformat()})
        self.assertEqual(list(response.context["cases"]), [self.case])
        response = self.client.get(reverse("case_list"), {"before": (self.today-timedelta(days=1)).isoformat()})
        self.assertEqual(list(response.context["cases"]), [company_case])
        response = self.client.get(reverse("case_list"), {"after": "not-a-date"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa una fecha válida")

    def test_pagination_preserves_search_filters(self):
        for number in range(22):
            Case.objects.create(deceased_name=f"Persona {number}", death_date=self.today, requester_name="Prueba",
                payer_type="private", payer_name="Prueba", created_by=self.actor)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("case_list"), {"q": "Persona", "payer": "private"})
        self.assertEqual(len(response.context["cases"]), 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 22)
        self.assertContains(response, "q=Persona&amp;payer=private&amp;page=2")
        response = self.client.get(reverse("case_list"), {"q": "Persona", "payer": "private", "page": 2})
        self.assertEqual(len(response.context["cases"]), 2)

    def test_stored_html_escaped_in_views(self):
        self.case.deceased_name = "<script>alert('x')</script>"
        self.case.save()
        self.client.force_login(self.viewer)
        for name in ("dashboard", "case_list"):
            response = self.client.get(reverse(name))
            self.assertContains(response, "&lt;script&gt;")
            self.assertNotContains(response, "<script>alert")

    def test_password_change_templates_render(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("password_change")), "Guardar contraseña")
        self.assertContains(self.client.get(reverse("password_change_done")), "Contraseña actualizada")

    def test_colombian_money_format(self):
        self.assertEqual(money(Decimal("1234567.89")), "$ 1.234.567,89")
        self.assertEqual(money(Decimal("-1000.01")), "$ -1.000,01")
        self.assertEqual(money(None), "$ 0,00")
        self.assertEqual(money("NaN"), "—")
