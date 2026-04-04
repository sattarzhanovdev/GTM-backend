from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AccountDeletionRequest,
    ApartmentMember,
    BuildingEntranceRange,
    ComplexBuilding,
    DevicePulse,
    Expense,
    ExpenseCategory,
    FundOpeningBalance,
    Notification,
    PaymentCharge,
    PaymentParticipation,
    Profile,
    PushDevice,
    ResidentialComplex,
    Receipt,
)
from .push import send_push_for_notification


class BuildingInline(admin.TabularInline):
    model = ComplexBuilding
    extra = 0


@admin.register(ResidentialComplex)
class ResidentialComplexAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "created_at")
    search_fields = ("title", "slug")
    readonly_fields = ("created_at",)
    inlines = (BuildingInline,)

    def save_model(self, request, obj: ResidentialComplex, form, change):
        super().save_model(request, obj, form, change)
        # Чтобы логин работал сразу после создания ЖК, добавляем дом "1" по умолчанию.
        if not obj.buildings.exists():
            ComplexBuilding.objects.get_or_create(complex=obj, building_id="1", defaults={"title": ""})


class EntranceRangeInline(admin.TabularInline):
    model = BuildingEntranceRange
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(ComplexBuilding)
class ComplexBuildingAdmin(admin.ModelAdmin):
    list_display = ("complex", "building_id", "title", "created_at")
    list_filter = ("complex",)
    search_fields = ("building_id", "title", "complex__title", "complex__slug")
    readonly_fields = ("created_at",)
    inlines = (EntranceRangeInline,)
    actions = ("seed_apartment_users",)

    @admin.action(description="Создать пользователей по диапазонам квартир")
    def seed_apartment_users(self, request, queryset):
        created_users = 0
        created_profiles = 0
        reset_passwords = 0
        created_members = 0

        with transaction.atomic():
            for b in queryset.select_related("complex").all():
                ranges = list(b.entrance_ranges.all())
                for r in ranges:
                    for apt in range(int(r.apartment_from), int(r.apartment_to) + 1):
                        username = f"{b.complex.slug}{b.building_id}{int(r.entrance)}{int(apt)}"
                        user, u_created = User.objects.get_or_create(username=username)
                        if u_created:
                            user.set_password(str(apt))
                            user.save(update_fields=["password"])
                            created_users += 1
                        else:
                            # Если пароль пустой/не задан, поставим дефолтный.
                            if not user.has_usable_password():
                                user.set_password(str(apt))
                                user.save(update_fields=["password"])
                                reset_passwords += 1

                        profile, p_created = Profile.objects.get_or_create(
                            user=user,
                            defaults={
                                "complex": b.complex,
                                "building": b,
                                "apartment": int(apt),
                                "entrance": int(r.entrance),
                                "created_at": timezone.now(),
                            },
                        )
                        if p_created:
                            created_profiles += 1
                        else:
                            changed = []
                            if profile.complex_id != b.complex_id:
                                profile.complex = b.complex
                                changed.append("complex")
                            if profile.building_id != b.id:
                                profile.building = b
                                changed.append("building")
                            if profile.apartment != int(apt):
                                profile.apartment = int(apt)
                                changed.append("apartment")
                            if profile.entrance != int(r.entrance):
                                profile.entrance = int(r.entrance)
                                changed.append("entrance")
                            if changed:
                                profile.save(update_fields=[*changed, "updated_at"])

                        _, m_created = ApartmentMember.objects.get_or_create(
                            building=b,
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

        self.message_user(
            request,
            f"Готово. users+{created_users}, profiles+{created_profiles}, members+{created_members}, passwords_set+{reset_passwords}.",
        )


@admin.register(BuildingEntranceRange)
class BuildingEntranceRangeAdmin(admin.ModelAdmin):
    list_display = ("building", "entrance", "apartment_from", "apartment_to", "created_at")
    list_filter = ("building__complex", "building", "entrance")
    search_fields = ("building__building_id", "building__complex__slug", "building__complex__title")
    readonly_fields = ("created_at",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "complex",
        "building",
        "apartment",
        "entrance",
        "phone_number",
        "has_parking_access",
        "password_changed_at",
        "is_payed",
        "is_accept",
        "is_blocked",
        "updated_at",
    )
    list_filter = ("complex", "building", "has_parking_access", "is_payed", "is_accept", "is_blocked", "entrance")
    search_fields = ("user__username", "full_name", "phone_number", "complex__title", "complex__slug", "building__building_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApartmentMember)
class ApartmentMemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "building", "apartment", "phone_number", "code", "is_primary", "created_at")
    list_filter = ("building__complex", "building", "apartment", "is_primary")
    search_fields = ("full_name", "phone_number", "code", "building__building_id", "building__complex__slug")
    readonly_fields = ("created_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "complex", "building", "apartment", "is_read", "push_sent_at", "created_at")
    list_filter = ("complex", "building", "apartment", "is_read")
    search_fields = ("title", "body", "complex__title", "complex__slug", "building__building_id")
    readonly_fields = ("created_at", "push_sent_at")
    actions = ("send_push_selected",)

    def save_model(self, request, obj: Notification, form, change):
        super().save_model(request, obj, form, change)
        # Отправляем push только при создании (или если ещё не отправляли).
        if obj.push_sent_at is None:
            res = send_push_for_notification(obj)
            if not res.get("ok"):
                self.message_user(
                    request,
                    f"Push отправлен с ошибками. sent={res.get('sent')}, пример: {(res.get('errors') or [''])[0]}",
                    level="warning",
                )

    @admin.action(description="Отправить push выбранным")
    def send_push_selected(self, request, queryset):
        sent_total = 0
        error_total = 0
        first_error = ""
        for n in queryset:
            res = send_push_for_notification(n)
            sent_total += int(res.get("sent") or 0)
            errs = res.get("errors") or []
            if errs:
                error_total += len(errs)
                if not first_error:
                    first_error = str(errs[0])
        msg = f"Отправлено push: {sent_total}"
        if error_total:
            msg += f" (ошибок: {error_total}, пример: {first_error})"
        self.message_user(request, msg)


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ("building", "apartment", "entrance", "platform", "token_type", "is_active", "token", "updated_at")
    list_filter = ("building__complex", "building", "platform", "token_type", "is_active", "apartment")
    search_fields = ("token", "building__building_id", "building__complex__slug")
    readonly_fields = ("created_at", "updated_at")


class ReceiptInline(admin.TabularInline):
    model = Receipt
    extra = 0
    readonly_fields = ("uploaded_at",)


class PaymentParticipationInline(admin.TabularInline):
    model = PaymentParticipation
    extra = 0
    fields = ("building", "apartment", "entrance", "status", "status_updated_at", "created_at")
    readonly_fields = ("created_at",)


@admin.register(PaymentCharge)
class PaymentChargeAdmin(admin.ModelAdmin):
    list_display = (
        "complex",
        "building",
        "service_name",
        "amount",
        "currency",
        "due_date",
        "payment_url",
        "created_at",
    )
    list_filter = ("complex", "building", "due_date")
    search_fields = ("service_name", "payment_url", "complex__title", "complex__slug", "building__building_id")
    readonly_fields = ("created_at",)
    inlines = (PaymentParticipationInline,)


@admin.register(PaymentParticipation)
class PaymentParticipationAdmin(admin.ModelAdmin):
    list_display = ("payment", "building", "apartment", "entrance", "status", "status_updated_at", "created_at")
    list_filter = ("building__complex", "building", "status", "apartment", "entrance")
    search_fields = ("payment__service_name", "apartment", "building__building_id", "building__complex__slug")
    readonly_fields = ("created_at", "status_updated_at")
    inlines = (ReceiptInline,)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("participation", "uploaded_at", "file_name", "file_link")
    list_filter = ("uploaded_at",)
    readonly_fields = ("uploaded_at",)

    @admin.display(description="Файл")
    def file_name(self, obj: Receipt) -> str:
        return getattr(obj.file, "name", "") or ""

    @admin.display(description="Ссылка")
    def file_link(self, obj: Receipt) -> str:
        try:
            url = obj.file.url
        except Exception:
            return ""
        return format_html('<a href="{}" target="_blank" rel="noreferrer noopener">Открыть</a>', url)


@admin.register(DevicePulse)
class DevicePulseAdmin(admin.ModelAdmin):
    list_display = ("key", "active_until", "is_active_admin", "updated_at")
    list_filter = ("key",)
    search_fields = ("key",)

    @admin.display(boolean=True, description="Активен")
    def is_active_admin(self, obj: DevicePulse) -> bool:
        return obj.is_active()


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ("profile", "status", "created_at", "processed_at")
    list_filter = ("status", "created_at")
    search_fields = ("profile__user__username", "profile__phone_number", "reason")
    readonly_fields = ("created_at",)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at",)
    ordering = ("sort_order", "name")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "category", "amount", "currency", "note", "created_at")
    list_filter = ("currency", "category", "occurred_at")
    search_fields = ("note", "category__name")
    readonly_fields = ("created_at",)
    date_hierarchy = "occurred_at"


@admin.register(FundOpeningBalance)
class FundOpeningBalanceAdmin(admin.ModelAdmin):
    list_display = ("month", "amount", "currency", "updated_at")
    list_filter = ("currency",)
    search_fields = ("month",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "month"
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
