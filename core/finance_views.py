from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import finance
from .finance_forms import CostForm, InvoiceForm, PaymentForm, VoidForm
from .models import Case, Cost, Invoice, Payment


def _finance_form(request, *, case, form_class, title, submit, command, entry=None, warning=""):
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            command(**form.cleaned_data)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(request, "Movimiento guardado y registrado en el historial.")
            return redirect("case_detail", pk=case.pk)
    return render(request, "core/finance_form.html", {"form": form, "case": case,
        "title": title, "submit_label": submit, "entry": entry, "warning": warning})


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def invoice_create(request, case_id):
    case = get_object_or_404(Case, pk=case_id)
    return _finance_form(request, case=case, form_class=InvoiceForm, title="Registrar factura", submit="Registrar factura",
        warning="Registro administrativo interno. No emite una factura electrónica validada por la DIAN.",
        command=lambda **data: finance.create_invoice(case=case, actor=request.user, **data))


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def payment_create(request, invoice_id):
    invoice = get_object_or_404(Invoice.objects.select_related("case"), pk=invoice_id)
    return _finance_form(request, case=invoice.case, entry=invoice, form_class=PaymentForm,
        title=f"Registrar abono · {invoice.number}", submit="Registrar abono",
        command=lambda **data: finance.register_payment(invoice=invoice, actor=request.user, **data))


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def cost_create(request, case_id):
    case = get_object_or_404(Case, pk=case_id)
    return _finance_form(request, case=case, form_class=CostForm, title="Registrar costo", submit="Registrar costo",
        command=lambda **data: finance.create_cost(case=case, actor=request.user, **data))


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def invoice_void(request, invoice_id):
    invoice = get_object_or_404(Invoice.objects.select_related("case"), pk=invoice_id)
    return _finance_form(request, case=invoice.case, entry=invoice, form_class=VoidForm,
        title=f"Anular factura · {invoice.number}", submit="Confirmar anulación",
        warning="Solo es posible anular una factura sin abonos activos. El registro se conservará.",
        command=lambda **data: finance.void_invoice(invoice=invoice, actor=request.user, **data))


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def payment_void(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("invoice__case"), pk=payment_id)
    return _finance_form(request, case=payment.invoice.case, form_class=VoidForm,
        title="Anular abono", submit="Confirmar anulación", warning="El valor del abono volverá al saldo pendiente de la factura.",
        command=lambda **data: finance.void_payment(payment=payment, actor=request.user, **data))


@login_required
@permission_required("core.manage_finance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def cost_void(request, cost_id):
    cost = get_object_or_404(Cost.objects.select_related("case"), pk=cost_id)
    return _finance_form(request, case=cost.case, form_class=VoidForm,
        title="Anular costo", submit="Confirmar anulación", warning="El costo quedará excluido de los totales y conservará su historial.",
        command=lambda **data: finance.void_cost(cost=cost, actor=request.user, **data))
