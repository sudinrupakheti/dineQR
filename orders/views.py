import json
from django.http import JsonResponse
from django.shortcuts import render, redirect
from .models import Order, OrderItem, MenuItem, Category, Review
from decimal import Decimal
from .ai_utils import analyze_note_sentiment
import pandas as pd
from django.db.models import Sum, Q
from datetime import date
from django.utils import timezone
from django.contrib.auth.decorators import user_passes_test
import difflib
from django.urls import reverse


def is_owner(user):
    return user.groups.filter(name="Owner").exists() or user.is_superuser


def is_staff(user):
    return user.groups.filter(name="Staff").exists() or user.is_superuser


def menu_view(request):
    query = request.GET.get("search", "").lower().strip()
    items = MenuItem.objects.all()
    categories = Category.objects.all()

    if query:
        matched_categories = categories.filter(name__icontains=query)

        # Intent detection
        is_veg = "veg" in query and "non" not in query
        is_spicy = any(w in query for w in ["spicy", "hot", "chili", "spice"])
        is_mild = any(w in query for w in ["mild", "not spicy", "not hot"])

        if is_spicy:
            # Pure intent query — skip text search entirely
            items = items.filter(spice_level__in=["medium", "hot"])
        elif is_mild:
            items = items.filter(spice_level="mild")
        else:
            # Strip punctuation for fuzzy matching
            import re

            clean_names = [
                re.sub(r"[^a-z0-9 ]", "", item.name.lower()) for item in items
            ]
            close_matches = difflib.get_close_matches(
                query, clean_names, n=5, cutoff=0.5
            )

            lookup = (
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(category__in=matched_categories)
            )

            # Add ALL close matches, not just [0]
            for match in close_matches:
                lookup |= Q(name__icontains=match.replace(" ", ""))

            items = items.filter(lookup)

        if is_veg:
            items = items.filter(veg=True)

    category_ids = items.values_list("category_id", flat=True)
    categories = categories.filter(id__in=category_ids)

    context = {"items": items, "categories": categories, "query": query}
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


def order_review_page(request, order_id):
    order = Order.objects.get(id=order_id)
    if request.method == "POST":
        for item in order.items.all():
            rating = request.POST.get(f"rating_{item.id}")
            comment = request.POST.get(f"comment_{item.id}", "")
            ai_result = analyze_note_sentiment(comment)

            Review.objects.create(
                order=order,
                menu_item=item.menu_item,
                rating=rating,
                comment=comment,
                sentiment=ai_result,
            )
        return redirect(f"{reverse('menu')}?table={order.table_number}")

    return render(request, "orders/review_form.html", {"order": order})


@user_passes_test(is_staff)
def kitchen_dashboard(request):
    # Get all orders that aren't finished yet
    active_orders = Order.objects.filter(status__in=["received", "preparing"]).order_by(
        "created_at"
    )
    return render(request, "orders/kitchen.html", {"orders": active_orders})


@user_passes_test(is_staff)
def management_dashboard(request):
    current_tab = request.GET.get("tab", "tables")

    table_data = []
    for i in range(1, 11):
        active_orders = Order.objects.filter(table_number=i).exclude(status="completed")
        if active_orders.exists():
            total_bill = (
                active_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0
            )
            statuses = [o.status for o in active_orders]
            display_status = (
                "ready"
                if "ready" in statuses
                else ("preparing" if "preparing" in statuses else "received")
            )
            table_data.append(
                {
                    "number": i,
                    "status": display_status,
                    "total": total_bill,
                    "has_orders": True,
                }
            )
        else:
            table_data.append(
                {"number": i, "status": "empty", "total": 0, "has_orders": False}
            )

    categories = Category.objects.prefetch_related("items").all()

    context = {
        "tables": table_data,
        "categories": categories,
        "current_tab": current_tab,
    }
    return render(request, "orders/management_dashboard.html", context)


@user_passes_test(is_staff)
def mark_table_paid(request, table_num):
    if request.method == "POST":
        # Find all orders for this table that aren't completed
        active_orders = Order.objects.filter(table_number=table_num).exclude(
            status="completed"
        )

        # Mark all of them as paid and completed
        active_orders.update(
            is_paid=True, paid_at=timezone.localtime(), status="completed"
        )
    return redirect("management_dashboard")


@user_passes_test(is_staff)
def toggle_item_availability(request, item_id):
    if request.method == "POST":
        item = MenuItem.objects.get(id=item_id)
        item.is_available = not item.is_available
        item.save()
    return redirect(f"{request.META.get('HTTP_REFERER', '/management/')}?tab=menu")


def table_bill(request, table_num):
    # Get all active (unpaid) orders for this table
    active_orders = Order.objects.filter(table_number=table_num).exclude(
        status="completed"
    )

    if not active_orders.exists():
        # If no active orders, maybe they just paid? Show the last completed orders from the last 15 mins
        active_orders = Order.objects.filter(
            table_number=table_num,
            status="completed",
            paid_at__gte=timezone.localtime() - timezone.timedelta(minutes=15),
        )

    # Collect all items across these orders
    items = OrderItem.objects.filter(order__in=active_orders)
    total = active_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0

    context = {
        "table_num": table_num,
        "items": items,
        "total": total,
        "date": timezone.localtime(),
        "bill_id": active_orders.first().id if active_orders.exists() else "000",
    }
    return render(request, "orders/bill_print.html", context)
