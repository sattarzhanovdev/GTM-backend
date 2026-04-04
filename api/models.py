from __future__ import annotations

import re

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


_LATIN_CODE_RE = re.compile(r"^[a-z0-9]+$")


class ResidentialComplex(models.Model):
    """
    Жилой комплекс (ЖК) / объект.

    `slug` используется в логине (префикс), например:
      - en204220  (complex=en, building=20, entrance=4, apartment=220)
      - en-20-4-220
    """

    slug = models.CharField(
        "Код (латиница)",
        max_length=32,
        unique=True,
        validators=[RegexValidator(_LATIN_CODE_RE, message="Только латиница/цифры без пробелов (например EN, ART)")],
        help_text="Короткий код для логина (например EN, ART). Хранится в нижнем регистре.",
    )
    title = models.CharField("Название", max_length=120)
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "ЖК"
        verbose_name_plural = "ЖК"
        indexes = [models.Index(fields=["slug"])]

    def save(self, *args, **kwargs):
        self.slug = (self.slug or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} ({self.slug.upper()})"


class ComplexBuilding(models.Model):
    complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.PROTECT,
        related_name="buildings",
        verbose_name="ЖК",
    )
    building_id = models.CharField(
        "Дом/блок",
        max_length=16,
        validators=[RegexValidator(_LATIN_CODE_RE, message="Только латиница/цифры без пробелов (например 20, 18, d)")],
        help_text="Идентификатор дома/блока в логине (например 20, 18, d).",
    )
    title = models.CharField("Название (опц.)", max_length=120, blank=True, default="")
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Дом (ЖК)"
        verbose_name_plural = "Дома (ЖК)"
        constraints = [
            models.UniqueConstraint(fields=["complex", "building_id"], name="uniq_complex_building_id"),
        ]
        indexes = [
            models.Index(fields=["complex", "building_id"]),
        ]

    def save(self, *args, **kwargs):
        v = (self.building_id or "").strip().lower()
        if v.isdigit():
            v = str(int(v))
        self.building_id = v
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = self.title or self.building_id
        return f"{self.complex.slug.upper()} / {label}"


