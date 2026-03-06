from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Prefetch, Q, Sum
from django.db.models.functions import ExtractMonth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

from .models import Expense, ExpenseCategory, FundOpeningBalance, PaymentCharge, PaymentParticipation, Receipt


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


def _parse_local_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


@staff_member_required
def expenses_report(request: HttpRequest) -> HttpResponse:
    tz = timezone.get_current_timezone()
    today = timezone.localdate()

    year_str = (request.GET.get("year") or str(today.year)).strip()
    currency = (request.GET.get("currency") or "сом").strip() or "сом"
    income_statuses = [s for s in request.GET.getlist("income_status") if s] or [
        PaymentParticipation.Status.ACCEPTED,
        PaymentParticipation.Status.PAID,
    ]
    fmt = (request.GET.get("format") or "").strip().lower()

    year = today.year
    if year_str.isdigit():
        year = int(year_str)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "add_expense":
            category_id = (request.POST.get("category_id") or "").strip()
            amount_str = (request.POST.get("amount") or "").strip()
            occurred_at_str = (request.POST.get("occurred_at") or "").strip()
            note = (request.POST.get("note") or "").strip()
            currency_post = (request.POST.get("currency") or currency).strip() or currency

            occurred_at = _parse_local_date(occurred_at_str) or today
            try:
                amount = int(amount_str)
            except Exception:
                amount = 0

            cat = None
            if category_id.isdigit():
                cat = ExpenseCategory.objects.filter(id=int(category_id), is_active=True).first()

            if cat and amount > 0:
                Expense.objects.create(
                    category=cat,
                    amount=amount,
                    currency=currency_post,
                    occurred_at=occurred_at,
                    note=note,
                    created_at=timezone.now(),
                )

            return redirect(f"{request.path}?year={year}&currency={currency_post}")

        if action == "set_opening":
            opening_str = (request.POST.get("opening_amount") or "").strip()
            opening_currency = (request.POST.get("currency") or currency).strip() or currency
            try:
                opening_amount = int(opening_str)
            except Exception:
                opening_amount = 0

            month = datetime(year, 1, 1).date()
            FundOpeningBalance.objects.update_or_create(
                month=month,
                defaults={"amount": opening_amount, "currency": opening_currency},
            )
            return redirect(f"{request.path}?year={year}&currency={opening_currency}")

    categories = list(ExpenseCategory.objects.filter(is_active=True).order_by("sort_order", "name"))

    expense_rows = (
        Expense.objects.filter(occurred_at__year=year, currency=currency)
        .annotate(month=ExtractMonth("occurred_at"))
        .values("category_id", "month")
        .annotate(total=Sum("amount"))
    )
    expenses_by_cat_month: dict[int, dict[int, int]] = {}
    totals_expenses_by_month: dict[int, int] = {m: 0 for m in range(1, 13)}
    for r in expense_rows:
        cat_id = int(r["category_id"])
        month = int(r["month"] or 0)
        total = int(r["total"] or 0)
        if month < 1 or month > 12:
            continue
        expenses_by_cat_month.setdefault(cat_id, {})[month] = total
        totals_expenses_by_month[month] = int(totals_expenses_by_month.get(month, 0)) + total

    income_rows = (
        PaymentParticipation.objects.filter(status_updated_at__year=year, status__in=income_statuses, payment__currency=currency)
        .select_related("payment")
        .annotate(month=ExtractMonth("status_updated_at"))
        .values("month")
        .annotate(total=Sum("payment__amount"))
    )
    totals_income_by_month: dict[int, int] = {m: 0 for m in range(1, 13)}
    for r in income_rows:
        month = int(r["month"] or 0)
        if 1 <= month <= 12:
            totals_income_by_month[month] = int(r["total"] or 0)

    opening_obj = FundOpeningBalance.objects.filter(month=datetime(year, 1, 1).date(), currency=currency).first()
    opening_amount = int(getattr(opening_obj, "amount", 0) or 0)

    fund_open_by_month: dict[int, int] = {}
    fund_close_by_month: dict[int, int] = {}
    run = opening_amount
    for m in range(1, 13):
        fund_open_by_month[m] = run
        run = run + int(totals_income_by_month.get(m, 0) or 0) - int(totals_expenses_by_month.get(m, 0) or 0)
        fund_close_by_month[m] = run

    month_labels = [
        {"month": 1, "label": "янв"},
        {"month": 2, "label": "фев"},
        {"month": 3, "label": "март"},
        {"month": 4, "label": "апр"},
        {"month": 5, "label": "май"},
        {"month": 6, "label": "июнь"},
        {"month": 7, "label": "июль"},
        {"month": 8, "label": "авг"},
        {"month": 9, "label": "сен"},
        {"month": 10, "label": "окт"},
        {"month": 11, "label": "нояб"},
        {"month": 12, "label": "дек"},
    ]

    table_rows = []
    for c in categories:
        by_month = expenses_by_cat_month.get(int(c.id), {})
        values = [int(by_month.get(m, 0) or 0) for m in range(1, 13)]
        table_rows.append({"id": c.id, "label": c.name, "values": values, "row_total": sum(values)})

    income_values = [int(totals_income_by_month.get(m, 0) or 0) for m in range(1, 13)]
    expense_values = [int(totals_expenses_by_month.get(m, 0) or 0) for m in range(1, 13)]
    fund_close_values = [int(fund_close_by_month.get(m, 0) or 0) for m in range(1, 13)]
    opening_values = [opening_amount] + [0] * 11
    income_year_total = sum(income_values)
    expense_year_total = sum(expense_values)
    fund_year_end = fund_close_values[-1] if fund_close_values else opening_amount

    if fmt == "csv":
        import csv
        from io import StringIO

        out = StringIO()
        w = csv.writer(out)
        header = ["Строка"] + [m["label"] for m in month_labels] + ["Итого"]
        w.writerow(header)

        w.writerow(["Доходы (оплаты)"] + income_values + [sum(income_values)])
        opening_label = f"01.01.{str(year)[-2:]}"
        w.writerow([f"Ост {opening_label}"] + opening_values + [opening_amount])
        for r in table_rows:
            w.writerow([r["label"]] + r["values"] + [r["row_total"]])
        w.writerow(["Итого расходы"] + expense_values + [sum(expense_values)])
        w.writerow(["Фонд (конец месяца)"] + fund_close_values + [fund_close_values[-1] if fund_close_values else 0])

        filename = f"expenses-{year}-{slugify(currency) or 'currency'}"
        resp = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return resp

    latest_expenses = (
        Expense.objects.filter(occurred_at__year=year, currency=currency)
        .select_related("category")
        .order_by("-occurred_at", "-created_at")[:50]
    )

    return render(
        request,
        "admin/expenses_report.html",
        {
            "year": year,
            "currency": currency,
            "income_statuses": set(income_statuses),
            "income_status_choices": PaymentParticipation.Status.choices,
            "opening_amount": opening_amount,
            "opening_date_label": f"01.01.{str(year)[-2:]}",
            "month_labels": month_labels,
            "table_rows": table_rows,
            "income_values": income_values,
            "expense_values": expense_values,
            "fund_close_values": fund_close_values,
            "opening_values": opening_values,
            "income_year_total": income_year_total,
            "expense_year_total": expense_year_total,
            "fund_year_end": fund_year_end,
            "latest_expenses": latest_expenses,
            "today": today.isoformat(),
        },
    )
