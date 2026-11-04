import uuid
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

ZERO = Decimal('0.00')
POSITIVE = MinValueValidator(Decimal('0.01'))


def private_path(instance, filename):
    return f'{"logos" if isinstance(instance, Company) else "documents"}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Company(ValidatedModel):
    name = models.CharField('Nombre comercial', max_length=200, default='Casa Funeraria Baranoa')
    legal_name = models.CharField('Razón social', max_length=200, blank=True)
    tax_id = models.CharField('NIT', max_length=30, blank=True)
    address = models.CharField('Dirección', max_length=250, blank=True)
    phone = models.CharField('Teléfono', max_length=40, blank=True)
    email = models.EmailField('Correo', blank=True)
    bank_details = models.TextField('Cuentas e instrucciones de pago', blank=True)
    logo = models.FileField('Logo', upload_to=private_path, max_length=255, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Partner(ValidatedModel):
    name = models.CharField('Empresa exequial', max_length=200, unique=True)
    contact_name = models.CharField('Contacto', max_length=200, blank=True)
    phone = models.CharField('Teléfono', max_length=40, blank=True)
    email = models.EmailField('Correo', blank=True)
    active = models.BooleanField('Activa', default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Case(ValidatedModel):
    STATUS_CHOICES = [('open', 'Abierto'), ('in_progress', 'En atención'), ('closed', 'Cerrado'), ('cancelled', 'Cancelado')]
    deceased_name = models.CharField('Nombre de la persona fallecida', max_length=200)
    deceased_id = models.CharField('Identificación', max_length=40, blank=True)
    birth_date = models.DateField('Fecha de nacimiento', null=True, blank=True)
    death_date = models.DateField('Fecha de fallecimiento')
    requester_name = models.CharField('Solicitante', max_length=200)
    requester_id = models.CharField('Identificación del solicitante', max_length=40, blank=True)
    requester_phone = models.CharField('Teléfono del solicitante', max_length=40, blank=True)
    requester_relationship = models.CharField('Parentesco o relación', max_length=80, blank=True)
    payer_type = models.CharField('Tipo de pagador', max_length=10, choices=[('company', 'Empresa exequial'), ('private', 'Particular')])
    partner = models.ForeignKey(Partner, verbose_name='Empresa exequial', on_delete=models.PROTECT, null=True, blank=True)
    payer_name = models.CharField('Responsable del pago', max_length=200)
    authorization_number = models.CharField('Número de autorización', max_length=120, blank=True)
    authorized_by = models.CharField('Autorizado por', max_length=200, blank=True)
    authorized_on = models.DateField('Fecha de autorización', null=True, blank=True)
    authorization_notes = models.TextField('Alcance de la autorización', blank=True)
    service_location = models.CharField('Lugar de prestación', max_length=250, blank=True)
    notes = models.TextField('Observaciones', blank=True)
    status = models.CharField('Estado', max_length=15, choices=STATUS_CHOICES, default='open', db_index=True)
    closure_reason = models.TextField('Motivo de cierre o cancelación', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [('manage_operations', 'Gestionar expedientes y documentos'), ('manage_finance', 'Gestionar cobros, abonos y costos'), ('manage_settings', 'Configurar empresa')]

    def clean(self):
        errors = {}
        if self.death_date and self.death_date > timezone.localdate():
            errors['death_date'] = 'El fallecimiento no puede tener fecha futura.'
        if self.birth_date and self.death_date and self.birth_date > self.death_date:
            errors['birth_date'] = 'El nacimiento debe ser anterior al fallecimiento.'
        if self.payer_type == 'company' and not self.partner_id:
            errors['partner'] = 'Seleccione la empresa exequial.'
        if self.payer_type == 'private' and self.partner_id:
            errors['partner'] = 'Un servicio particular no debe tener empresa exequial.'
        if self.authorized_on and self.authorized_on > timezone.localdate():
            errors['authorized_on'] = 'La autorización no puede tener fecha futura.'
        if errors:
            raise ValidationError(errors)

    @property
    def code(self):
        return f'CFB-{self.pk:06d}' if self.pk else 'Nuevo expediente'

    @property
    def billed_total(self):
        return sum((x.amount for x in self.invoices.all() if x.status == 'issued'), ZERO)

    @property
    def paid_total(self):
        return sum((x.paid_total for x in self.invoices.all() if x.status == 'issued'), ZERO)

    @property
    def balance(self):
        return self.billed_total - self.paid_total

    @property
    def cost_total(self):
        return sum((x.amount for x in self.costs.all() if not x.voided), ZERO)

    @property
    def margin(self):
        return self.billed_total - self.cost_total

    @property
    def missing_documents(self):
        return [r for r in self.requirements.all() if r.required and not r.documents.all()]

    def __str__(self):
        return f'{self.code} · {self.deceased_name}'


class ServiceItem(ValidatedModel):
    case = models.ForeignKey(Case, related_name='items', on_delete=models.PROTECT)
    description = models.CharField('Servicio o actividad', max_length=250)
    quantity = models.PositiveIntegerField('Cantidad', default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField('Valor unitario (COP)', max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    authorized = models.BooleanField('Autorizado / contratado', default=False)
    performed = models.BooleanField('Prestado', default=False)
    performed_at = models.DateTimeField('Fecha de prestación', null=True, blank=True)
    notes = models.TextField('Observaciones', blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name='service_quantity_positive'), models.CheckConstraint(condition=Q(unit_price__gte=0), name='service_price_nonnegative')]

    @property
    def total(self):
        return self.quantity * self.unit_price

    def clean(self):
        if self.performed and not self.authorized:
            raise ValidationError('No se puede prestar un servicio sin autorización.')


class Procedure(ValidatedModel):
    case = models.ForeignKey(Case, related_name='procedures', on_delete=models.PROTECT)
    title = models.CharField('Trámite', max_length=250)
    entity = models.CharField('Entidad', max_length=15, choices=[('registry', 'Registraduría'), ('notary', 'Notaría'), ('other', 'Otra')], default='registry')
    status = models.CharField('Estado', max_length=15, choices=[('pending', 'Pendiente'), ('in_progress', 'En trámite'), ('done', 'Completado')], default='pending')
    reference = models.CharField('Radicado o referencia', max_length=120, blank=True)
    notes = models.TextField('Observaciones', blank=True)
    due_on = models.DateField('Fecha límite', null=True, blank=True)
    completed_on = models.DateField('Fecha de finalización', null=True, blank=True)

    def clean(self):
        if self.status == 'done' and not self.completed_on:
            raise ValidationError({'completed_on': 'Indique cuándo se completó el trámite.'})
        if self.status != 'done' and self.completed_on:
            raise ValidationError({'completed_on': 'Solo los trámites completados tienen fecha de finalización.'})
        if self.completed_on and self.completed_on > timezone.localdate():
            raise ValidationError({'completed_on': 'La fecha de finalización no puede ser futura.'})


class DocumentRequirement(ValidatedModel):
    case = models.ForeignKey(Case, related_name='requirements', on_delete=models.PROTECT)
    label = models.CharField('Documento solicitado', max_length=200)
    required = models.BooleanField('Obligatorio para cerrar', default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['case', 'label'], name='unique_requirement_case')]

    def __str__(self):
        return self.label


class Document(ValidatedModel):
    case = models.ForeignKey(Case, related_name='documents', on_delete=models.PROTECT)
    requirement = models.ForeignKey(DocumentRequirement, related_name='documents', on_delete=models.PROTECT, null=True, blank=True)
    title = models.CharField('Nombre del documento', max_length=200)
    file = models.FileField('PDF', upload_to=private_path, max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def clean(self):
        if self.requirement_id and self.requirement.case_id != self.case_id:
            raise ValidationError({'requirement': 'El requisito pertenece a otro expediente.'})


class Invoice(ValidatedModel):
    case = models.ForeignKey(Case, related_name='invoices', on_delete=models.PROTECT)
    number = models.CharField('Número', max_length=32, unique=True)
    issued_on = models.DateField('Fecha de emisión')
    due_on = models.DateField('Fecha de vencimiento')
    description = models.TextField('Concepto')
    amount = models.DecimalField('Valor (COP)', max_digits=14, decimal_places=2, validators=[POSITIVE])
    status = models.CharField(max_length=10, choices=[('issued', 'Vigente'), ('void', 'Anulada')], default='issued')
    void_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='invoice_amount_positive'), models.CheckConstraint(condition=Q(due_on__gte=models.F('issued_on')), name='invoice_due_after_issued')]

    def clean(self):
        if self.issued_on and self.issued_on > timezone.localdate():
            raise ValidationError({'issued_on': 'No puede ser futura.'})
        if self.due_on and self.issued_on and self.due_on < self.issued_on:
            raise ValidationError({'due_on': 'Debe ser igual o posterior a la emisión.'})
        if self.status == 'void' and not self.void_reason.strip():
            raise ValidationError({'void_reason': 'Indique un motivo.'})

    @property
    def paid_total(self):
        return sum((x.amount for x in self.payments.all() if not x.voided), ZERO)

    @property
    def balance(self):
        return self.amount - self.paid_total if self.status == 'issued' else ZERO

    def __str__(self):
        return self.number


class Payment(ValidatedModel):
    invoice = models.ForeignKey(Invoice, related_name='payments', on_delete=models.PROTECT)
    amount = models.DecimalField('Valor (COP)', max_digits=14, decimal_places=2, validators=[POSITIVE])
    paid_on = models.DateField('Fecha de pago')
    method = models.CharField('Medio de pago', max_length=15, choices=[('cash', 'Efectivo'), ('transfer', 'Transferencia'), ('card', 'Tarjeta'), ('other', 'Otro')])
    reference = models.CharField('Referencia', max_length=120, blank=True)
    notes = models.TextField('Observaciones', blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='payment_amount_positive')]

    def clean(self):
        if self.paid_on and self.paid_on > timezone.localdate():
            raise ValidationError({'paid_on': 'No puede ser futura.'})
        if self.voided and not self.void_reason.strip():
            raise ValidationError({'void_reason': 'Indique un motivo.'})


class Cost(ValidatedModel):
    case = models.ForeignKey(Case, related_name='costs', on_delete=models.PROTECT)
    description = models.CharField('Concepto', max_length=250)
    supplier = models.CharField('Proveedor', max_length=200, blank=True)
    amount = models.DecimalField('Valor (COP)', max_digits=14, decimal_places=2, validators=[POSITIVE])
    incurred_on = models.DateField('Fecha del costo')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='cost_amount_positive')]

    def clean(self):
        if self.incurred_on and self.incurred_on > timezone.localdate():
            raise ValidationError({'incurred_on': 'No puede ser futura.'})
        if self.voided and not self.void_reason.strip():
            raise ValidationError({'void_reason': 'Indique un motivo.'})


class AuditEvent(models.Model):
    case = models.ForeignKey(Case, related_name='audit_events', on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


def log_event(actor, action, case=None, detail=''):
    return AuditEvent.objects.create(actor=actor, action=action, case=case, detail=detail)


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(default=timezone.now)
