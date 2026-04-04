from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import BuildingEntranceRange, ComplexBuilding, Profile, ResidentialComplex


@dataclass(frozen=True)
class SeedUser:
    username: str
    password: str
    apartment: int
    entrance: int
    complex_slug: str
    building_id: str


def _iter_seed_users(complex_slug: str | None = None, building_id: str | None = None):
    # 1) Если есть ЖК в БД — используем их (админ может добавлять новые).
    if ResidentialComplex.objects.exists():
        buildings_qs = ComplexBuilding.objects.select_related("complex").order_by("complex__slug", "building_id")
        if complex_slug:
            buildings_qs = buildings_qs.filter(complex__slug=str(complex_slug).lower())
        if building_id:
            buildings_qs = buildings_qs.filter(building_id=str(building_id).lower())

        for b in buildings_qs:
            ranges = BuildingEntranceRange.objects.filter(building=b).order_by("entrance", "apartment_from")
            for r in ranges:
                for apt in range(int(r.apartment_from), int(r.apartment_to) + 1):
                    username = f"{b.complex.slug}{b.building_id}{int(r.entrance)}{int(apt)}"
                    yield SeedUser(
                        username=username,
                        password=str(apt),
                        apartment=int(apt),
                        entrance=int(r.entrance),
                        complex_slug=str(b.complex.slug),
                        building_id=str(b.building_id),
                    )
        return

    # 2) Fallback: старый конфиг из settings.DBN_COMPLEXES
    complexes = getattr(settings, "DBN_COMPLEXES", None)
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
                    # NOTE: complex/building here нужны для профиля/скоупа.
                    # В settings ключи уже в нужном виде.
                    yield SeedUser(
                        username=username,
                        password=str(apt),
                        apartment=int(apt),
                        entrance=int(ent_i),
                        complex_slug=str(c_slug).lower(),
                        building_id=str(b_id).lower(),
                    )


class Command(BaseCommand):
    help = "Create Django users for apartments based on settings.DBN_COMPLEXES."

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
            self.stdout.write(self.style.WARNING("No users generated. Check DBN_COMPLEXES and filters."))
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

                complex_obj = ResidentialComplex.objects.filter(slug=str(su.complex_slug).lower()).first()
                if complex_obj is None:
                    complex_obj = ResidentialComplex.objects.create(slug=str(su.complex_slug).lower(), title=str(su.complex_slug).upper())
                building_obj = None
                building_obj = ComplexBuilding.objects.filter(complex=complex_obj, building_id=str(su.building_id).lower()).first()
                if building_obj is None:
                    building_obj = ComplexBuilding.objects.create(complex=complex_obj, building_id=str(su.building_id).lower(), title="")

                profile, p_created = Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        "complex": complex_obj,
                        "building": building_obj,
                        "apartment": su.apartment,
                        "entrance": su.entrance,
                        "created_at": timezone.now(),
                    },
                )
                if p_created:
                    created_profiles += 1
                else:
                    changed = []
                    if profile.apartment != su.apartment:
                        profile.apartment = su.apartment
                        changed.append("apartment")
                    if profile.entrance != su.entrance:
                        profile.entrance = su.entrance
                        changed.append("entrance")
                    if complex_obj and profile.complex_id != complex_obj.id:
                        profile.complex = complex_obj
                        changed.append("complex")
                    if building_obj and profile.building_id != building_obj.id:
                        profile.building = building_obj
                        changed.append("building")
                    if changed:
                        profile.save(update_fields=[*changed, "updated_at"])
                        updated_profiles += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"users(created={created_users}, passwords_reset={updated_passwords}), "
                f"profiles(created={created_profiles}, updated={updated_profiles})."
            )
        )
