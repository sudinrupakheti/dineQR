from django.urls import path
from . import views

urlpatterns = [
    path("", views.menu_view, name="menu"),
    path("cart/", views.cart_detail, name="cart_detail"),
    path("place-order/", views.place_order, name="place_order"),
    path("order-success/<int:order_id>/", views.order_success, name="order_success"),
    path(
        "api/order-status/<int:order_id>/",
        views.get_order_status,
        name="get_order_status",
    ),
    path("kitchen/", views.kitchen_dashboard, name="kitchen_dashboard"),
    path(
        "api/update-order-status/<int:order_id>/",
        views.update_order_status,
        name="update_order_status",
    ),
    path("order/review/<int:order_id>/", views.order_review_page, name="order_review"),
    path("management/", views.management_dashboard, name="management_dashboard"),
    path(
        "management/table-paid/<int:table_num>/",
        views.mark_table_paid,
        name="mark_table_paid",
    ),
    path(
        "management/toggle-item/<int:item_id>/",
        views.toggle_item_availability,
        name="toggle_item_availability",
    ),
    path("bill/<int:table_num>/", views.table_bill, name="table_bill"),
    path(
        "api/cancel-item/<int:item_id>/",
        views.cancel_order_item,
        name="cancel_order_item",
    ),
    path("api/menu-status/", views.menu_status_api, name="menu_status_api"),
    path("api/call-waiter/", views.call_waiter_api, name="call_waiter_api"),
    path(
        "api/active-waiter-calls/",
        views.get_active_waiter_calls,
        name="get_active_waiter_calls",
    ),
    path(
        "api/resolve-waiter-call/<int:call_id>/",
        views.resolve_waiter_call,
        name="resolve_waiter_call",
    ),
    path(
        "management/toggle-featured/<int:item_id>/",
        views.toggle_item_featured,
        name="toggle_item_featured",
    ),
    path(
        "payment/confirm/<int:table_num>/",
        views.confirm_payment_request,
        name="confirm_payment",
    ),
    path(
        "api/generate-split-qr/",
        views.generate_split_qr_api,
        name="generate_split_qr_api",
    ),
    path(
        "management/table/<int:table_num>/qr/",
        views.serve_table_qr,
        name="serve_table_qr",
    ),
    path(
        "management/broadcast/update/",
        views.update_kitchen_broadcast,
        name="update_kitchen_broadcast",
    ),
]
