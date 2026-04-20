from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q

from .auth import issue_token, json_error, parse_json_body, parse_username, require_auth, resolve_complex_building
from .mqtt import publish_device_command
from .models import AccountDeletionRequest, ApartmentMember, DevicePulse, Notification, PaymentCharge, PaymentParticipation, Profile, PushDevice, Receipt


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

    parsed = parse_username(username)
    if not parsed:
        return json_error(
            "Неверный формат username. Примеры: '12-1' (старый) или 'nasip204220' / 'nasip-20-4-220' (новый).",
            status=400,
        )

    apartment = str(parsed["apartment"])
    entrance = str(parsed["entrance"])

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return json_error("Пользователь не найден", status=401)

    # Пароль для квартиры: по умолчанию задаём как номер квартиры при создании пользователей.
    # Дополнительно не "авторегистрируем" — вход только для существующих.
    if not user.check_password(password):
        return json_error("Неверный логин или пароль", status=401)

    complex_obj, building_obj = resolve_complex_building(parsed)
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={
            "complex": complex_obj,
            "building": building_obj,
            "apartment": int(parsed["apartment"]),
            "entrance": int(parsed["entrance"]),
            "created_at": timezone.now(),
        },
    )
    if (
        profile.apartment != int(parsed["apartment"])
        or profile.entrance != int(parsed["entrance"])
        or profile.complex_id != (complex_obj.id if complex_obj else None)
        or profile.building_id != (building_obj.id if building_obj else None)
    ):
        profile.apartment = int(parsed["apartment"])
        profile.entrance = int(parsed["entrance"])
        profile.complex = complex_obj
        profile.building = building_obj
        profile.save(update_fields=["apartment", "entrance", "complex", "building", "updated_at"])

    # Ensure at least one "apartment member" exists for the UI.
    ApartmentMember.objects.get_or_create(
        building=profile.building,
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
                "hasParkingAccess": bool(profile.has_parking_access),
                "mustChangePassword": profile.password_changed_at is None,
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
                "hasParkingAccess": bool(profile.has_parking_access),
                "mustChangePassword": profile.password_changed_at is None,
            },
        }
    )


@csrf_exempt
@require_POST
@require_auth
def profile_password_change(request):
    payload = parse_json_body(request)
    if payload is None:
        return json_error("Неверный JSON в теле запроса", status=400)

    old_password = str(
        payload.get("oldPassword")
        or payload.get("old_password")
        or payload.get("currentPassword")
        or payload.get("current_password")
        or ""
    ).strip()
    new_password = str(payload.get("newPassword") or payload.get("new_password") or "").strip()

    if not old_password or not new_password:
        return json_error("Нужны поля oldPassword и newPassword", status=400)
    if new_password == old_password:
        return json_error("Новый пароль не должен совпадать со старым", status=400)

    user: User = request.user
    if not user.check_password(old_password):
        return json_error("Неверный текущий пароль", status=401)

    try:
        validate_password(new_password, user=user)
    except ValidationError as e:
        msg = "; ".join([str(m) for m in (e.messages or [])]) or "Пароль не проходит проверку"
        return json_error(msg, status=400)

    user.set_password(new_password)
    user.save(update_fields=["password"])

    profile: Profile = request.profile
    profile.password_changed_at = timezone.now()
    profile.save(update_fields=["password_changed_at", "updated_at"])

    return JsonResponse({"ok": True})


@require_GET
@require_auth
def notifications(request):
    profile: Profile = request.profile
    qs = (
        Notification.objects.filter(complex=profile.complex)
        .filter(
            Q(apartment=profile.apartment, building=profile.building)
            | Q(apartment=profile.apartment, building__isnull=True)
            | Q(apartment__isnull=True, building=profile.building)
            | Q(apartment__isnull=True, building__isnull=True)
        )
        .order_by("-created_at")
    )
    items = [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "is_read": n.is_read,
            "created_at": _local_dt_iso(n.created_at),
            "apartment": n.apartment,
        }
        for n in qs
    ]
    return JsonResponse({"ok": True, "items": items})


