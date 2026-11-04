"""Atomic financial commands: posted records are retained and corrected by voiding."""
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Case, Cost, Invoice, Payment


ZERO = Decimal("0.00")


def _authorize(actor):
    if not actor or not actor.is_active or not actor.has_perm("core.manage_finance"):
        raise PermissionDenied("No tiene permiso para gestionar movimientos financieros.")


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Ingrese un valor monetario válido.")
    if not amount.is_finite() or amount <= ZERO:
        raise ValidationError("El valor debe ser mayor que cero.")
    if amount > Decimal("999999999999.99") or amount != amount.quantize(Decimal("0.01")):
        raise ValidationError("El valor admite hasta doce enteros y dos decimales.")
    return amount.quantize(Decimal("0.01"))


def _date(value, label, allow_future=False):
    if not isinstance(value, date):
        raise ValidationError(f"{label}: ingrese una fecha válida.")
    if not allow_future and value > timezone.localdate():
        raise ValidationError(f"{label}: la fecha no puede ser futura.")
    return value


def _writable(case, *, collection=False):
    blocked = ("cancelled",) if collection else ("closed", "cancelled")
    if case.status in blocked:
        raise ValidationError("Reabra el expediente antes de registrar o anular movimientos.")


def _reason(value):
    value = str(value or "").strip()
    if len(value) < 5:
        raise ValidationError("Explique el motivo de la anulación (mínimo 5 caracteres).")
    return value


def _audit(case, actor, action, detail):
    AuditEvent.objects.create(case=case, actor=actor, action=action, detail=detail)


def _lock_invoice(invoice):
    # All commands use the same lock order: case, then invoice.
    case_id = Invoice.objects.values_list("case_id", flat=True).get(pk=invoice.pk)
    case = Case.objects.select_for_update().get(pk=case_id)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    return case, invoice


@transaction.atomic
def create_invoice(*, case, actor, amount, issued_on, due_on, description):
    _authorize(actor)
    case = Case.objects.select_for_update().get(pk=case.pk)
    _writable(case)
    amount = _amount(amount)
    _date(issued_on, "Emisión")
    _date(due_on, "Vencimiento", allow_future=True)
    if due_on < issued_on:
        raise ValidationError("El vencimiento no puede ser anterior a la emisión.")
    description = str(description or "").strip()
    if not description:
        raise ValidationError("Describa el concepto facturado.")
    # This is an internal reference, not DIAN resolution/authorized numbering.
    number = f"CFB-{issued_on:%Y%m%d}-{uuid4().hex[:16].upper()}"
    invoice = Invoice.objects.create(case=case, created_by=actor, number=number,
        amount=amount, issued_on=issued_on, due_on=due_on, description=description,
        status="issued")
    _audit(case, actor, "Factura registrada", f"{invoice.number}: COP {amount}.")
    return invoice


@transaction.atomic
def register_payment(*, invoice, actor, amount, paid_on, method, reference="", notes="", idempotency_key=None):
    _authorize(actor)
    amount = _amount(amount)
    try:
        key = UUID(str(idempotency_key)) if idempotency_key else uuid4()
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("Identificador de pago inválido; vuelva a abrir el formulario.")
    case, invoice = _lock_invoice(invoice)
    reference, notes = str(reference or "").strip(), str(notes or "").strip()
    existing = Payment.objects.filter(idempotency_key=key).first()
    if existing:
        if (existing.invoice_id, existing.amount, existing.paid_on, existing.method,
                existing.reference, existing.notes) != (invoice.pk, amount, paid_on, method, reference, notes):
            raise ValidationError("El identificador ya corresponde a otro pago. Abra un formulario nuevo.")
        return existing
    _writable(case, collection=True)
    if invoice.status != "issued":
        raise ValidationError("No se pueden abonar facturas anuladas.")
    _date(paid_on, "Fecha de pago")
    if paid_on < invoice.issued_on:
        raise ValidationError("El pago no puede ser anterior a la emisión de la factura.")
    if amount > invoice.balance:
        raise ValidationError("El abono supera el saldo pendiente de la factura.")
    payment = Payment.objects.create(invoice=invoice, created_by=actor, amount=amount,
        paid_on=paid_on, method=method, reference=reference, notes=notes, idempotency_key=key)
    _audit(case, actor, "Abono registrado", f"Abono #{payment.pk}, {invoice.number}: COP {amount}.")
    return payment


@transaction.atomic
def void_invoice(*, invoice, actor, reason):
    _authorize(actor)
    case, invoice = _lock_invoice(invoice)
    _writable(case)
    reason = _reason(reason)
    if invoice.status == "void":
        raise ValidationError("La factura ya está anulada.")
    if invoice.payments.filter(voided=False).exists():
        raise ValidationError("Primero anule los abonos activos de esta factura.")
    invoice.status, invoice.void_reason = "void", reason
    invoice.save(update_fields=("status", "void_reason"))
    _audit(case, actor, "Factura anulada", f"{invoice.number}: {reason}")
    return invoice


@transaction.atomic
def void_payment(*, payment, actor, reason):
    _authorize(actor)
    case, invoice = _lock_invoice(payment.invoice)
    _writable(case, collection=True)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    reason = _reason(reason)
    if payment.voided:
        raise ValidationError("El abono ya está anulado.")
    payment.voided, payment.void_reason = True, reason
    payment.save(update_fields=("voided", "void_reason"))
    _audit(case, actor, "Abono anulado", f"Abono #{payment.pk}, {invoice.number}: {reason}")
    return payment


@transaction.atomic
def create_cost(*, case, actor, amount, incurred_on, description, supplier=""):
    _authorize(actor)
    case = Case.objects.select_for_update().get(pk=case.pk)
    _writable(case)
    amount = _amount(amount)
    _date(incurred_on, "Fecha del costo")
    description = str(description or "").strip()
    if not description:
        raise ValidationError("Describa el costo del servicio.")
    cost = Cost.objects.create(case=case, created_by=actor, amount=amount,
        incurred_on=incurred_on, description=description, supplier=str(supplier or "").strip())
    _audit(case, actor, "Costo registrado", f"Costo #{cost.pk}: COP {amount}; {description}.")
    return cost


@transaction.atomic
def void_cost(*, cost, actor, reason):
    _authorize(actor)
    case = Case.objects.select_for_update().get(pk=cost.case_id)
    _writable(case)
    cost = Cost.objects.select_for_update().get(pk=cost.pk)
    reason = _reason(reason)
    if cost.voided:
        raise ValidationError("El costo ya está anulado.")
    cost.voided, cost.void_reason = True, reason
    cost.save(update_fields=("voided", "void_reason"))
    _audit(case, actor, "Costo anulado", f"Costo #{cost.pk}: {reason}")
    return cost
