from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import finance
from core.finance_forms import InvoiceForm, PaymentForm
from core.models import AuditEvent, Case, Cost, Invoice, Payment


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class FinanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser("tesoreria", "", "test-password-only-123")
        cls.viewer = get_user_model().objects.create_user("consulta", password="test-password-only-123")
        cls.today = timezone.localdate()
        cls.case = Case.objects.create(deceased_name="Persona de prueba", death_date=cls.today,
            requester_name="Solicitante de prueba", payer_type="private", payer_name="Pagador de prueba", created_by=cls.actor)

    def invoice(self, amount="100000.00", **kwargs):
        data = dict(case=self.case, actor=self.actor, amount=amount, issued_on=self.today,
            due_on=self.today + timedelta(days=30), description="Servicio funerario de prueba")
        data.update(kwargs)
        return finance.create_invoice(**data)

    def pay(self, invoice, amount="40000.00", **kwargs):
        data = dict(invoice=invoice, actor=self.actor, amount=amount, paid_on=self.today,
            method="transfer", reference="REC-PRUEBA", notes="", idempotency_key=uuid4())
        data.update(kwargs)
        return finance.register_payment(**data)

    def test_complete_collection_and_cost_workflow(self):
        invoice = self.invoice()
        self.pay(invoice)
        self.pay(invoice, "60000.00")
        finance.create_cost(case=self.case, actor=self.actor, amount="25000.50", incurred_on=self.today,
            description="Traslado de prueba", supplier="Proveedor de prueba")
        self.assertEqual(invoice.balance, Decimal("0.00"))
        self.assertEqual(self.case.billed_total, Decimal("100000.00"))
        self.assertEqual(self.case.paid_total, Decimal("100000.00"))
        self.assertEqual(self.case.cost_total, Decimal("25000.50"))
        self.assertEqual(self.case.margin, Decimal("74999.50"))
        self.assertEqual(AuditEvent.objects.filter(case=self.case).count(), 4)

    def test_rejects_overpayment_without_writing_or_auditing(self):
        invoice = self.invoice()
        self.pay(invoice, "90000.00")
        count = AuditEvent.objects.count()
        with self.assertRaises(ValidationError):
            self.pay(invoice, "10000.01")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), count)
        self.assertEqual(invoice.balance, Decimal("10000.00"))

    def test_repeat_payment_is_idempotent_and_mismatched_repeat_rejected(self):
        invoice = self.invoice()
        key = uuid4()
        first = self.pay(invoice, idempotency_key=key)
        again = self.pay(invoice, idempotency_key=key)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="Abono registrado").count(), 1)
        with self.assertRaises(ValidationError):
            self.pay(invoice, "100.00", idempotency_key=key)
        second_invoice = self.invoice()
        with self.assertRaises(ValidationError):
            self.pay(second_invoice, idempotency_key=key)

    def test_void_retains_records_and_requires_abons_to_be_voided_first(self):
        invoice = self.invoice()
        payment = self.pay(invoice)
        with self.assertRaises(ValidationError):
            finance.void_invoice(invoice=invoice, actor=self.actor, reason="Corrección del valor")
        finance.void_payment(payment=payment, actor=self.actor, reason="Duplicado en digitación")
        self.assertEqual(invoice.balance, Decimal("100000.00"))
        finance.void_invoice(invoice=invoice, actor=self.actor, reason="Corrección del valor")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "void")
        self.assertEqual(self.case.billed_total, Decimal("0.00"))
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.pay(invoice)
        with self.assertRaises(ValidationError):
            finance.void_payment(payment=payment, actor=self.actor, reason="Reintento de anulación")

    def test_cost_void_changes_totals_and_preserves_reason(self):
        cost = finance.create_cost(case=self.case, actor=self.actor, amount="20000.00", incurred_on=self.today,
            description="Traslado", supplier="Proveedor")
        with self.assertRaises(ValidationError):
            finance.void_cost(cost=cost, actor=self.actor, reason="")
        finance.void_cost(cost=cost, actor=self.actor, reason="Proveedor corrigió su cuenta")
        cost.refresh_from_db()
        self.assertTrue(cost.voided)
        self.assertEqual(self.case.cost_total, Decimal("0.00"))
        self.assertEqual(Cost.objects.count(), 1)

    def test_rejects_invalid_amounts(self):
        for amount in ("0", "-1", "1.001", "NaN", "Infinity", "1000000000000", "incorrecto"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.invoice(amount)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_dates_are_validated(self):
        with self.assertRaises(ValidationError):
            self.invoice(due_on=self.today - timedelta(days=1))
        with self.assertRaises(ValidationError):
            self.invoice(issued_on=self.today + timedelta(days=1))
        invoice = self.invoice()
        for paid_on in (self.today - timedelta(days=1), self.today + timedelta(days=1)):
            with self.subTest(paid_on=paid_on), self.assertRaises(ValidationError):
                self.pay(invoice, paid_on=paid_on)
        with self.assertRaises(ValidationError):
            finance.create_cost(case=self.case, actor=self.actor, amount="100", incurred_on=self.today + timedelta(days=1), description="Prueba")

    def test_closed_case_allows_collection_and_reversal_but_not_new_invoice_or_cost(self):
        invoice = self.invoice()
        self.case.status = "closed"
        self.case.save()
        payment = self.pay(invoice)
        finance.void_payment(payment=payment, actor=self.actor, reason="Corrección de referencia")
        self.assertEqual(invoice.balance, Decimal("100000.00"))
        with self.assertRaises(ValidationError):
            self.invoice()
        with self.assertRaises(ValidationError):
            finance.create_cost(case=self.case, actor=self.actor, amount="100", incurred_on=self.today, description="Prueba")

    def test_cancelled_case_rejects_collection(self):
        invoice = self.invoice()
        self.case.status = "cancelled"
        self.case.save()
        with self.assertRaises(ValidationError):
            self.pay(invoice)

    def test_services_enforce_finance_permission(self):
        with self.assertRaises(PermissionDenied):
            self.invoice(actor=self.viewer)
        invoice = self.invoice()
        with self.assertRaises(PermissionDenied):
            self.pay(invoice, actor=self.viewer)
        self.assertEqual(Payment.objects.count(), 0)

    def test_forms_accept_centavos_and_reject_extra_decimals(self):
        form = InvoiceForm(data={"amount": "0.01", "issued_on": self.today, "due_on": self.today, "description": "Prueba"})
        self.assertTrue(form.is_valid(), form.errors)
        form = PaymentForm(data={"amount": "1.001", "paid_on": self.today, "method": "cash", "idempotency_key": uuid4()})
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_views_require_login_and_finance_permission(self):
        url = reverse("invoice_create", kwargs={"case_id": self.case.pk})
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_get_confirmation_is_read_only_and_post_creates_invoice(self):
        self.client.force_login(self.actor)
        url = reverse("invoice_create", kwargs={"case_id": self.case.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(Invoice.objects.count(), 0)
        response = self.client.post(url, {"amount": "120000.00", "issued_on": self.today,
            "due_on": self.today, "description": "Servicio"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invoice.objects.count(), 1)
        invoice = Invoice.objects.get()
        url = reverse("invoice_void", kwargs={"invoice_id": invoice.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "issued")
        self.client.post(url, {"reason": "Corrección del expediente"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "void")

    def test_financial_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        url = reverse("invoice_create", kwargs={"case_id": self.case.pk})
        response = client.post(url, {"amount": "120000", "issued_on": self.today, "due_on": self.today, "description": "Servicio"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Invoice.objects.count(), 0)
