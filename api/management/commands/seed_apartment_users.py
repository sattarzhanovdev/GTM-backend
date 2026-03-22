from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import Profile


@dataclass(frozen=True)
class SeedUser:
    username: str
    password: str
    apartment: int
    entrance: int


def _iter_seed_users(complex_slug: str | None = None, building_id: str | None = None):
    complexes = getattr(settings, "GTM_COMPLEXES", None)
    if not isinstance(complexes, dict):
        return

    for c_slug, c_cfg in complexes.items():
        if complex_slug and str(c_slug).lower() != str(complex_slug).lower():
            continue
        buildings = (c_cfg or {}).get("buildings") or {}
        if not isinstance(buildings, dict):
            continue

        for b_id, b_cfg in buildings.items():
            if building_id and str(b_id).lower() != str(building_id).lower():
                continue
            ranges = (b_cfg or {}).get("entrance_ranges") or []
            for ent, start, end in ranges:
                try:
                    ent_i = int(ent)
                    start_i = int(start)
                    end_i = int(end)
                except Exception:
                    continue
                for apt in range(start_i, end_i + 1):
                    username = f"{str(c_slug).lower()}{str(b_id).lower()}{ent_i}{apt}"
                    yield SeedUser(
                        username=username,
                        password=str(apt),
                        apartment=int(apt),
                        entrance=int(ent_i),
                    )


class Command(BaseCommand):
    help = "Create Django users for apartments based on settings.GTM_COMPLEXES."

    def add_arguments(self, parser):
        parser.add_argument("--complex", dest="complex_slug", default=None, help="Complex slug (e.g. nasip)")
        parser.add_argument("--building", dest="building_id", default=None, help="Building id (e.g. 20, 18, d, e)")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Do not write to DB; only print counts.",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            default=False,
            help="Reset existing user passwords to apartment number.",
        )

    def handle(self, *args, **options):
        complex_slug: str | None = options.get("complex_slug")
        building_id: str | None = options.get("building_id")
        dry_run: bool = bool(options.get("dry_run"))
        reset_passwords: bool = bool(options.get("reset_passwords"))

        created_users = 0
        updated_passwords = 0
        created_profiles = 0
        updated_profiles = 0
        total = 0

        seed_users = list(_iter_seed_users(complex_slug=complex_slug, building_id=building_id))
        if not seed_users:
            self.stdout.write(self.style.WARNING("No users generated. Check GTM_COMPLEXES and filters."))
            return

        self.stdout.write(f"Generated: {len(seed_users)} users")
        if dry_run:
            return

        with transaction.atomic():
            for su in seed_users:
                total += 1
                user, created = User.objects.get_or_create(username=su.username)
                if created:
                    user.set_password(su.password)
                    user.save(update_fields=["password"])
                    created_users += 1
                elif reset_passwords:
                    user.set_password(su.password)
                    user.save(update_fields=["password"])
                    updated_passwords += 1

                profile, p_created = Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        "apartment": su.apartment,
                        "entrance": su.entrance,
                        "created_at": timezone.now(),
                    },
                )
                if p_created:
                    created_profiles += 1
                else:
                    if profile.apartment != su.apartment or profile.entrance != su.entrance:
                        profile.apartment = su.apartment
                        profile.entrance = su.entrance
                        profile.save(update_fields=["apartment", "entrance", "updated_at"])
                        updated_profiles += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"users(created={created_users}, passwords_reset={updated_passwords}), "
                f"profiles(created={created_profiles}, updated={updated_profiles})."
            )
        )

