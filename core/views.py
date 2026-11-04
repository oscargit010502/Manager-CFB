from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CaseForm, CompanyForm, DocumentForm, PartnerForm, ProcedureForm, ReasonForm, RequirementForm, ServiceItemForm
from .models import Case, Company, Document, DocumentRequirement, Partner, Procedure, ServiceItem, log_event


def permitted(permission):
    def decorate(view):
        return login_required(permission_required(permission, raise_exception=True)(view))
    return decorate


def _editable(case):
    if case.status in ("closed", "cancelled"):
        raise ValidationError("Este expediente está cerrado o cancelado y no admite cambios operativos.")


def _form_page(request, form, title, case=None, hint="", back_url=None):
    return render(request, "core/form.html", {"form": form, "title": title, "case": case, "hint": hint, "back_url": back_url})


def _validation_message(request, error):
    messages.error(request, " ".join(error.messages))


@permitted("core.view_case")
def case_detail(request, pk):
    case = get_object_or_404(Case.objects.select_related("partner", "created_by"), pk=pk)
    return render(request, "core/case_detail.html", {"case": case,
        "items": case.items.all(), "requirements": case.requirements.prefetch_related("documents"),
        "documents": case.documents.select_related("requirement", "uploaded_by"),
        "procedures": case.procedures.all(), "invoices": case.invoices.prefetch_related("payments"),
        "costs": case.costs.all(), "events": case.audit_events.select_related("actor").order_by("-created_at")[:50],
        "editable": case.status not in ("closed", "cancelled"), "reason_form": ReasonForm()})


@permitted("core.manage_operations")
def case_create(request):
    form = CaseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            case = form.save(commit=False)
            case.created_by = request.user
            case.save()
            for label in ("Certificado de defunción", "Registro civil de defunción"):
                DocumentRequirement.objects.create(case=case, label=label, required=True)
            if case.payer_type == "company":
                DocumentRequirement.objects.create(case=case, label="Autorización de la empresa", required=True)
            Procedure.objects.create(case=case, title="Registro de defunción", entity="registry", status="pending")
            log_event(request.user, "Expediente creado", case=case)
        messages.success(request, f"Expediente {case.code} creado.")
        return redirect("case_detail", pk=case.pk)
    return render(request, "core/case_form.html", {"form": form, "title": "Nuevo expediente"})


@permitted("core.manage_operations")
def case_edit(request, pk):
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        try:
            _editable(case)
        except ValidationError as error:
            _validation_message(request, error)
            return redirect("case_detail", pk=pk)
        form = CaseForm(request.POST or None, instance=case)
        if request.method == "POST" and form.is_valid():
            form.save()
            if case.payer_type == "company":
                requirement, _ = DocumentRequirement.objects.get_or_create(case=case, label="Autorización de la empresa", defaults={"required": True})
                if not requirement.required:
                    requirement.required = True
                    requirement.save()
            else:
                requirement = case.requirements.filter(label="Autorización de la empresa").first()
                if requirement:
                    requirement.required = False
                    requirement.save()
            log_event(request.user, "Expediente actualizado", case=case, detail=", ".join(form.changed_data))
            messages.success(request, "Datos del expediente actualizados.")
            return redirect("case_detail", pk=pk)
    return render(request, "core/case_form.html", {"form": form, "title": f"Editar {case.code}", "case": case})


def _case_child_create(request, pk, form_class, title, action):
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        try:
            _editable(case)
        except ValidationError as error:
            _validation_message(request, error)
            return redirect("case_detail", pk=pk)
        form = form_class(request.POST or None, instance=form_class._meta.model(case=case))
        if request.method == "POST" and form.is_valid():
            item = form.save(commit=False)
            item.case = case
            item.save()
            log_event(request.user, action, case=case, detail=getattr(item, "description", getattr(item, "title", str(item))))
            messages.success(request, "Registro guardado.")
            return redirect("case_detail", pk=pk)
    return _form_page(request, form, title, case)


@permitted("core.manage_operations")
def service_add(request, pk):
    return _case_child_create(request, pk, ServiceItemForm, "Agregar servicio", "Servicio agregado")


@permitted("core.manage_operations")
def service_update(request, item_id):
    item = get_object_or_404(ServiceItem, pk=item_id)
    with transaction.atomic():
        case = Case.objects.select_for_update().get(pk=item.case_id)
        item = ServiceItem.objects.select_for_update().get(pk=item_id)
        try:
            _editable(case)
        except ValidationError as error:
            _validation_message(request, error)
            return redirect("case_detail", pk=case.pk)
        form = ServiceItemForm(request.POST or None, instance=item)
        if request.method == "POST" and form.is_valid():
            form.save()
            log_event(request.user, "Servicio actualizado", case=case, detail=f"{item.description}: {', '.join(form.changed_data)}")
            messages.success(request, "Servicio actualizado.")
            return redirect("case_detail", pk=case.pk)
    return _form_page(request, form, "Actualizar servicio", case)


