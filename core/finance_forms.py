from uuid import uuid4
from decimal import Decimal

from django import forms
from django.utils import timezone


DATE_WIDGET = {"type": "date"}


class InvoiceForm(forms.Form):
    description = forms.CharField(label="Concepto facturado", widget=forms.Textarea(attrs={"rows": 3}), max_length=3000)
    amount = forms.DecimalField(label="Valor total (COP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    issued_on = forms.DateField(label="Fecha de emisión", initial=timezone.localdate, widget=forms.DateInput(attrs=DATE_WIDGET, format="%Y-%m-%d"))
    due_on = forms.DateField(label="Fecha de vencimiento", widget=forms.DateInput(attrs=DATE_WIDGET, format="%Y-%m-%d"))


class PaymentForm(forms.Form):
    amount = forms.DecimalField(label="Valor del abono (COP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    paid_on = forms.DateField(label="Fecha del pago", initial=timezone.localdate, widget=forms.DateInput(attrs=DATE_WIDGET, format="%Y-%m-%d"))
    method = forms.ChoiceField(label="Medio de pago", choices=(("cash", "Efectivo"), ("transfer", "Transferencia"), ("card", "Tarjeta"), ("other", "Otro")))
    reference = forms.CharField(label="Referencia del pago", max_length=120, required=False)
    notes = forms.CharField(label="Observaciones", widget=forms.Textarea(attrs={"rows": 3}), max_length=3000, required=False)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)


class CostForm(forms.Form):
    description = forms.CharField(label="Concepto del costo", widget=forms.Textarea(attrs={"rows": 3}), max_length=250)
    supplier = forms.CharField(label="Proveedor", required=False, max_length=200)
    amount = forms.DecimalField(label="Valor del costo (COP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    incurred_on = forms.DateField(label="Fecha del costo", initial=timezone.localdate, widget=forms.DateInput(attrs=DATE_WIDGET, format="%Y-%m-%d"))


class VoidForm(forms.Form):
    reason = forms.CharField(label="Motivo de la anulación", min_length=5, max_length=3000,
        help_text="El movimiento y este motivo permanecerán en el historial.", widget=forms.Textarea(attrs={"rows": 4}))
