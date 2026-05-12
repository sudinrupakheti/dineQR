import json
from django.http import JsonResponse
from django.shortcuts import render, redirect
from .models import Order, OrderItem, MenuItem, Category, Review
from decimal import Decimal
from .ai_utils import analyze_note_sentiment


def menu_view(request):
    items = MenuItem.objects.filter(is_available=True)
    categories = Category.objects.all()

    context = {
        "items": items,
        "categories": categories,
    }
    return render(request, "orders/menu.html", context)


def cart_detail(request):
    table_num = request.GET.get("table")
    previous_orders = []

    if table_num:
        # Get orders for this table that aren't "completed" yet
        previous_orders = (
            Order.objects.filter(table_number=table_num)
            .exclude(status="completed")
            .order_by("-created_at")
        )

    return render(
        request, "orders/cart_detail.html", {"previous_orders": previous_orders}
    )


def place_order(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            cart = data.get("cart")
            raw_table_number = data.get("table_number")

            if not cart or not raw_table_number:
                return JsonResponse(
                    {"status": "error", "message": "Invalid data"}, status=400
                )

            try:
                table_num = int(raw_table_number)
                if table_num < 1 or table_num > 10:
                    return JsonResponse(
                        {"status": "error", "message": "Table must be 1-10"}, status=400
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Invalid table format"}, status=400
                )

            new_order = Order.objects.create(
                table_number=table_num,
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


def get_order_status(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
        return JsonResponse({"status": order.status})
    except Order.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)


def update_order_status(request, order_id):
    if request.method == "POST":
        order = Order.objects.get(id=order_id)
        new_status = request.POST.get("status")

        valid_statuses = ["preparing", "ready", "completed"]

        if new_status in valid_statuses:
            order.status = new_status
            order.save()

            return redirect("kitchen_dashboard")
    return JsonResponse({"status": "error"}, status=400)


def kitchen_dashboard(request):
    # Get all orders that aren't finished yet
    active_orders = Order.objects.filter(status__in=["received", "preparing"]).order_by(
        "created_at"
    )
    return render(request, "orders/kitchen.html", {"orders": active_orders})

def order_review_page(request, order_id):
    order = Order.objects.get(id=order_id)

    if request.method == "POST":
        # Loop through the items in the order to get ratings
        for item in order.items.all():
            rating = request.POST.get(f"rating_{item.id}")
            comment = request.POST.get(f"comment_{item.id}", "")

            # RUN AI SENTIMENT ANALYSIS HERE
            ai_result = analyze_note_sentiment(comment)

            Review.objects.create(
                order=order,
                menu_item=item.menu_item,
                rating=rating,
                comment=comment,
                sentiment=ai_result,
            )

        # Mark order as fully closed and send back to menu
        order.status = "completed"
        order.save()
        return redirect("menu")

    return render(request, "orders/review_form.html", {"order": order})

