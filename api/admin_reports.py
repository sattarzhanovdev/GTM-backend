from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

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
    apartment_str = (request.GET.get("apartment") or "").strip()
    entrance_str = (request.GET.get("entrance") or "").strip()
    has_receipt = (request.GET.get("has_receipt") or "").strip().lower() in ("1", "true", "yes", "on")
    fmt = (request.GET.get("format") or "").strip().lower()

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

    participations: list[PaymentParticipation] = []
    totals = {
        "rows": 0,
        "accepted_count": 0,
        "paid_count": 0,
        "pending_count": 0,
        "due_count": 0,
        "accepted_sum": 0,
        "paid_sum": 0,
        "pending_sum": 0,
        "due_sum": 0,
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
        if apartment_str.isdigit():
            parts_qs = parts_qs.filter(apartment=int(apartment_str))
        if entrance_str.isdigit():
            parts_qs = parts_qs.filter(entrance=int(entrance_str))
        if has_receipt:
            parts_qs = parts_qs.filter(receipts__isnull=False).distinct()

        participations = list(parts_qs[:2000])
        totals["rows"] = len(participations)
        amount = int(getattr(selected_charge, "amount", 0) or 0)
        for p in participations:
            if p.status == PaymentParticipation.Status.ACCEPTED:
                totals["accepted_count"] += 1
                totals["accepted_sum"] += amount
            elif p.status == PaymentParticipation.Status.PAID:
                totals["paid_count"] += 1
                totals["paid_sum"] += amount
            elif p.status == PaymentParticipation.Status.PENDING:
                totals["pending_count"] += 1
                totals["pending_sum"] += amount
            elif p.status == PaymentParticipation.Status.DUE:
                totals["due_count"] += 1
                totals["due_sum"] += amount

    if fmt == "csv":
        import csv
        from io import StringIO

        out = StringIO()
        w = csv.writer(out)
        w.writerow(["Дата/время", "Квартира", "Подъезд", "Статус", "Сумма", "Валюта", "Чек (url)", "Чек загружен"])
        for p in participations:
            receipt = next(iter(getattr(p, "receipts", []).all()), None)  # prefetched, no extra queries
            receipt_url = ""
            receipt_uploaded = ""
            if receipt:
                try:
                    receipt_url = receipt.file.url
                except Exception:
                    receipt_url = ""
                receipt_uploaded = timezone.localtime(receipt.uploaded_at, tz).strftime("%Y-%m-%d %H:%M") if receipt.uploaded_at else ""

            dt = timezone.localtime(p.status_updated_at, tz).strftime("%Y-%m-%d %H:%M") if p.status_updated_at else ""
            w.writerow(
                [
                    dt,
                    p.apartment,
                    p.entrance,
                    p.get_status_display(),
                    p.payment.amount,
                    p.payment.currency,
                    receipt_url,
                    receipt_uploaded,
                ]
            )

        filename = "report"
        if selected_charge:
            filename = f"payments-{selected_charge.id}-{slugify(selected_charge.service_name)[:40] or 'charge'}"
        resp = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return resp

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
            "apartment_value": apartment_str,
            "entrance_value": entrance_str,
            "has_receipt": has_receipt,
            "rows": participations,
            "totals": totals,
        },
    )
