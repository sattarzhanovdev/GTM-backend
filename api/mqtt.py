from __future__ import annotations

import json
import os
from typing import Any

from django.conf import settings

from .models import Profile

try:
    from paho.mqtt import publish as mqtt_publish
except Exception:  # pragma: no cover - optional dependency in dev
    mqtt_publish = None


def _setting(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value not in (None, ""):
        return str(value)
    return str(getattr(settings, name, default) or default)


def mqtt_enabled() -> bool:
    return bool(_setting("MQTT_HOST"))


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_topic(profile: Profile, device_type: str, device_id: str | int) -> str:
    return build_topic_for_scope(
        complex_slug=profile.complex.slug,
        building_id=profile.building.building_id,
        entrance=profile.entrance,
        apartment=profile.apartment,
        device_type=device_type,
        device_id=device_id,
    )


def build_topic_for_scope(
    *,
    complex_slug: str,
    building_id: str,
    entrance: int | None,
    apartment: int | None,
    device_type: str,
    device_id: str | int,
) -> str:
    prefix = _setting("MQTT_TOPIC_PREFIX", "gtm").strip().strip("/")
    template = _setting(
        "MQTT_TOPIC_TEMPLATE",
        "{prefix}/{complex}/{building}/{device_type}/{device_id}/set",
    )
    topic = template.format(
        prefix=prefix,
        complex=complex_slug,
        building=building_id,
        entrance=entrance,
        apartment=apartment,
        device_type=device_type,
        device_id=device_id,
        scope=f"{complex_slug}/{building_id}",
    )
    return "/".join(part for part in str(topic).split("/") if part)


def publish_device_command(
    profile: Profile,
    *,
    device_type: str,
    device_id: str | int,
    action: str = "open",
    value: bool = True,
    seconds: int = 1,
    extra: dict[str, Any] | None = None,
    target_complex: str | None = None,
    target_building: str | None = None,
) -> dict[str, Any]:
    complex_slug = str(target_complex or profile.complex.slug)
    building_id = str(target_building or profile.building.building_id)
    topic = build_topic_for_scope(
        complex_slug=complex_slug,
        building_id=building_id,
        entrance=profile.entrance,
        apartment=profile.apartment,
        device_type=device_type,
        device_id=device_id,
    )
    payload: dict[str, Any] = {
        "action": action,
        "value": value,
        "seconds": seconds,
        "complex": complex_slug,
        "building": building_id,
        "entrance": profile.entrance,
        "apartment": profile.apartment,
        "deviceType": device_type,
        "deviceId": str(device_id),
    }
    if extra:
        payload.update(extra)

    if not mqtt_enabled():
        return {"published": False, "topic": topic, "payload": payload}

    if mqtt_publish is None:
        raise RuntimeError("MQTT dependency is missing. Install paho-mqtt on the backend.")

    auth = None
    username = _setting("MQTT_USERNAME")
    password = _setting("MQTT_PASSWORD")
    if username:
        auth = {"username": username, "password": password}

    tls = None
    if _as_bool(_setting("MQTT_TLS")):
        tls = {}

    mqtt_publish.single(
        topic,
        payload=json.dumps(payload, ensure_ascii=False),
        hostname=_setting("MQTT_HOST"),
        port=int(_setting("MQTT_PORT", "1883")),
        client_id=_setting("MQTT_CLIENT_ID", ""),
        keepalive=int(_setting("MQTT_KEEPALIVE", "30")),
        auth=auth,
        tls=tls,
        qos=int(_setting("MQTT_QOS", "1")),
        retain=_as_bool(_setting("MQTT_RETAIN")),
    )

    return {"published": True, "topic": topic, "payload": payload}
