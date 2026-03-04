from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    entrance = models.PositiveIntegerField(verbose_name="Подъезд")

    full_name = models.CharField("ФИО", max_length=200, blank=True, default="")
    phone_number = models.CharField("Телефон", max_length=32, blank=True, default="")

    is_payed = models.BooleanField("Оплачено", default=True)
    is_accept = models.BooleanField("Подтверждён", default=True)
    is_blocked = models.BooleanField("Заблокирован", default=False)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"
        indexes = [
            models.Index(fields=["apartment"]),
            models.Index(fields=["apartment", "entrance"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} (apt {self.apartment}, ent {self.entrance})"


class ApartmentMember(models.Model):
    apartment = models.PositiveIntegerField(verbose_name="Квартира")

    full_name = models.CharField("ФИО", max_length=200)
    phone_number = models.CharField("Телефон", max_length=32, blank=True, default="")
    code = models.CharField("Код", max_length=32, blank=True, default="")

    is_primary = models.BooleanField("Основной", default=False)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Пользователь квартиры"
        verbose_name_plural = "Пользователи квартиры"
        indexes = [models.Index(fields=["apartment"])]

    def __str__(self) -> str:
        return f"{self.full_name} (apt {self.apartment})"


class Notification(models.Model):
    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    title = models.CharField("Заголовок", max_length=200)
    body = models.TextField("Текст", blank=True, default="")
    is_read = models.BooleanField("Прочитано", default=False)
    push_sent_at = models.DateTimeField("Push отправлен", null=True, blank=True)
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        indexes = [models.Index(fields=["apartment"]), models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        return f"{self.title} (apt {self.apartment})"


class PushDevice(models.Model):
    token = models.CharField("Expo push token", max_length=255, unique=True)
    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    entrance = models.PositiveIntegerField(verbose_name="Подъезд")
    platform = models.CharField("Платформа", max_length=20, blank=True, default="")
    is_active = models.BooleanField("Активно", default=True)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Устройство (push)"
        verbose_name_plural = "Устройства (push)"
        indexes = [models.Index(fields=["apartment"]), models.Index(fields=["is_active"])]

    def __str__(self) -> str:
        return f"{self.apartment} {self.platform} {self.token[:18]}…"


class PaymentCharge(models.Model):
    service_name = models.CharField("Название", max_length=100)
    amount = models.PositiveIntegerField("Сумма")
    currency = models.CharField("Валюта", max_length=16, default="сом")

    payment_url = models.URLField("Ссылка на оплату", max_length=500, blank=True, default="")
    due_date = models.DateField("Срок оплаты", null=True, blank=True)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Начисление"
        verbose_name_plural = "Начисления"
        indexes = [models.Index(fields=["due_date"])]

    def __str__(self) -> str:
        return f"{self.service_name} {self.amount}{self.currency}"


class PaymentParticipation(models.Model):
    class Status(models.TextChoices):
        DUE = "due", "К оплате"
        PAID = "paid", "Оплачено"
        PENDING = "pending", "На рассмотрении"
        ACCEPTED = "accepted", "Принято"

    payment = models.ForeignKey(
        PaymentCharge,
        on_delete=models.CASCADE,
        related_name="participations",
        verbose_name="Начисление",
    )

    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    entrance = models.PositiveIntegerField(verbose_name="Подъезд")

    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.DUE)
    status_updated_at = models.DateTimeField("Статус обновлён", default=timezone.now)
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Оплата (квартира)"
        verbose_name_plural = "Оплаты (квартиры)"
        constraints = [
            models.UniqueConstraint(fields=["payment", "apartment"], name="uniq_payment_apartment"),
        ]
        indexes = [
            models.Index(fields=["apartment"]),
            models.Index(fields=["apartment", "status"]),
            models.Index(fields=["status_updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.payment} (apt {self.apartment})"


class Receipt(models.Model):
    participation = models.ForeignKey(
        PaymentParticipation,
        on_delete=models.CASCADE,
        related_name="receipts",
        null=True,
        blank=True,
        verbose_name="Оплата (квартира)",
    )
    file = models.FileField("Файл", upload_to="receipts/")
    uploaded_at = models.DateTimeField("Загружено", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Чек"
        verbose_name_plural = "Чеки"


class DevicePulse(models.Model):
    key = models.CharField("Ключ", max_length=64, unique=True)
    active_until = models.DateTimeField("Активно до", null=True, blank=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Состояние устройства"
        verbose_name_plural = "Состояния устройств"

    def is_active(self) -> bool:
        if not self.active_until:
            return False
        return timezone.now() < self.active_until
