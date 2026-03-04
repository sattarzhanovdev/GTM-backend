from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .auth import USERNAME_RE, issue_token, json_error, parse_json_body, require_auth
from .models import ApartmentMember, DevicePulse, Notification, PaymentCharge, PaymentParticipation, Profile, PushDevice, Receipt


STATUS_TEXT_RU = {
    PaymentParticipation.Status.DUE: "К оплате",
    PaymentParticipation.Status.PAID: "Оплачено",
    PaymentParticipation.Status.PENDING: "На рассмотрении",
    PaymentParticipation.Status.ACCEPTED: "Принято",
}


def _local_dt_iso(dt) -> str | None:
    if not dt:
        return None
    try:
        return timezone.localtime(dt).isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return None


def _local_date_iso(dt) -> str | None:
    if not dt:
        return None
    try:
        return timezone.localtime(dt).date().isoformat()
    except Exception:
        try:
            return dt.date().isoformat()
        except Exception:
            return None


def _parse_local_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


@require_GET
def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def login(request):
    body = parse_json_body(request)
    if body is None:
        return json_error("Неверный JSON в теле запроса")

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    if not username or not password:
        return json_error("Нужны поля username и password", status=400)

    match = USERNAME_RE.match(username)
    if not match:
        return json_error("username должен быть в формате 'квартира-подъезд' (например 12-1)", status=400)

    apartment = match.group("apartment")
    entrance = match.group("entrance")

    # бизнес-правило: пароль = номер квартиры
    if password != apartment:
        return json_error("Неверный логин или пароль", status=401)

    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_password(password)
        user.save(update_fields=["password"])
    else:
        if not user.check_password(password):
            return json_error("Неверный логин или пароль", status=401)

    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={
            "apartment": int(apartment),
            "entrance": int(entrance),
            "created_at": timezone.now(),
        },
    )

    # Ensure at least one "apartment member" exists for the UI.
    ApartmentMember.objects.get_or_create(
        apartment=profile.apartment,
        is_primary=True,
        defaults={
            "full_name": profile.full_name or f"Квартира {profile.apartment}",
            "phone_number": profile.phone_number,
            "code": f"{profile.apartment:02d}KG{profile.entrance:02d}",
            "created_at": timezone.now(),
        },
    )

    token = issue_token(username)
    return JsonResponse(
        {
            "ok": True,
            "token": token,
            "user": {
                "username": username,
                "apartment": profile.apartment,
                "entrance": profile.entrance,
                "isPayed": profile.is_payed,
                "isAccept": profile.is_accept,
                "block": "18" if profile.is_blocked else "0",
            },
        }
    )


@require_GET
@require_auth
def me(request):
    profile: Profile = request.profile
    return JsonResponse(
        {
            "ok": True,
            "user": {
                "username": request.user.username,
                "apartment": profile.apartment,
                "entrance": profile.entrance,
                "isPayed": profile.is_payed,
                "isAccept": profile.is_accept,
                "block": "18" if profile.is_blocked else "0",
            },
        }
    )


@require_GET
@require_auth
def notifications(request):
    profile: Profile = request.profile
    qs = Notification.objects.filter(apartment=profile.apartment).order_by("-created_at")
    items = [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "is_read": n.is_read,
            "created_at": _local_dt_iso(n.created_at),
        }
        for n in qs
    ]
    return JsonResponse({"ok": True, "items": items})


@csrf_exempt
@require_POST
@require_auth
def notifications_mark_read(request, notification_id: int):
    profile: Profile = request.profile
    updated = Notification.objects.filter(id=notification_id, apartment=profile.apartment).update(is_read=True)
    if not updated:
        return json_error("Не найдено", status=404)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def notifications_delete(request, notification_id: int):
    profile: Profile = request.profile
    deleted, _ = Notification.objects.filter(id=notification_id, apartment=profile.apartment).delete()
    if not deleted:
        return json_error("Не найдено", status=404)
    return JsonResponse({"ok": True})


@require_GET
@require_auth
def apartment_users(request):
    profile: Profile = request.profile
    items = (
        ApartmentMember.objects.filter(apartment=profile.apartment)
        .order_by("-is_primary", "-created_at")
        .values("id", "full_name", "phone_number", "code", "is_primary")
    )
    return JsonResponse({"ok": True, "items": list(items)})


@csrf_exempt
@require_POST
@require_auth
def apartment_users_delete(request, member_id: int):
    profile: Profile = request.profile
    deleted, _ = ApartmentMember.objects.filter(id=member_id, apartment=profile.apartment, is_primary=False).delete()
    if not deleted:
        return json_error("Не найдено или нельзя удалить основного пользователя", status=404)
    return JsonResponse({"ok": True})


@require_GET
@require_auth
def payments(request):
    profile: Profile = request.profile
    qs = PaymentCharge.objects.all().order_by("-created_at")
    parts = PaymentParticipation.objects.filter(apartment=profile.apartment, payment__in=qs).values(
        "payment_id", "status", "status_updated_at"
    )
    part_by_payment_id = {p["payment_id"]: p for p in parts}
    items = [
        {
            "id": p.id,
            "title": p.service_name,
            "amount": p.amount,
            "currency": p.currency,
            "amountText": f"{p.amount} {p.currency}",
            "status": part_by_payment_id.get(p.id, {}).get("status", PaymentParticipation.Status.DUE),
            "statusText": STATUS_TEXT_RU.get(
                part_by_payment_id.get(p.id, {}).get("status", PaymentParticipation.Status.DUE),
                "К оплате",
            ),
            "dueDate": p.due_date.isoformat() if p.due_date else None,
            "payUrl": p.payment_url or None,
        }
        for p in qs
    ]
    return JsonResponse({"ok": True, "items": items})