@permitted("core.manage_operations")
def procedure_add(request, pk):
    return _case_child_create(request, pk, ProcedureForm, "Agregar trámite", "Trámite agregado")


@permitted("core.manage_operations")
def requirement_add(request, pk):
    return _case_child_create(request, pk, RequirementForm, "Agregar requisito documental", "Requisito documental agregado")


@permitted("core.manage_operations")
@require_POST
def service_toggle(request, item_id):
    item = get_object_or_404(ServiceItem, pk=item_id)
    with transaction.atomic():
        case = Case.objects.select_for_update().get(pk=item.case_id)
        item = ServiceItem.objects.select_for_update().get(pk=item_id)
        try:
            _editable(case)
            if not item.authorized:
                raise ValidationError("El servicio debe estar autorizado antes de marcarlo como prestado.")
            # The desired state is explicit: repeated submissions never toggle it back.
            performed = request.POST.get("performed")
            if performed not in ("0", "1"):
                raise ValidationError("Indica si el servicio se prestó.")
            if performed == "1" and case.payer_type == "company" and not all((case.authorization_number, case.authorized_by, case.authorized_on)):
                raise ValidationError("Completa el número, responsable y fecha de autorización antes de registrar la prestación.")
            if item.performed == (performed == "1"):
                messages.info(request, "El servicio ya tiene el estado solicitado.")
                return redirect("case_detail", pk=case.pk)
            item.performed = performed == "1"
            item.performed_at = timezone.now() if item.performed else None
            item.save()
            log_event(request.user, "Prestación actualizada", case=case, detail=f"{item.description}: {'prestado' if item.performed else 'pendiente'}")
            messages.success(request, "Prestación actualizada.")
        except ValidationError as error:
            _validation_message(request, error)
    return redirect("case_detail", pk=item.case_id)


@permitted("core.manage_operations")
def procedure_update(request, procedure_id):
    procedure = get_object_or_404(Procedure, pk=procedure_id)
    with transaction.atomic():
        case = Case.objects.select_for_update().get(pk=procedure.case_id)
        procedure = Procedure.objects.select_for_update().get(pk=procedure_id)
        try:
            _editable(case)
        except ValidationError as error:
            _validation_message(request, error)
            return redirect("case_detail", pk=case.pk)
        form = ProcedureForm(request.POST or None, instance=procedure)
        if request.method == "POST" and form.is_valid():
            form.save()
            log_event(request.user, "Trámite actualizado", case=case, detail=f"{procedure.title}: {procedure.get_status_display()}")
            messages.success(request, "Trámite actualizado.")
            return redirect("case_detail", pk=case.pk)
    return _form_page(request, form, "Actualizar trámite", case)


@permitted("core.manage_operations")
def document_upload(request, pk):
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        try:
            _editable(case)
        except ValidationError as error:
            _validation_message(request, error)
            return redirect("case_detail", pk=pk)
        form = DocumentForm(request.POST or None, request.FILES or None, case=case)
        if request.method == "POST" and form.is_valid():
            document = form.save(commit=False)
            document.case = case
            document.uploaded_by = request.user
            for key, value in form.metadata.items():
                setattr(document, key, value)
            document.save()
            log_event(request.user, "Documento cargado", case=case, detail=f"{document.title} · SHA-256 {document.sha256}")
            messages.success(request, "PDF guardado en el almacenamiento privado.")
            return redirect("case_detail", pk=pk)
    return _form_page(request, form, "Cargar documento PDF", case, "Los archivos anteriores se conservan. Adjunta una nueva versión cuando sea necesario.")


@permitted("core.view_case")
def document_download(request, document_id):
    document = get_object_or_404(Document.objects.select_related("case"), pk=document_id)
    try:
        file = document.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("El archivo no está disponible en el almacenamiento.")
    log_event(request.user, "Documento descargado", case=document.case, detail=document.title)
    response = FileResponse(file, as_attachment=True, filename=document.original_name, content_type="application/pdf")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@permitted("core.manage_operations")
@require_POST
def case_start(request, pk):
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        if case.status != "open":
            messages.error(request, "Solo se puede iniciar un expediente abierto.")
        else:
            case.status = "in_progress"
            case.save()
            log_event(request.user, "Atención iniciada", case=case)
            messages.success(request, "El expediente está en atención.")
    return redirect("case_detail", pk=pk)


