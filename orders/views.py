import json
from django.http import JsonResponse
from django.shortcuts import render, redirect
from .models import Order, OrderItem, MenuItem, Category, Review
from decimal import Decimal
from .ai_utils import analyze_note_sentiment
import pandas as pd
from django.db.models import Sum
from datetime import date
from django.utils import timezone
from django.contrib.auth.decorators import user_passes_test

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

@user_passes_test(is_staff)
def kitchen_dashboard(request):
    # Get all orders that aren't finished yet
    active_orders = Order.objects.filter(status__in=["received", "preparing"]).order_by(
        "created_at"
    )
    return render(request, "orders/kitchen.html", {"orders": active_orders})

@user_passes_test(is_owner)
def owner_dashboard(request):
    filter_type = request.GET.get("filter", "all")  # Default to all-time

    # Base queries
    completed_orders = Order.objects.filter(status="completed")
    all_reviews = Review.objects.all()

    # Apply 'Today' filter if requested
    if filter_type == "today":
        today = timezone.localdate()
        completed_orders = completed_orders.filter(created_at__date=today)
        all_reviews = all_reviews.filter(created_at__date=today)

    total_revenue = (
        completed_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0
    )
    positive_count = all_reviews.filter(sentiment="positive").count()
    negative_count = all_reviews.filter(sentiment="negative").count()

    best_seller = "No sales"
    items_sold = 0

    if completed_orders.exists():
        all_items = OrderItem.objects.filter(order__in=completed_orders)
        if all_items.exists():
            data = list(all_items.values("menu_item__name", "quantity"))
            df = pd.DataFrame(data)
            if not df.empty:
                sales_summary = (
                    df.groupby("menu_item__name")["quantity"].sum().reset_index()
                )
                top_item_row = sales_summary.sort_values(
                    by="quantity", ascending=False
                ).iloc[0]
                best_seller = top_item_row["menu_item__name"]
                items_sold = top_item_row["quantity"]

    context = {
        "filter_type": filter_type,
        "total_revenue": total_revenue,
        "order_count": completed_orders.count(),
        "best_seller": best_seller,
        "items_sold": items_sold,
        "positive_count": positive_count,
        "negative_count": negative_count,
    }


def call_waiter_api(request):
    if request.method == "POST":
        import json

        try:
            data = json.loads(request.body)
            table_num = data.get("table_number")
            reason = data.get("reason", "help")

            if not table_num:
                return JsonResponse(
                    {"status": "error", "message": "Table number missing."}, status=400
                )

            # Anti-Spam protection: Check if this table already has an active request
            existing_call = WaiterCall.objects.filter(
                table_number=table_num, is_resolved=False
            ).first()
            if existing_call:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": f"Our staff is already on the way for: {existing_call.get_reason_display()}!",
                    },
                    status=400,
                )

            # Create the call
            WaiterCall.objects.create(table_number=table_num, reason=reason)
            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@user_passes_test(is_staff)
def get_active_waiter_calls(request):
    """API for the dashboard to get all unresolved waiter calls."""
    calls = WaiterCall.objects.filter(is_resolved=False).order_by("-created_at")
    data = [
        {
            "id": c.id,
            "table": c.table_number,
            "reason": c.get_reason_display(),
            "time": c.created_at.strftime("%H:%M"),
        }
        for c in calls
    ]
    return JsonResponse({"calls": data})


@user_passes_test(is_staff)
def resolve_waiter_call(request, call_id):  
    """Mark a service request as resolved."""
    if request.method == "POST":
        call = WaiterCall.objects.get(id=call_id)
        call.is_resolved = True
        call.save()
        return JsonResponse({"status": "success"})