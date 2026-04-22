import json
from django.http import JsonResponse
from django.shortcuts import render, redirect
from .models import Order, OrderItem, MenuItem, Category
from decimal import Decimal


def menu_view(request):
    items = MenuItem.objects.filter(is_available=True)
    categories = Category.objects.all()

    context = {
        "items": items,
        "categories": categories,
    }
    return render(request, "orders/menu.html", context)


def cart_detail(request):
    return render(request, "orders/cart_detail.html")


def place_order(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            cart = data.get("cart")
            table_number = data.get("table_number")

            if not cart or not table_number:
                return JsonResponse(
                    {"status": "error", "message": "Invalid data"}, status=400
                )

            new_order = Order.objects.create(
                table_number=table_number,
                status="received",
                total_price=Decimal("0.00"),
            )

            running_total = Decimal("0.00")

            for item_id, item_data in cart.items():
                menu_item = MenuItem.objects.get(id=item_id)
                qty = int(item_data["quantity"])

                OrderItem.objects.create(
                    order=new_order,
                    menu_item=menu_item,
                    quantity=qty,
                    notes=item_data.get("notes", ""),
                )

                running_total += Decimal(str(menu_item.price)) * qty

            new_order.total_price = running_total
            new_order.save()

            return JsonResponse({"status": "success", "order_id": new_order.id})

        except Exception as e:
            print(f"Order Error: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


def order_success(request, order_id):
    order = Order.objects.get(id=order_id)
    return render(request, "orders/order_success.html", {"order": order})
