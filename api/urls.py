from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("login/", views.login, name="login"),
    path("me/", views.me, name="me"),

    # Profile
    path("profile/notifications/", views.notifications, name="notifications"),
    path("profile/notifications/<int:notification_id>/read/", views.notifications_mark_read, name="notifications_read"),
    path("profile/notifications/<int:notification_id>/delete/", views.notifications_delete, name="notifications_delete"),
    path("profile/users/", views.apartment_users, name="apartment_users"),
    path("profile/users/<int:member_id>/delete/", views.apartment_users_delete, name="apartment_users_delete"),

    # Payments
    path("payments/", views.payments, name="payments"),
    path("payments/history/", views.payments_history, name="payments_history"),
    path("payments/<int:payment_id>/receipt/", views.payments_attach_receipt, name="payments_attach_receipt"),

    # Devices
    path("devices/status/", views.devices_status, name="devices_status"),
    path("devices/gate/open/", views.devices_gate_open, name="devices_gate_open"),
    path("devices/kalitka/<int:n>/open/", views.devices_kalitka_open, name="devices_kalitka_open"),
    path("devices/entrance/<int:n>/open/", views.devices_entrance_open, name="devices_entrance_open"),
    path("devices/entrance/<int:n>/lift/open/", views.devices_lift_open, name="devices_lift_open"),
]
