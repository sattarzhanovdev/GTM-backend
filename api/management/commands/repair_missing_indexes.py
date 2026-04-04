from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Repair missing DB indexes that some migrations expect (useful for SQLite after manual DB edits)."

    def handle(self, *args, **options):
        fixed = 0
        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor != "sqlite":
                self.stdout.write(self.style.WARNING(f"DB vendor is '{vendor}'. Nothing to repair."))
                return

            # Ensure table exists before touching indexes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_pushdevice';")
            if cursor.fetchone() is None:
                self.stdout.write(self.style.WARNING("Table api_pushdevice not found. Run migrations first."))
                return

            cursor.execute("PRAGMA index_list('api_pushdevice');")
            existing = {row[1] for row in cursor.fetchall() if len(row) > 1}

            old_name = "api_pushdev_token_t_d9f802_idx"
            new_name = "api_pushdev_token_t_8886d9_idx"
            create_old = f"CREATE INDEX IF NOT EXISTS {old_name} ON api_pushdevice (token_type);"
            drop_new = f"DROP INDEX IF EXISTS {new_name};"

            # Some codebases have a migration that renames old_name -> new_name.
            # If the DB already contains new_name but not old_name, that migration fails
            # because it tries to CREATE new_name first.
            #
            # To make migrations deterministic:
            # - ensure old_name exists
            # - ensure new_name does NOT exist (so rename can succeed)
            if new_name in existing and old_name not in existing:
                cursor.execute(drop_new)
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f"Dropped conflicting index: {new_name}"))
                # Refresh the index list so next checks are accurate.
                cursor.execute("PRAGMA index_list('api_pushdevice');")
                existing = {row[1] for row in cursor.fetchall() if len(row) > 1}

            if old_name not in existing:
                cursor.execute(create_old)
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f"Created index: {old_name}"))

        self.stdout.write(self.style.SUCCESS(f"Done. fixed={fixed}"))
