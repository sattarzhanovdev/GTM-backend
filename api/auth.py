from __future__ import annotations

import json
import re
from datetime import timedelta
from functools import wraps

from django.contrib.auth.models import User
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import JsonResponse
from django.utils import timezone

from .models import Profile

USERNAME_RE = re.compile(r"^(?P<apartment>\d+)-(?P<entrance>\d+)$")
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
    return TimestampSigner(salt="gtm-api-token")


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


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        username = auth_username_from_request(request)
        if not username:
            return json_error("Unauthorized", status=401)

        match = USERNAME_RE.match(username)
        if not match:
            return json_error("Unauthorized", status=401)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return json_error("Unauthorized", status=401)

        profile, _ = Profile.objects.get_or_create(
            user=user,
            defaults={
                "apartment": int(match.group("apartment")),
                "entrance": int(match.group("entrance")),
                "created_at": timezone.now(),
            },
        )

        request.user = user
        request.profile = profile
        return view_func(request, *args, **kwargs)

    return wrapper

