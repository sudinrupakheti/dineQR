from django.urls import path  # type: ignore
from . import views
from django.conf import settings    # type: ignore
from django.conf.urls.static import static # type: ignore


urlpatterns = [
    path("", views.menu_view, name="menu"),
    path("welcome/", views.welcome_view, name="welcome"),
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
    path("api/call-waiter/", views.call_waiter_api, name="call_waiter_api"),  # type: ignore
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
    path("management/menu/add/", views.save_menu_item, name="add_menu_item"),
    path("management/menu/edit/<int:item_id>/", views.save_menu_item, name="edit_menu_item"),
    path("management/category/add/", views.save_category, name="add_category"),
    path("management/category/edit/<int:category_id>/", views.save_category, name="edit_category"),
    path("management/delete/<str:model_type>/<int:object_id>/", views.unified_delete, name="unified_delete"),
    path("management/api/staff-order/", views.staff_place_order, name="staff_place_order"),  # type: ignore
    path("management/api/table/<int:table_num>/", views.get_table_orders, name="get_table_orders"),
    path("management/api/modify-item/<int:item_id>/", views.modify_order_item, name="modify_order_item"),  # type: ignore
    path("management/api/drawer/", views.get_drawer_items, name="get_drawer_items"),
    path("management/order/<int:order_id>/settle/", views.mark_order_paid, name="mark_order_paid"),
    path("management/order/<int:order_id>/bill/", views.single_order_bill, name="single_order_bill"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path(
        "api/verify-session/",
        views.verify_table_session,
        name="verify_table_session",
    ),
    path("management/reviews/clear/", views.clear_old_reviews, name="clear_old_reviews"),
    path("api/kitchen/orders/", views.kitchen_orders_api, name="kitchen_orders_api"),
    path("api/kitchen/item-status/<int:item_id>/", views.update_item_status, name="update_item_status"),
    path("api/kitchen/recent-completed/", views.get_recent_completed_orders, name="get_recent_completed_orders"),
    path("api/kitchen/recall/<int:order_id>/", views.recall_order_api, name="recall_order_api"),
    # New Customer Auth & Table Session Routes
    path("api/customer/signup/", views.customer_signup_api, name="customer_signup_api"),
    path("api/customer/login/", views.customer_login_api, name="customer_login_api"),
    path("api/customer/convert-guest/", views.convert_guest_account_api, name="convert_guest_account_api"),
    path("api/customer/history/", views.user_order_history_api, name="user_order_history_api"),
    path("customer/portal/", views.customer_portal, name="customer_portal"),
    path("api/table-cart/update/", views.update_table_cart, name="update_table_cart"),
    path("api/table-cart/get/", views.get_table_cart, name="get_table_cart"),
    path(
    "management/table/<int:table_num>/reset-session/",
    views.reset_table_session,
    name="reset_table_session",
    ),
    path("api/table-split/update/", views.update_table_split, name="update_table_split"),
    path("api/table-split/get/", views.get_table_split, name="get_table_split"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
