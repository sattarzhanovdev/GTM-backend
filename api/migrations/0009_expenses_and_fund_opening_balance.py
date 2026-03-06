from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0008_accountdeletionrequest"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Название")),
                ("sort_order", models.PositiveIntegerField(default=100, verbose_name="Порядок")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активно")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="Создано")),
            ],
            options={
                "verbose_name": "Категория расходов",
                "verbose_name_plural": "Категории расходов",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="FundOpeningBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "month",
                    models.DateField(
                        help_text="Первый день месяца (например 2026-01-01)",
                        unique=True,
                        verbose_name="Месяц",
                    ),
                ),
                ("amount", models.IntegerField(verbose_name="Остаток на начало месяца")),
                ("currency", models.CharField(default="сом", max_length=16, verbose_name="Валюта")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Остаток фонда (месяц)",
                "verbose_name_plural": "Остатки фонда (месяцы)",
            },
        ),
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.PositiveIntegerField(verbose_name="Сумма")),
                ("currency", models.CharField(default="сом", max_length=16, verbose_name="Валюта")),
                ("occurred_at", models.DateField(verbose_name="Дата")),
                ("note", models.CharField(blank=True, default="", max_length=300, verbose_name="Комментарий")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="Создано")),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="expenses",
                        to="api.expensecategory",
                        verbose_name="Категория",
                    ),
                ),
            ],
            options={
                "verbose_name": "Расход",
                "verbose_name_plural": "Расходы",
            },
        ),
        migrations.AddIndex(
            model_name="expensecategory",
            index=models.Index(fields=["is_active"], name="api_expensec_is_acti_3c2db0_idx"),
        ),
        migrations.AddIndex(
            model_name="expensecategory",
            index=models.Index(fields=["sort_order"], name="api_expensec_sort_o_820443_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["occurred_at"], name="api_expense_occurre_1ce7c7_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["created_at"], name="api_expense_created_79a719_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["currency"], name="api_expense_currency_6020c0_idx"),
        ),
        migrations.AddIndex(
            model_name="fundopeningbalance",
            index=models.Index(fields=["month"], name="api_fundopen_month_72e5ef_idx"),
        ),
        migrations.AddIndex(
            model_name="fundopeningbalance",
            index=models.Index(fields=["currency"], name="api_fundopen_currency_a4ff67_idx"),
        ),
    ]

