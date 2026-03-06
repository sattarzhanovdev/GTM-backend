from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .models import PaymentCharge, PaymentParticipation, Receipt


def _parse_local_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if timezone.is_aware(dt):
        return timezone.localtime(dt)
    try:
        return timezone.make_aware(dt, timezone.get_current_timezone())
    except Exception:
        return None


@staff_member_required
def apartment_search_payments_report(request: HttpRequest) -> HttpResponse:
    """
    Отчет по оплатам доступа/услуги "поиск квартиры".

    Основано на существующих моделях:
      - PaymentCharge (начисление)
      - PaymentParticipation (статус оплаты по квартире)
      - Receipt (загруженный чек)
    """

    charge_id = (request.GET.get("charge_id") or "").strip()
    from_str = (request.GET.get("from") or "").strip()
    to_str = (request.GET.get("to") or "").strip()
    status_values = [s for s in request.GET.getlist("status") if s]

    tz = timezone.get_current_timezone()
    now = timezone.localtime(timezone.now(), tz)
    default_from = now - timedelta(days=30)
    dt_from = _parse_local_datetime(from_str) or default_from
    dt_to = _parse_local_datetime(to_str) or now

    charges_qs = PaymentCharge.objects.all().order_by("-created_at")
    charges = list(charges_qs[:200])

    selected_charge: PaymentCharge | None = None
    if charge_id.isdigit():
        selected_charge = charges_qs.filter(id=int(charge_id)).first()

    if selected_charge is None:
        selected_charge = (
            charges_qs.filter(Q(service_name__icontains="поиск") | Q(service_name__icontains="search")).first()
            or charges_qs.first()
        )

    participations = []
    totals = {
        "rows": 0,
        "accepted_count": 0,
        "paid_count": 0,
        "pending_count": 0,
        "due_count": 0,
    }

    if selected_charge is not None:
        parts_qs = (
            PaymentParticipation.objects.filter(payment=selected_charge)
            .select_related("payment")
            .prefetch_related(Prefetch("receipts", queryset=Receipt.objects.order_by("-uploaded_at")))
            .order_by("-status_updated_at", "-created_at")
        )
        parts_qs = parts_qs.filter(status_updated_at__gte=dt_from, status_updated_at__lte=dt_to)
        if status_values:
            parts_qs = parts_qs.filter(status__in=status_values)

        participations = list(parts_qs[:2000])
        totals["rows"] = len(participations)
        for p in participations:
            if p.status == PaymentParticipation.Status.ACCEPTED:
                totals["accepted_count"] += 1
            elif p.status == PaymentParticipation.Status.PAID:
                totals["paid_count"] += 1
            elif p.status == PaymentParticipation.Status.PENDING:
                totals["pending_count"] += 1
            elif p.status == PaymentParticipation.Status.DUE:
                totals["due_count"] += 1

    def _dt_local_input(dt: datetime) -> str:
        try:
            local = timezone.localtime(dt, tz)
        except Exception:
            local = dt
        # datetime-local expects "YYYY-MM-DDTHH:MM"
        return local.strftime("%Y-%m-%dT%H:%M")

    return render(
        request,
        "admin/apartment_search_payments_report.html",
        {
            "charges": charges,
            "selected_charge": selected_charge,
            "dt_from_value": _dt_local_input(dt_from),
            "dt_to_value": _dt_local_input(dt_to),
            "status_choices": PaymentParticipation.Status.choices,
            "selected_statuses": set(status_values),
            "rows": participations,
            "totals": totals,
        },
    )

