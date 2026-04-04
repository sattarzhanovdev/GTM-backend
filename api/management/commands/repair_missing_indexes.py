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

            # Normalize DB state to make "RenameIndex(old -> new)" migrations succeed:
            # - drop `new` if it already exists
            # - ensure `old` exists
            #
            # This avoids two common SQLite failures:
            # - "no such index: <old>" when dropping old
            # - "index <new> already exists" when creating new
            rename_pairs = [
                # pushdevice.token_type
                (
                    "api_pushdevice",
                    "api_pushdev_token_t_d9f802_idx",
                    "CREATE INDEX IF NOT EXISTS api_pushdev_token_t_d9f802_idx ON api_pushdevice (token_type);",
                    "api_pushdev_token_t_8886d9_idx",
                ),
                # accountdeletionrequest.status / created_at
                (
                    "api_accountdeletionrequest",
                    "api_accountd_status_ee69c6_idx",
                    "CREATE INDEX IF NOT EXISTS api_accountd_status_ee69c6_idx ON api_accountdeletionrequest (status);",
                    "api_account_status_432e3a_idx",
                ),
                (
                    "api_accountdeletionrequest",
                    "api_accountd_created_2ab7de_idx",
                    "CREATE INDEX IF NOT EXISTS api_accountd_created_2ab7de_idx ON api_accountdeletionrequest (created_at);",
                    "api_account_created_ab502a_idx",
                ),
                # expense.occurred_at / created_at / currency
                (
                    "api_expense",
                    "api_expense_occurre_1ce7c7_idx",
                    "CREATE INDEX IF NOT EXISTS api_expense_occurre_1ce7c7_idx ON api_expense (occurred_at);",
                    "api_expense_occurre_048890_idx",
                ),
                (
                    "api_expense",
                    "api_expense_created_79a719_idx",
                    "CREATE INDEX IF NOT EXISTS api_expense_created_79a719_idx ON api_expense (created_at);",
                    "api_expense_created_0f1467_idx",
                ),
                (
                    "api_expense",
                    "api_expense_currency_6020c0_idx",
                    "CREATE INDEX IF NOT EXISTS api_expense_currency_6020c0_idx ON api_expense (currency);",
                    "api_expense_currenc_4186c3_idx",
                ),
                # expensecategory.is_active / sort_order
                (
                    "api_expensecategory",
                    "api_expensec_is_acti_3c2db0_idx",
                    "CREATE INDEX IF NOT EXISTS api_expensec_is_acti_3c2db0_idx ON api_expensecategory (is_active);",
                    "api_expense_is_acti_ef217c_idx",
                ),
                (
                    "api_expensecategory",
                    "api_expensec_sort_o_820443_idx",
                    "CREATE INDEX IF NOT EXISTS api_expensec_sort_o_820443_idx ON api_expensecategory (sort_order);",
                    "api_expense_sort_or_d35c4a_idx",
                ),
                # fundopeningbalance.month / currency
                (
                    "api_fundopeningbalance",
                    "api_fundopen_month_72e5ef_idx",
                    "CREATE INDEX IF NOT EXISTS api_fundopen_month_72e5ef_idx ON api_fundopeningbalance (month);",
                    "api_fundope_month_305e21_idx",
                ),
                (
                    "api_fundopeningbalance",
                    "api_fundopen_currency_a4ff67_idx",
                    "CREATE INDEX IF NOT EXISTS api_fundopen_currency_a4ff67_idx ON api_fundopeningbalance (currency);",
                    "api_fundope_currenc_ab5b26_idx",
                ),
            ]

            def _refresh(table: str) -> set[str]:
                cursor.execute(f"PRAGMA index_list('{table}');")
                return {row[1] for row in cursor.fetchall() if len(row) > 1}

            # Build index list per table as needed
            index_cache: dict[str, set[str]] = {"api_pushdevice": existing}

            for table, old_name, create_old_sql, new_name in rename_pairs:
                # Skip tables that do not exist yet (early in migration graph)
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}';")
                if cursor.fetchone() is None:
                    continue

                table_indexes = index_cache.get(table)
                if table_indexes is None:
                    table_indexes = _refresh(table)
                    index_cache[table] = table_indexes

                if new_name in table_indexes:
                    cursor.execute(f"DROP INDEX IF EXISTS {new_name};")
                    fixed += 1
                    self.stdout.write(self.style.SUCCESS(f"Dropped index: {new_name}"))
                    table_indexes = _refresh(table)
                    index_cache[table] = table_indexes

                if old_name not in table_indexes:
                    cursor.execute(create_old_sql)
                    fixed += 1
                    self.stdout.write(self.style.SUCCESS(f"Created index: {old_name}"))
                    table_indexes = _refresh(table)
                    index_cache[table] = table_indexes

        self.stdout.write(self.style.SUCCESS(f"Done. fixed={fixed}"))