@permitted("core.manage_operations")
@require_POST
def case_close(request, pk):
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        try:
            _editable(case)
            missing = list(case.requirements.filter(required=True, documents__isnull=True).values_list("label", flat=True))
            if missing:
                raise ValidationError("Faltan documentos obligatorios: " + ", ".join(missing) + ".")
            if case.procedures.exclude(status="done").exists():
                raise ValidationError("Hay trámites pendientes de finalizar.")
            if not case.items.filter(authorized=True).exists() or case.items.filter(authorized=True, performed=False).exists():
                raise ValidationError("Debe existir al menos un servicio autorizado y todos los autorizados deben estar prestados.")
            if case.payer_type == "company" and not all((case.authorization_number, case.authorized_by, case.authorized_on)):
                raise ValidationError("Completa el número, responsable y fecha de autorización de la empresa.")
            case.status = "closed"
            case.save()
            log_event(request.user, "Expediente cerrado", case=case)
            messages.success(request, "Expediente cerrado.")
        except ValidationError as error:
            _validation_message(request, error)
    return redirect("case_detail", pk=pk)


@permitted("core.manage_operations")
@require_POST
def case_cancel(request, pk):
    form = ReasonForm(request.POST)
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        try:
            _editable(case)
            if not form.is_valid():
                raise ValidationError("Escribe un motivo para cancelar el expediente.")
            if case.invoices.filter(status="issued").exists():
                raise ValidationError("Anula las facturas activas antes de cancelar el expediente.")
            if case.costs.filter(voided=False).exists():
                raise ValidationError("Anula los costos activos antes de cancelar el expediente.")
            case.status = "cancelled"
            case.closure_reason = form.cleaned_data["reason"]
            case.save()
            log_event(request.user, "Expediente cancelado", case=case, detail=case.closure_reason)
            messages.success(request, "Expediente cancelado; su historial se conserva.")
        except ValidationError as error:
            _validation_message(request, error)
    return redirect("case_detail", pk=pk)


@permitted("core.manage_settings")
@require_POST
def case_reopen(request, pk):
    form = ReasonForm(request.POST)
    with transaction.atomic():
        case = get_object_or_404(Case.objects.select_for_update(), pk=pk)
        if case.status not in ("closed", "cancelled"):
            messages.error(request, "Solo se puede reabrir un expediente cerrado o cancelado.")
        elif not form.is_valid():
            messages.error(request, "Escribe el motivo de reapertura.")
        else:
            previous_status = case.get_status_display()
            case.status = "open"
            case.closure_reason = ""
            case.save()
            log_event(request.user, "Expediente reabierto", case=case, detail=f"Estado anterior: {previous_status}. Motivo: {form.cleaned_data['reason']}")
            messages.success(request, "Expediente reabierto para correcciones.")
    return redirect("case_detail", pk=pk)


@permitted("core.view_case")
def partner_list(request):
    query = request.GET.get("q", "").strip()[:200]
    partners = Partner.objects.all()
    if query:
        partners = partners.filter(Q(name__icontains=query) | Q(contact_name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query))
    page = Paginator(partners, 25).get_page(request.GET.get("page"))
    return render(request, "core/partner_list.html", {"page_obj": page, "q": query})


@permitted("core.manage_operations")
def partner_create(request):
    form = PartnerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            partner = form.save()
            log_event(request.user, "Empresa registrada", detail=partner.name)
        messages.success(request, "Empresa exequial registrada.")
        return redirect("partner_list")
    return _form_page(request, form, "Registrar empresa exequial", back_url=reverse("partner_list"))


@permitted("core.manage_operations")
def partner_edit(request, pk):
    with transaction.atomic():
        partner = get_object_or_404(Partner.objects.select_for_update(), pk=pk)
        form = PartnerForm(request.POST or None, instance=partner)
        if request.method == "POST" and form.is_valid():
            form.save()
            if form.changed_data:
                log_event(request.user, "Empresa actualizada", detail=f"{partner.name}: {', '.join(form.changed_data)}")
            messages.success(request, "Empresa exequial actualizada.")
            return redirect("partner_list")
    return _form_page(request, form, f"Editar empresa · {partner.name}",
        hint="Al desactivar una empresa, los expedientes existentes se conservan y no se podrá seleccionar para nuevos servicios.",
        back_url=reverse("partner_list"))


@permitted("core.manage_settings")
def company_settings(request):
    company, _ = Company.objects.get_or_create(pk=1)
    form = CompanyForm(request.POST or None, request.FILES or None, instance=company)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            log_event(request.user, "Configuración empresarial actualizada", detail=", ".join(form.changed_data))
        messages.success(request, "Configuración empresarial guardada.")
        return redirect("company_settings")
    return _form_page(request, form, "Datos de la empresa", hint="Completa los datos reales de Casa Funeraria Baranoa. Los datos legales y bancarios son opcionales hasta que se configuren.")


@login_required
def company_logo(request):
    company = get_object_or_404(Company, pk=1)
    if not company.logo:
        raise Http404()
    try:
        file = company.logo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404()
    from PIL import Image
    image = Image.open(file)
    mime = "image/png" if image.format == "PNG" else "image/jpeg"
    file.seek(0)
    response = FileResponse(file, content_type=mime)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
