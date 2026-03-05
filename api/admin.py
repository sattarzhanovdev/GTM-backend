from django.contrib import admin
from django.utils.html import format_html

from .models import ApartmentMember, DevicePulse, Notification, PaymentCharge, PaymentParticipation, Profile, PushDevice, Receipt
from .push import send_push_for_notification


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "apartment", "entrance", "phone_number", "is_payed", "is_accept", "is_blocked", "updated_at")
    list_filter = ("is_payed", "is_accept", "is_blocked", "entrance")
    search_fields = ("user__username", "full_name", "phone_number")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApartmentMember)
class ApartmentMemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "apartment", "phone_number", "code", "is_primary", "created_at")
    list_filter = ("apartment", "is_primary")
    search_fields = ("full_name", "phone_number", "code")
    readonly_fields = ("created_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "apartment", "is_read", "push_sent_at", "created_at")
    list_filter = ("apartment", "is_read")
    search_fields = ("title", "body")
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
    list_display = ("apartment", "entrance", "platform", "is_active", "token", "updated_at")
    list_filter = ("platform", "is_active", "apartment")
    search_fields = ("token",)
    readonly_fields = ("created_at", "updated_at")


class ReceiptInline(admin.TabularInline):
    model = Receipt
    extra = 0
    readonly_fields = ("uploaded_at",)


class PaymentParticipationInline(admin.TabularInline):
    model = PaymentParticipation
    extra = 0
    fields = ("apartment", "entrance", "status", "status_updated_at", "created_at")
    readonly_fields = ("created_at",)


@admin.register(PaymentCharge)
class PaymentChargeAdmin(admin.ModelAdmin):
    list_display = (
        "service_name",
        "amount",
        "currency",
        "due_date",
        "payment_url",
        "created_at",
    )
    list_filter = ("due_date",)
    search_fields = ("service_name", "payment_url")
    readonly_fields = ("created_at",)
    inlines = (PaymentParticipationInline,)


@admin.register(PaymentParticipation)
class PaymentParticipationAdmin(admin.ModelAdmin):
    list_display = ("payment", "apartment", "entrance", "status", "status_updated_at", "created_at")
    list_filter = ("status", "apartment", "entrance")
    search_fields = ("payment__service_name", "apartment")
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