@csrf_exempt
@require_POST
@require_auth
def notifications_mark_read(request, notification_id: int):
    profile: Profile = request.profile
    updated = (
        Notification.objects.filter(id=notification_id, complex=profile.complex, apartment=profile.apartment)
        .filter(Q(building=profile.building) | Q(building__isnull=True))
        .update(is_read=True)
    )
    if not updated:
        return json_error("Не найдено", status=404)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def notifications_delete(request, notification_id: int):
    profile: Profile = request.profile
    deleted, _ = (
        Notification.objects.filter(id=notification_id, complex=profile.complex, apartment=profile.apartment)
        .filter(Q(building=profile.building) | Q(building__isnull=True))
        .delete()
    )
    if not deleted:
        return json_error("Не найдено", status=404)
    return JsonResponse({"ok": True})


@require_GET
@require_auth
def apartment_users(request):
    profile: Profile = request.profile
    items = (
        ApartmentMember.objects.filter(building=profile.building, apartment=profile.apartment)
        .order_by("-is_primary", "-created_at")
        .values("id", "full_name", "phone_number", "code", "is_primary")
    )
    return JsonResponse({"ok": True, "items": list(items)})


@csrf_exempt
@require_POST
@require_auth
def apartment_users_delete(request, member_id: int):
    profile: Profile = request.profile
    deleted, _ = ApartmentMember.objects.filter(
        id=member_id,
        building=profile.building,
        apartment=profile.apartment,
        is_primary=False,
    ).delete()
    if not deleted:
        return json_error("Не найдено или нельзя удалить основного пользователя", status=404)
    return JsonResponse({"ok": True})


@require_GET
@require_auth
def payments(request):
    profile: Profile = request.profile
    qs = (
        PaymentCharge.objects.filter(complex=profile.complex)
        .filter(Q(building=profile.building) | Q(building__isnull=True))
        .order_by("-created_at")
    )
    parts = PaymentParticipation.objects.filter(building=profile.building, apartment=profile.apartment, payment__in=qs).values(
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
        PaymentParticipation.objects.filter(building=profile.building, apartment=profile.apartment)
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
    if payment.complex_id != profile.complex_id:
        return json_error("Не найдено", status=404)
    if payment.building_id and payment.building_id != profile.building_id:
        return json_error("Не найдено", status=404)

    part, _ = PaymentParticipation.objects.get_or_create(
        payment=payment,
        building=profile.building,
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
    token_type = str(payload.get("tokenType") or payload.get("token_type") or "").strip().lower()

    if not token:
        return json_error("Нужно поле token", status=400)

    if not token_type:
        # авто-определение для обратной совместимости
        token_type = "expo" if token.startswith("ExponentPushToken") else "fcm"

    if token_type not in (PushDevice.TokenType.EXPO, PushDevice.TokenType.FCM):
        return json_error("Неверный tokenType (должен быть 'expo' или 'fcm')", status=400)

    PushDevice.objects.update_or_create(
        token=token,
        defaults={
            "token_type": token_type,
            "building": profile.building,
            "apartment": profile.apartment,
            "entrance": profile.entrance,
            "platform": platform,
            "is_active": True,
        },
    )
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@require_auth
def account_delete_request(request):
    profile: Profile = request.profile
    payload = parse_json_body(request) or {}
    reason = str(payload.get("reason") or "").strip()

    # Не плодим бесконечные заявки
    exists = AccountDeletionRequest.objects.filter(profile=profile, status=AccountDeletionRequest.Status.PENDING).exists()
    if exists:
        return JsonResponse({"ok": True, "detail": "already pending"})

    AccountDeletionRequest.objects.create(profile=profile, reason=reason, created_at=timezone.now())
    return JsonResponse({"ok": True})


def _pulse(key: str, seconds: int = 1):
    until = timezone.now() + timedelta(seconds=seconds)
    DevicePulse.objects.update_or_create(key=key, defaults={"active_until": until})


def _publish_device_command(
    profile: Profile,
    *,
    device_type: str,
    device_id: str | int,
    seconds: int = 1,
    extra: dict | None = None,
    target_complex: str | None = None,
    target_building: str | None = None,
):
    try:
        return publish_device_command(
            profile,
            device_type=device_type,
            device_id=device_id,
            seconds=seconds,
            extra=extra,
            target_complex=target_complex,
            target_building=target_building,
        )
    except Exception as exc:
        raise RuntimeError(f"MQTT publish failed: {exc}") from exc


def _resolve_global_device_scope(profile: Profile, device_type: str, device_id: int) -> tuple[str, str]:
    complex_slug = str(profile.complex.slug)

    if device_type == "gate":
        building_id = {
            1: "20",
            2: "20",
            3: "20",
            4: "d",
            5: "e",
        }.get(device_id, str(profile.building.building_id))
        return complex_slug, building_id

    if device_type == "kalitka":
        building_id = {
            1: "20",
            2: "20",
            3: "20",
            4: "d",
            5: "e",
            6: "e",
        }.get(device_id, str(profile.building.building_id))
        return complex_slug, building_id

    return complex_slug, str(profile.building.building_id)


@require_GET
@require_auth
def devices_status(request):
    keys = (
        ["gate"]  # legacy alias for gate1
        + [f"gate{i}" for i in range(1, 6)]
        + [f"kalitka{i}" for i in range(1, 7)]
        + [f"entrance{i}" for i in range(1, 6)]
        + [f"lift{i}" for i in range(1, 6)]
        + ["parking"]
    )
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
    profile: Profile = request.profile
    _pulse("gate", seconds=1)
    _pulse("gate1", seconds=1)
    target_complex, target_building = _resolve_global_device_scope(profile, "gate", 1)
    try:
        mqtt = _publish_device_command(
            profile,
            device_type="gate",
            device_id=1,
            target_complex=target_complex,
            target_building=target_building,
        )
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})


