from django.urls import path
from . import views

urlpatterns = [
    path(
        "",
        views.menu_view,
        name="menu",
    ),
    path(
        "cart/",
        views.cart_detail,
        name="cart_detail",
    ),
    path(
        "place-order/",
        views.place_order,
        name="place_order",
    ),
    path(
        "order-success/<int:order_id>/",
        views.order_success,
        name="order_success",
    ),
    path(
        "api/order-status/<int:order_id>/",
        views.get_order_status,
        name="get_order_status",
    ),
]
