from __future__ import annotations

from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone

from .models import ApartmentMember, Notification, PaymentCharge, PaymentParticipation, Profile, Receipt


@staff_member_required
def admin_analytics(request):
    today = timezone.localdate()
    start_date = today - timedelta(days=13)

    apartments_total = Profile.objects.values("apartment").distinct().count()
    profiles_total = Profile.objects.count()
    members_total = ApartmentMember.objects.count()

    charges_total = PaymentCharge.objects.count()
    participations_total = PaymentParticipation.objects.count()

    receipts_total = Receipt.objects.count()
    receipts_pending_total = PaymentParticipation.objects.filter(status=PaymentParticipation.Status.PENDING).count()

    notifications_total = Notification.objects.count()
    notifications_unread_total = Notification.objects.filter(is_read=False).count()

    status_rows = PaymentParticipation.objects.values("status").annotate(count=Count("id")).order_by("status")
    status_map = {row["status"]: row["count"] for row in status_rows}
    status_labels = []
    status_values = []
    for value, label in PaymentParticipation.Status.choices:
        status_labels.append(label)
        status_values.append(int(status_map.get(value, 0)))

    receipts_rows = (
        Receipt.objects.filter(uploaded_at__date__gte=start_date)
        .annotate(day=TruncDate("uploaded_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    receipts_by_day = {row["day"].isoformat(): int(row["count"]) for row in receipts_rows if row["day"]}
    receipt_labels = [(start_date + timedelta(days=i)).isoformat() for i in range(14)]
    receipt_values = [receipts_by_day.get(d, 0) for d in receipt_labels]

    return JsonResponse(
        {
            "ok": True,
            "cards": {
                "apartmentsTotal": apartments_total,
                "profilesTotal": profiles_total,
                "membersTotal": members_total,
                "chargesTotal": charges_total,
                "participationsTotal": participations_total,
                "receiptsTotal": receipts_total,
                "receiptsPendingTotal": receipts_pending_total,
                "notificationsTotal": notifications_total,
                "notificationsUnreadTotal": notifications_unread_total,
            },
            "charts": {
                "paymentsByStatus": {"labels": status_labels, "values": status_values},
                "receiptsLast14Days": {"labels": receipt_labels, "values": receipt_values},
            },
        }
    )

