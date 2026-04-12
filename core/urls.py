from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path("login/", views.admin_login, name="admin_login"),
    path("logout/", views.admin_logout, name="admin_logout"),
    # Dashboard
    path("", views.admin_dashboard, name="admin_dashboard"),
    # Orders
    path("orders/", views.orders_view, name="orders_view"),
    path(
        "orders/<int:order_id>/status/",
        views.update_order_status,
        name="update_order_status",
    ),
    # Menu
    path("menu/", views.menu_management, name="menu_management"),
    path("menu/<int:item_id>/toggle/", views.menu_item_toggle, name="menu_item_toggle"),
    # Analytics
    path("analytics/", views.analytics_view, name="analytics_view"),
]
