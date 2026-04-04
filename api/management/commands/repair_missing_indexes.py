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

            wanted = {
                "api_pushdev_token_t_d9f802_idx": "CREATE INDEX IF NOT EXISTS api_pushdev_token_t_d9f802_idx ON api_pushdevice (token_type);",
            }

            for name, sql in wanted.items():
                if name in existing:
                    continue
                cursor.execute(sql)
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f"Created index: {name}"))

        self.stdout.write(self.style.SUCCESS(f"Done. fixed={fixed}"))