@require_GET
@require_auth
def payments_history(request):
    profile: Profile = request.profile
    date_str = (request.GET.get("date") or "").strip()
    qs = (
        PaymentParticipation.objects.filter(apartment=profile.apartment)
        .exclude(status=PaymentParticipation.Status.DUE)
        .select_related("payment")
        .order_by("-status_updated_at", "-created_at")
    )
    if date_str:
        d = _parse_local_date(date_str)
        if not d:
            return json_error("Неверный формат даты, нужен YYYY-MM-DD", status=400)
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
        end = start + timedelta(days=1)
        qs = qs.filter(status_updated_at__gte=start, status_updated_at__lt=end)
    items = [
        {
            "id": part.payment_id,
            "title": part.payment.service_name,
            "amount": part.payment.amount,
            "currency": part.payment.currency,
            "amountText": f"{part.payment.amount} {part.payment.currency}",
            "status": part.status,
            "statusText": STATUS_TEXT_RU.get(part.status, "К оплате"),
            "date": _local_date_iso(part.status_updated_at),
            "payUrl": part.payment.payment_url or None,
        }
        for part in qs
    ]
    return JsonResponse({"ok": True, "items": items})


@csrf_exempt
@require_POST
@require_auth
def payments_attach_receipt(request, payment_id: int):
    profile: Profile = request.profile
    try:
        payment = PaymentCharge.objects.get(id=payment_id)
    except PaymentCharge.DoesNotExist:
        return json_error("Не найдено", status=404)

    part, _ = PaymentParticipation.objects.get_or_create(
        payment=payment,
        apartment=profile.apartment,
        defaults={
            "entrance": profile.entrance,
            "status": PaymentParticipation.Status.PENDING,
            "status_updated_at": timezone.now(),
            "created_at": timezone.now(),
        },
    )

    if "file" in request.FILES:
        receipt = Receipt.objects.create(participation=part, file=request.FILES["file"])
    else:
        payload = parse_json_body(request)
        if payload is None:
            return json_error("Неверный JSON в теле запроса", status=400)

        raw = str(payload.get("base64") or payload.get("fileBase64") or "").strip()
        if not raw:
            return json_error("Нужно поле file (multipart/form-data) или base64 (JSON)", status=400)

        # allow "data:image/jpeg;base64,...."
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]

        try:
            import base64 as _b64

            content = _b64.b64decode(raw, validate=False)
        except Exception:
            return json_error("Не удалось прочитать base64", status=400)

        name = str(payload.get("name") or "receipt.jpg").strip() or "receipt.jpg"
        receipt = Receipt.objects.create(participation=part, file=ContentFile(content, name=name))

    part.status = PaymentParticipation.Status.PENDING
    part.status_updated_at = timezone.now()
    part.entrance = profile.entrance
    part.save(update_fields=["status", "status_updated_at", "entrance"])

    return JsonResponse({"ok": True, "receipt": {"id": receipt.id}})


@csrf_exempt
@require_POST
@require_auth
def push_register(request):
    profile: Profile = request.profile
    payload = parse_json_body(request)
    if payload is None:
        return json_error("Неверный JSON в теле запроса", status=400)

    token = str(payload.get("token") or "").strip()
    platform = str(payload.get("platform") or "").strip()

    if not token:
        return json_error("Нужно поле token", status=400)

    PushDevice.objects.update_or_create(
        token=token,
        defaults={
            "apartment": profile.apartment,
            "entrance": profile.entrance,
            "platform": platform,
            "is_active": True,
        },
    )
    return JsonResponse({"ok": True})


def _pulse(key: str, seconds: int = 1):
    until = timezone.now() + timedelta(seconds=seconds)
    DevicePulse.objects.update_or_create(key=key, defaults={"active_until": until})


@require_GET
@require_auth
def devices_status(request):
    keys = ["gate"] + [f"kalitka{i}" for i in range(1, 5)] + [f"entrance{i}" for i in range(1, 6)] + [
        f"lift{i}" for i in range(1, 6)
    ]
    pulses = {p.key: p for p in DevicePulse.objects.filter(key__in=keys)}
    return JsonResponse(
        {
            "ok": True,
            "status": {k: bool(pulses.get(k) and pulses[k].is_active()) for k in keys},
        }
    )


@csrf_exempt
@require_POST
@require_auth
def devices_gate_open(request):
    _pulse("gate", seconds=1)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def devices_kalitka_open(request, n: int):
    if n not in (1, 2, 3, 4):
        return json_error("Неверный номер калитки", status=400)
    _pulse(f"kalitka{n}", seconds=1)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def devices_entrance_open(request, n: int):
    if n not in (1, 2, 3, 4, 5):
        return json_error("Неверный номер подъезда", status=400)
    _pulse(f"entrance{n}", seconds=1)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def devices_lift_open(request, n: int):
    if n not in (1, 2, 3, 4, 5):
        return json_error("Неверный номер подъезда", status=400)
    _pulse(f"lift{n}", seconds=1)
    return JsonResponse({"ok": True})

# Create your views here.
