from __future__ import annotations

import csv
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import ApartmentMember, BuildingEntranceRange, ComplexBuilding, Profile, ResidentialComplex


@dataclass(frozen=True)
class EntranceRange:
    entrance: int
    apartment_from: int
    apartment_to: int


EL_NASIP_RANGES: dict[str, list[EntranceRange]] = {
    # По PDF "номерация.pdf"
    "20": [
        EntranceRange(1, 1, 63),
        EntranceRange(2, 64, 117),
        EntranceRange(3, 118, 171),
        EntranceRange(4, 172, 225),
        EntranceRange(5, 226, 279),
    ],
    "18": [
        EntranceRange(1, 1, 54),
        EntranceRange(2, 55, 108),
    ],
    "d": [
        EntranceRange(1, 1, 56),
        EntranceRange(2, 57, 112),
    ],
    "e": [
        EntranceRange(3, 113, 162),
        EntranceRange(4, 163, 212),
    ],
}


class Command(BaseCommand):
    help = "Seed accounts for ЖК Эл Насип (code EN): complexes/buildings/ranges + Django users/profiles."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="en", help="Complex code for login (default: en)")
        parser.add_argument("--title", default="Эл Насип", help="Complex title (default: Эл Насип)")
        parser.add_argument("--dry-run", action="store_true", default=False, help="Do not write to DB; only print counts.")
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            default=False,
            help="Reset existing user passwords to apartment number.",
        )
        parser.add_argument(
            "--output-csv",
            default="",
            help="Optional path to write CSV with columns username,password (e.g. /tmp/en_accounts.csv).",
        )

    def handle(self, *args, **options):
        slug = str(options.get("slug") or "en").strip().lower()
        title = str(options.get("title") or slug.upper()).strip() or slug.upper()
        dry_run = bool(options.get("dry_run"))
        reset_passwords = bool(options.get("reset_passwords"))
        output_csv = str(options.get("output_csv") or "").strip()

        # Pre-calc number of users
        total = 0
        for b_id, ranges in EL_NASIP_RANGES.items():
            for r in ranges:
                total += int(r.apartment_to) - int(r.apartment_from) + 1
        self.stdout.write(f"Will generate: {total} users for complex '{slug}'")
        if dry_run:
            return

        csv_rows: list[tuple[str, str]] = []
        created_users = 0
        updated_passwords = 0
        created_profiles = 0
        updated_profiles = 0
        created_members = 0

        with transaction.atomic():
            complex_obj, _ = ResidentialComplex.objects.get_or_create(slug=slug, defaults={"title": title})
            if complex_obj.title != title and title:
                complex_obj.title = title
                complex_obj.save(update_fields=["title"])

            for building_id, ranges in EL_NASIP_RANGES.items():
                building_obj, _ = ComplexBuilding.objects.get_or_create(
                    complex=complex_obj,
                    building_id=str(building_id).lower(),
                    defaults={"title": ""},
                )

                # Ensure entrance ranges exist
                for r in ranges:
                    BuildingEntranceRange.objects.get_or_create(
                        building=building_obj,
                        entrance=int(r.entrance),
                        apartment_from=int(r.apartment_from),
                        apartment_to=int(r.apartment_to),
                        defaults={"created_at": timezone.now()},
                    )

                for r in ranges:
                    for apt in range(int(r.apartment_from), int(r.apartment_to) + 1):
                        username = f"{complex_obj.slug}{building_obj.building_id}{int(r.entrance)}{int(apt)}"
                        password = str(int(apt))

                        user, created = User.objects.get_or_create(username=username)
                        if created:
                            user.set_password(password)
                            user.save(update_fields=["password"])
                            created_users += 1
                        elif reset_passwords:
                            user.set_password(password)
                            user.save(update_fields=["password"])
                            updated_passwords += 1

                        profile, p_created = Profile.objects.get_or_create(
                            user=user,
                            defaults={
                                "complex": complex_obj,
                                "building": building_obj,
                                "apartment": int(apt),
                                "entrance": int(r.entrance),
                                "created_at": timezone.now(),
                            },
                        )
                        if p_created:
                            created_profiles += 1
                        else:
                            changed = []
                            if profile.complex_id != complex_obj.id:
                                profile.complex = complex_obj
                                changed.append("complex")
                            if profile.building_id != building_obj.id:
                                profile.building = building_obj
                                changed.append("building")
                            if profile.apartment != int(apt):
                                profile.apartment = int(apt)
                                changed.append("apartment")
                            if profile.entrance != int(r.entrance):
                                profile.entrance = int(r.entrance)
                                changed.append("entrance")
                            if changed:
                                profile.save(update_fields=[*changed, "updated_at"])
                                updated_profiles += 1

                        _, m_created = ApartmentMember.objects.get_or_create(
                            building=building_obj,
                            apartment=int(apt),
                            is_primary=True,
                            defaults={
                                "full_name": profile.full_name or f"Квартира {apt}",
                                "phone_number": profile.phone_number,
                                "code": f"{int(apt):02d}KG{int(r.entrance):02d}",
                                "created_at": timezone.now(),
                            },
                        )
                        if m_created:
                            created_members += 1

                        if output_csv:
                            csv_rows.append((username, password))

        if output_csv:
            with open(output_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["username", "password"])
                w.writerows(csv_rows)

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"users(created={created_users}, passwords_reset={updated_passwords}), "
                f"profiles(created={created_profiles}, updated={updated_profiles}), "
                f"members(created={created_members})."
            )
        )

