from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0007_pushdevice_token_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountDeletionRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(blank=True, default="", max_length=300, verbose_name="Причина")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Ожидает"), ("done", "Обработано"), ("rejected", "Отклонено")],
                        default="pending",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="Создано")),
                ("processed_at", models.DateTimeField(blank=True, null=True, verbose_name="Обработано")),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deletion_requests",
                        to="api.profile",
                        verbose_name="Профиль",
                    ),
                ),
            ],
            options={
                "verbose_name": "Запрос на удаление аккаунта",
                "verbose_name_plural": "Запросы на удаление аккаунта",
            },
        ),
        migrations.AddIndex(
            model_name="accountdeletionrequest",
            index=models.Index(fields=["status"], name="api_accountd_status_ee69c6_idx"),
        ),
        migrations.AddIndex(
            model_name="accountdeletionrequest",
            index=models.Index(fields=["created_at"], name="api_accountd_created_2ab7de_idx"),
        ),
    ]