class BuildingEntranceRange(models.Model):
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.CASCADE,
        related_name="entrance_ranges",
        verbose_name="Дом",
    )
    entrance = models.PositiveIntegerField("Подъезд")
    apartment_from = models.PositiveIntegerField("Квартира от")
    apartment_to = models.PositiveIntegerField("Квартира до")
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Диапазон квартир (подъезд)"
        verbose_name_plural = "Диапазоны квартир (подъезды)"
        indexes = [
            models.Index(fields=["building", "entrance"]),
            models.Index(fields=["building", "apartment_from", "apartment_to"]),
        ]

    def save(self, *args, **kwargs):
        if self.apartment_from and self.apartment_to and self.apartment_from > self.apartment_to:
            self.apartment_from, self.apartment_to = self.apartment_to, self.apartment_from
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.building}: ent {self.entrance} ({self.apartment_from}-{self.apartment_to})"


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.PROTECT,
        related_name="profiles",
        verbose_name="ЖК",
    )
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="profiles",
        verbose_name="Дом",
    )
    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    entrance = models.PositiveIntegerField(verbose_name="Подъезд")

    full_name = models.CharField("ФИО", max_length=200, blank=True, default="")
    phone_number = models.CharField("Телефон", max_length=32, blank=True, default="")

    is_payed = models.BooleanField("Оплачено", default=True)
    is_accept = models.BooleanField("Подтверждён", default=True)
    is_blocked = models.BooleanField("Заблокирован", default=False)
    has_parking_access = models.BooleanField("Доступ к парковке", default=False)

    password_changed_at = models.DateTimeField("Пароль сменён", null=True, blank=True)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"
        indexes = [
            models.Index(fields=["complex", "building"]),
            models.Index(fields=["apartment"]),
            models.Index(fields=["apartment", "entrance"]),
            models.Index(fields=["complex", "building", "apartment", "entrance"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} ({self.complex.slug.upper()}/{self.building.building_id} apt {self.apartment}, ent {self.entrance})"


class ApartmentMember(models.Model):
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="apartment_members",
        verbose_name="Дом",
    )
    apartment = models.PositiveIntegerField(verbose_name="Квартира")

    full_name = models.CharField("ФИО", max_length=200)
    phone_number = models.CharField("Телефон", max_length=32, blank=True, default="")
    code = models.CharField("Код", max_length=32, blank=True, default="")

    is_primary = models.BooleanField("Основной", default=False)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Пользователь квартиры"
        verbose_name_plural = "Пользователи квартиры"
        indexes = [
            models.Index(fields=["building", "apartment"]),
            models.Index(fields=["apartment"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.building.complex.slug.upper()}/{self.building.building_id} apt {self.apartment})"


class Notification(models.Model):
    complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.PROTECT,
        related_name="notifications",
        verbose_name="ЖК",
    )
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="notifications",
        verbose_name="Дом",
        null=True,
        blank=True,
    )
    apartment = models.PositiveIntegerField(verbose_name="Квартира", null=True, blank=True)
    title = models.CharField("Заголовок", max_length=200)
    body = models.TextField("Текст", blank=True, default="")
    is_read = models.BooleanField("Прочитано", default=False)
    push_sent_at = models.DateTimeField("Push отправлен", null=True, blank=True)
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        indexes = [
            models.Index(fields=["complex", "building", "apartment"]),
            models.Index(fields=["apartment"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        scope = "всем"
        if self.apartment is not None:
            scope = f"кв {self.apartment}"
        cx = self.complex.slug.upper()
        b = self.building.building_id if self.building_id and self.building else "*"
        return f"{self.title} ({cx}/{b} {scope})"


class PushDevice(models.Model):
    class TokenType(models.TextChoices):
        EXPO = "expo", "Expo"
        FCM = "fcm", "FCM"

    token = models.CharField("Expo push token", max_length=255, unique=True)
    token_type = models.CharField("Тип токена", max_length=10, choices=TokenType.choices, default=TokenType.EXPO)
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="push_devices",
        verbose_name="Дом",
    )
    apartment = models.PositiveIntegerField(verbose_name="Квартира")
    entrance = models.PositiveIntegerField(verbose_name="Подъезд")
    platform = models.CharField("Платформа", max_length=20, blank=True, default="")
    is_active = models.BooleanField("Активно", default=True)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Устройство (push)"
        verbose_name_plural = "Устройства (push)"
        indexes = [
            models.Index(fields=["building", "apartment"]),
            models.Index(fields=["apartment"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["token_type"], name="api_pushdev_token_t_d9f802_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.apartment} {self.platform} {self.token_type} {self.token[:18]}…"


class PaymentCharge(models.Model):
    complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.PROTECT,
        related_name="payment_charges",
        verbose_name="ЖК",
    )
    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="payment_charges",
        verbose_name="Дом (опц.)",
        null=True,
        blank=True,
        help_text="Если заполнено — начисление видят только жители этого дома.",
    )
    service_name = models.CharField("Название", max_length=100)
    amount = models.PositiveIntegerField("Сумма")
    currency = models.CharField("Валюта", max_length=16, default="сом")

    payment_url = models.URLField("Ссылка на оплату", max_length=500, blank=True, default="")
    due_date = models.DateField("Срок оплаты", null=True, blank=True)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Начисление"
        verbose_name_plural = "Начисления"
        indexes = [
            models.Index(fields=["complex", "building"]),
            models.Index(fields=["due_date"]),
        ]

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

    building = models.ForeignKey(
        ComplexBuilding,
        on_delete=models.PROTECT,
        related_name="payment_participations",
        verbose_name="Дом",
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
            models.UniqueConstraint(fields=["payment", "building", "apartment"], name="uniq_payment_building_apartment"),
        ]
        indexes = [
            models.Index(fields=["building", "apartment"]),
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


class AccountDeletionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        DONE = "done", "Обработано"
        REJECTED = "rejected", "Отклонено"

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="deletion_requests", verbose_name="Профиль")
    reason = models.CharField("Причина", max_length=300, blank=True, default="")
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    processed_at = models.DateTimeField("Обработано", null=True, blank=True)

    class Meta:
        verbose_name = "Запрос на удаление аккаунта"
        verbose_name_plural = "Запросы на удаление аккаунта"
        indexes = [models.Index(fields=["status"]), models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        return f"{self.profile.user.username} ({self.status})"


class ExpenseCategory(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    sort_order = models.PositiveIntegerField("Порядок", default=100)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Категория расходов"
        verbose_name_plural = "Категории расходов"
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["sort_order"]),
        ]

    def __str__(self) -> str:
        return self.name


class Expense(models.Model):
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name="Категория",
    )
    amount = models.PositiveIntegerField("Сумма")
    currency = models.CharField("Валюта", max_length=16, default="сом")
    occurred_at = models.DateField("Дата")
    note = models.CharField("Комментарий", max_length=300, blank=True, default="")
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        indexes = [
            models.Index(fields=["occurred_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["currency"]),
        ]

    def __str__(self) -> str:
        return f"{self.category}: {self.amount} {self.currency} ({self.occurred_at})"


class FundOpeningBalance(models.Model):
    month = models.DateField("Месяц", help_text="Первый день месяца (например 2026-01-01)", unique=True)
    amount = models.IntegerField("Остаток на начало месяца")
    currency = models.CharField("Валюта", max_length=16, default="сом")
    created_at = models.DateTimeField("Создано", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Остаток фонда (месяц)"
        verbose_name_plural = "Остатки фонда (месяцы)"
        indexes = [
            models.Index(fields=["month"]),
            models.Index(fields=["currency"]),
        ]

    def __str__(self) -> str:
        return f"{self.month}: {self.amount} {self.currency}"
