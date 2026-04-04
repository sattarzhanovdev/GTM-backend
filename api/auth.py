from __future__ import annotations

import json
import re
from datetime import timedelta
from functools import wraps
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone

from .models import BuildingEntranceRange, ComplexBuilding, Profile, ResidentialComplex

OLD_USERNAME_RE = re.compile(r"^(?P<apartment>\d+)-(?P<entrance>\d+)$")
NEW_USERNAME_SPLIT_RE = re.compile(
    r"^(?P<complex>[a-z0-9]+)-(?P<building>[0-9]+|[a-z]+)-(?P<entrance>\d+)-(?P<apartment>\d+)$",
    re.IGNORECASE,
)
TOKEN_MAX_AGE = int(timedelta(days=30).total_seconds())


def json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def parse_json_body(request):
    try:
        raw = request.body.decode("utf-8") if request.body else ""
        return json.loads(raw) if raw else {}
    except Exception:
        return None


def _token_signer():
    return TimestampSigner(salt="DBN-api-token")


def issue_token(username: str) -> str:
    return _token_signer().sign(username)


def get_bearer_token(request) -> str | None:
    header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION") or ""
    if not header.startswith("Bearer "):
        return None
    token = header.removeprefix("Bearer ").strip()
    return token or None


def auth_username_from_request(request) -> str | None:
    token = get_bearer_token(request)
    if not token:
        return None
    try:
        return _token_signer().unsign(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _complexes_cfg() -> dict:
    """
    Возвращает конфиг комплексов/домов для парсинга username.

    Приоритет:
      1) данные из БД (ResidentialComplex/ComplexBuilding/BuildingEntranceRange)
      2) fallback: settings.DBN_COMPLEXES (для обратной совместимости)

    Формат совпадает с прежним settings.DBN_COMPLEXES.
    """

    # короткий кеш, чтобы parse_username не бил БД на каждый запрос
    now_ts = int(timezone.now().timestamp())
    cache = getattr(_complexes_cfg, "_cache", None)
    if isinstance(cache, dict) and cache.get("ts") == now_ts:
        return cache.get("data") or {}

    db_cfg: dict[str, Any] = {}
    try:
        complexes = (
            ResidentialComplex.objects.all()
            .prefetch_related(
                Prefetch(
                    "buildings",
                    queryset=ComplexBuilding.objects.all().prefetch_related(
                        Prefetch(
                            "entrance_ranges",
                            queryset=BuildingEntranceRange.objects.all().order_by("entrance", "apartment_from"),
                        )
                    ),
                )
            )
            .order_by("slug")
        )
        for c in complexes:
            buildings: dict[str, Any] = {}
            for b in c.buildings.all():
                ranges = []
                for r in b.entrance_ranges.all():
                    ranges.append((int(r.entrance), int(r.apartment_from), int(r.apartment_to)))
                buildings[str(b.building_id)] = {"entrance_ranges": ranges}
            db_cfg[str(c.slug)] = {"title": str(c.title), "buildings": buildings}
    except Exception:
        db_cfg = {}

    settings_cfg = getattr(settings, "DBN_COMPLEXES", None)
    if isinstance(settings_cfg, dict):
        merged = dict(settings_cfg)
        merged.update(db_cfg)  # БД перекрывает settings
    else:
        merged = dict(db_cfg)

    _complexes_cfg._cache = {"ts": now_ts, "data": merged}
    return merged


def _normalize_complex_slug(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_building_id(value: str) -> str:
    v = (value or "").strip().lower()
    # Снимаем ведущие нули для числовых идентификаторов домов (например "020" -> "20")
    if v.isdigit():
        v = str(int(v))
    return v


def _settings_complex_cfg(complex_slug: str) -> dict | None:
    cfg = getattr(settings, "DBN_COMPLEXES", None)
    if not isinstance(cfg, dict):
        return None
    return cfg.get(_normalize_complex_slug(complex_slug)) if complex_slug else None


def resolve_complex_building(parsed: dict) -> tuple[ResidentialComplex | None, ComplexBuilding | None]:
    """
    Привязывает parsed username к объектам БД. Если объектов нет — создаёт их
    на основе settings.DBN_COMPLEXES (если возможно), либо создаёт "пустые"
    сущности (без диапазонов).
    """

    complex_slug = _normalize_complex_slug(parsed.get("complex") or "")
    building_id = _normalize_building_id(parsed.get("building") or "")

    if not complex_slug:
        # Старый формат: считаем что это "первый" комплекс.
        first = ResidentialComplex.objects.order_by("slug").first()
        if first:
            complex_slug = str(first.slug)
        else:
            # fallback to settings
            cfg = _complexes_cfg()
            complex_slug = _normalize_complex_slug(next(iter(cfg.keys()), "default")) or "default"

    complex_obj = ResidentialComplex.objects.filter(slug=complex_slug).first()
    if complex_obj is None:
        s_cfg = _settings_complex_cfg(complex_slug) or {}
        title = str(s_cfg.get("title") or complex_slug.upper())
        complex_obj = ResidentialComplex.objects.create(slug=complex_slug, title=title)

    if not building_id:
        # Если дом не задан (старый формат), берём первый дом или создаём "1".
        b = ComplexBuilding.objects.filter(complex=complex_obj).order_by("building_id").first()
        if b:
            building_obj = b
        else:
            building_obj = ComplexBuilding.objects.create(complex=complex_obj, building_id="1", title="")
        return complex_obj, building_obj

    building_obj = ComplexBuilding.objects.filter(complex=complex_obj, building_id=building_id).first()
    if building_obj is None:
        building_obj = ComplexBuilding.objects.create(complex=complex_obj, building_id=building_id, title="")

    # Если это дом из settings и диапазоны ещё не заполнены — зальём их.
    if not BuildingEntranceRange.objects.filter(building=building_obj).exists():
        s_cfg = _settings_complex_cfg(complex_slug) or {}
        buildings = (s_cfg or {}).get("buildings") if isinstance(s_cfg, dict) else {}
        b_cfg = (buildings or {}).get(building_id) if isinstance(buildings, dict) else None
        ranges = (b_cfg or {}).get("entrance_ranges") or []
        to_create = []
        for ent, start, end in ranges:
            try:
                to_create.append(
                    BuildingEntranceRange(
                        building=building_obj,
                        entrance=int(ent),
                        apartment_from=int(start),
                        apartment_to=int(end),
                        created_at=timezone.now(),
                    )
                )
            except Exception:
                continue
        if to_create:
            BuildingEntranceRange.objects.bulk_create(to_create)

    return complex_obj, building_obj


def _entrance_for_apartment(complex_slug: str, building_id: str, apartment: int) -> int | None:
    complex_slug = _normalize_complex_slug(complex_slug)
    building_id = _normalize_building_id(building_id)
    buildings = _complexes_cfg().get(complex_slug, {}).get("buildings", {})
    bcfg = buildings.get(building_id) if isinstance(buildings, dict) else None
    ranges = (bcfg or {}).get("entrance_ranges") or []
    for ent, start, end in ranges:
        try:
            if int(start) <= int(apartment) <= int(end):
                return int(ent)
        except Exception:
            continue
    return None


def parse_username(username: str) -> dict | None:
    """
    Возвращает словарь:
      {
        "username": <raw>,
        "complex": <slug|None>,
        "building": <id|None>,
        "entrance": <int>,
        "apartment": <int>,
      }
    Поддерживаемые форматы:
      - старый: "12-1" (квартира-подъезд)
      - новый (с дефисами): "nasip-20-4-220"
      - новый (компактный): "nasip204220"
    """
    raw = (username or "").strip()
    if not raw:
        return None

    m = OLD_USERNAME_RE.match(raw)
    if m:
        try:
            return {
                "username": raw,
                "complex": None,
                "building": None,
                "entrance": int(m.group("entrance")),
                "apartment": int(m.group("apartment")),
            }
        except Exception:
            return None

    m = NEW_USERNAME_SPLIT_RE.match(raw)
    if m:
        complex_slug = _normalize_complex_slug(m.group("complex"))
        building_id = _normalize_building_id(m.group("building"))
        try:
            entrance = int(m.group("entrance"))
            apartment = int(m.group("apartment"))
        except Exception:
            return None

        cfg = _complexes_cfg()
        if complex_slug not in cfg:
            return None
        buildings = cfg.get(complex_slug, {}).get("buildings", {})
        if building_id not in (buildings or {}):
            return None

        ranges = (buildings.get(building_id) or {}).get("entrance_ranges") or []
        expected = _entrance_for_apartment(complex_slug, building_id, apartment)
        if apartment <= 0:
            return None
        if ranges and expected is None:
            return None
        if expected is not None and int(expected) != int(entrance):
            return None

        return {
            "username": raw,
            "complex": complex_slug,
            "building": building_id,
            "entrance": entrance,
            "apartment": apartment,
        }

    cfg = _complexes_cfg()
    raw_l = raw.lower()
    complex_slug = None
    rest = ""
    for slug in sorted(cfg.keys(), key=len, reverse=True):
        if raw_l.startswith(slug.lower()):
            complex_slug = _normalize_complex_slug(slug)
            rest = raw_l[len(slug) :].strip()
            break
    if not complex_slug or not rest:
        return None

    buildings = cfg.get(complex_slug, {}).get("buildings", {}) or {}
    if not isinstance(buildings, dict):
        return None

    # 1) Попытка: rest начинается с известного building_id
    for building_id_raw in sorted(buildings.keys(), key=len, reverse=True):
        building_id = _normalize_building_id(building_id_raw)
        if not rest.startswith(building_id):
            continue
        tail = rest[len(building_id) :]
        if not tail:
            continue

        # Вариант A: есть подъезд (1–2 цифры) + квартира (остальные цифры)
        if tail.isdigit() and len(tail) >= 2:
            for ent_len in (1, 2):
                if len(tail) <= ent_len:
                    continue
                ent_s = tail[:ent_len]
                apt_s = tail[ent_len:]
                if not ent_s.isdigit() or not apt_s.isdigit():
                    continue
                entrance = int(ent_s)
                apartment = int(apt_s)
                if apartment <= 0:
                    continue
                ranges = (buildings.get(building_id) or {}).get("entrance_ranges") or []
                expected = _entrance_for_apartment(complex_slug, building_id, apartment)
                if ranges and expected is None:
                    continue
                if expected is not None and int(expected) != int(entrance):
                    continue
                return {
                    "username": raw,
                    "complex": complex_slug,
                    "building": building_id,
                    "entrance": entrance,
                    "apartment": apartment,
                }

        # Вариант B: без подъезда (building + apartment), подъезд считаем по диапазонам
        if tail.isdigit():
            apartment = int(tail)
            if apartment <= 0:
                continue
            entrance = _entrance_for_apartment(complex_slug, building_id, apartment)
            if entrance is not None:
                return {
                    "username": raw,
                    "complex": complex_slug,
                    "building": building_id,
                    "entrance": int(entrance),
                    "apartment": apartment,
                }

    # 2) Брутфорс: апартаменты с конца, подъезд 1–2 цифры, building = остальное
    if rest.isdigit():
        for apt_len in (4, 3, 2, 1):
            if len(rest) <= apt_len:
                continue
            apt_s = rest[-apt_len:]
            prefix = rest[: -apt_len]
            if not apt_s.isdigit():
                continue
            apartment = int(apt_s)
            if apartment <= 0:
                continue
            for ent_len in (2, 1):
                if len(prefix) <= ent_len:
                    continue
                ent_s = prefix[-ent_len:]
                bld_s = prefix[: -ent_len]
                building_id = _normalize_building_id(bld_s)
                if building_id not in buildings:
                    continue
                if not ent_s.isdigit():
                    continue
                entrance = int(ent_s)
                ranges = (buildings.get(building_id) or {}).get("entrance_ranges") or []
                expected = _entrance_for_apartment(complex_slug, building_id, apartment)
                if ranges and expected is None:
                    continue
                if expected is not None and int(expected) != int(entrance):
                    continue
                return {
                    "username": raw,
                    "complex": complex_slug,
                    "building": building_id,
                    "entrance": entrance,
                    "apartment": apartment,
                }

    return None


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        username = auth_username_from_request(request)
        if not username:
            return json_error("Unauthorized", status=401)

        parsed = parse_username(username)
        if not parsed:
            return json_error("Unauthorized", status=401)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return json_error("Unauthorized", status=401)

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
        # На случай если username/правила изменились, синхронизируем значения.
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

        request.user = user
        request.profile = profile
        return view_func(request, *args, **kwargs)

    return wrapper