@csrf_exempt
@require_POST
@require_auth
def devices_gate_n_open(request, n: int):
    if n not in (1, 2, 3, 4, 5):
        return json_error("Неверный номер ворот", status=400)
    profile: Profile = request.profile
    _pulse(f"gate{n}", seconds=1)
    if n == 1:
        _pulse("gate", seconds=1)
    target_complex, target_building = _resolve_global_device_scope(profile, "gate", n)
    try:
        mqtt = _publish_device_command(
            profile,
            device_type="gate",
            device_id=n,
            target_complex=target_complex,
            target_building=target_building,
        )
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})


@csrf_exempt
@require_POST
@require_auth
def devices_kalitka_open(request, n: int):
    if n not in (1, 2, 3, 4, 5, 6):
        return json_error("Неверный номер калитки", status=400)
    profile: Profile = request.profile
    _pulse(f"kalitka{n}", seconds=1)
    target_complex, target_building = _resolve_global_device_scope(profile, "kalitka", n)
    try:
        mqtt = _publish_device_command(
            profile,
            device_type="kalitka",
            device_id=n,
            target_complex=target_complex,
            target_building=target_building,
        )
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})


@csrf_exempt
@require_POST
@require_auth
def devices_entrance_open(request, n: int):
    if n not in (1, 2, 3, 4, 5):
        return json_error("Неверный номер подъезда", status=400)
    profile: Profile = request.profile
    _pulse(f"entrance{n}", seconds=1)
    try:
        mqtt = _publish_device_command(profile, device_type="entrance", device_id=n)
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})


@csrf_exempt
@require_POST
@require_auth
def devices_lift_open(request, n: int):
    if n not in (1, 2, 3, 4, 5):
        return json_error("Неверный номер подъезда", status=400)
    profile: Profile = request.profile
    _pulse(f"lift{n}", seconds=1)
    try:
        mqtt = _publish_device_command(profile, device_type="lift", device_id=n)
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})


@csrf_exempt
@require_POST
@require_auth
def devices_parking_open(request):
    profile: Profile = request.profile
    if not profile.has_parking_access:
        return json_error("Нет доступа к парковке", status=403)
    _pulse("parking", seconds=1)
    try:
        mqtt = _publish_device_command(profile, device_type="parking", device_id=1)
    except RuntimeError as exc:
        return json_error(str(exc), status=503)
    return JsonResponse({"ok": True, "mqtt": mqtt})

# Create your views here.
