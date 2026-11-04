"""Authenticated overview and searchable service register."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from .models import Case, Cost, DocumentRequirement, Invoice, Payment, Procedure


def _case_rows():
    return Case.objects.select_related("partner").prefetch_related(
        "invoices__payments", "costs", "requirements__documents"
    )


@login_required
@permission_required("core.view_case", raise_exception=True)
def dashboard(request):
    today = timezone.localdate()
    zero = Decimal("0.00")
    billed = Invoice.objects.filter(status="issued").aggregate(total=Sum("amount"))["total"] or zero
    paid = Payment.objects.filter(voided=False, invoice__status="issued").aggregate(total=Sum("amount"))["total"] or zero
    costs = Cost.objects.filter(voided=False).aggregate(total=Sum("amount"))["total"] or zero
    overdue = list(Invoice.objects.filter(status="issued", due_on__lt=today).select_related("case").prefetch_related("payments"))
    overdue = [invoice for invoice in overdue if invoice.balance > 0]
    pending = Procedure.objects.exclude(status="done").exclude(case__status__in=["closed", "cancelled"])
    missing = DocumentRequirement.objects.filter(required=True, documents__isnull=True).exclude(case__status__in=["closed", "cancelled"])
    context = {
        "today": today,
        "active_cases": Case.objects.filter(status__in=["open", "in_progress"]).count(),
        "total_cases": Case.objects.count(),
        "pending_procedures": pending.count(),
        "missing_documents": missing.count(),
        "cases_missing_documents": missing.values("case_id").distinct().count(),
        "billed_total": billed,
        "paid_total": paid,
        "balance_total": billed - paid,
        "cost_total": costs,
        "margin_total": billed - costs,
        "overdue_count": len(overdue),
        "overdue_total": sum((invoice.balance for invoice in overdue), zero),
        "overdue_invoices": sorted(overdue, key=lambda invoice: invoice.due_on)[:5],
        "upcoming_procedures": pending.select_related("case").order_by("due_on", "pk")[:6],
        "recent_cases": _case_rows().order_by("-created_at")[:6],
        "nav": "dashboard",
    }
    return render(request, "core/dashboard.html", context)


@login_required
@permission_required("core.view_case", raise_exception=True)
def case_list(request):
    cases = _case_rows().order_by("-created_at")
    query = request.GET.get("q", "").strip()[:200]
    status = request.GET.get("status", "")
    payer = request.GET.get("payer", "")
    after = request.GET.get("after", "")
    before = request.GET.get("before", "")
    filter_error = ""
    if query:
        terms = (Q(deceased_name__icontains=query) | Q(deceased_id__icontains=query)
                 | Q(requester_name__icontains=query) | Q(payer_name__icontains=query)
                 | Q(partner__name__icontains=query) | Q(authorization_number__icontains=query))
        case_number = query.upper().removeprefix("CFB-")
        if case_number.isdigit() and len(case_number) <= 18:
            terms |= Q(pk=int(case_number))
        cases = cases.filter(terms)
    if status == "active":
        cases = cases.filter(status__in=["open", "in_progress"])
    elif status in {"open", "in_progress", "closed", "cancelled"}:
        cases = cases.filter(status=status)
    if payer in {"company", "private"}:
        cases = cases.filter(payer_type=payer)
    for value, lookup in ((after, "death_date__gte"), (before, "death_date__lte")):
        if value:
            try:
                cases = cases.filter(**{lookup: date.fromisoformat(value)})
            except ValueError:
                filter_error = "Ingresa una fecha válida para filtrar los expedientes."
    params = request.GET.copy()
    params.pop("page", None)
    page = Paginator(cases, 20).get_page(request.GET.get("page"))
    return render(request, "core/case_list.html", {
        "page_obj": page, "cases": page.object_list, "q": query, "status": status,
        "payer": payer, "after": after, "before": before,
        "querystring": params.urlencode(), "filter_error": filter_error, "nav": "cases",
    })
