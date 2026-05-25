import json
import difflib
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.db.models import Sum, Q, Avg, Count
from django.contrib.auth.decorators import user_passes_test
from django.conf import settings
import qrcode
import io
import base64


from .models import (
    Order,
    OrderItem,
    MenuItem,
    Category,
    Review,
    WaiterCall,
    TableSession,
)
from .ai_utils import analyze_note_sentiment


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
        elif "featured" in query or "special" in query:
            items = items.filter(is_featured=True)
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
    running_total = Decimal("0.00")
    any_ready = False
    show_thanks = False

    if table_num:
        previous_orders = (
            Order.objects.filter(table_number=table_num)
            .exclude(status__in=["completed", "cancelled"])
            .order_by("-created_at")
        )

        recently_settled = Order.objects.filter(
            table_number=table_num,
            status="completed",
            paid_at__gte=timezone.now() - timedelta(minutes=10),
        ).exists()

        if not previous_orders.exists() and recently_settled:
            show_thanks = True

        # 3. CALCULATE TOTAL FIRST
        for order in previous_orders:
            running_total += order.total_price
            if order.status == "ready":
                any_ready = True

    qr_code = None
    if previous_orders.exists():
        first_order = previous_orders.first()
        local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")

        qr_code = generate_bill_qr(
            {
                "amount": f"{running_total:,.2f}",
                "order_id": first_order.id,
                "table_number": table_num,
                "timestamp": local_time,
            }
        )

    return render(
        request,
        "orders/cart_detail.html",
        {
            "previous_orders": previous_orders,
            "running_total": running_total,
            "any_ready": any_ready,
            "show_thanks": show_thanks,
            "qr_code": qr_code,
        },
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
            return JsonResponse(
                {"status": "error", "message": "Invalid request method"}, status=405
            )


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
        try:
            # TRY to find the order
            order = Order.objects.get(id=order_id)
            new_status = request.POST.get("status")

            valid_statuses = ["preparing", "ready", "completed"]

            if new_status in valid_statuses:
                order.status = new_status
                order.save()
        except Order.DoesNotExist:
            # If the user canceled the order and it was deleted from DB,
            # just silently catch the error and refresh the kitchen screen!
            pass

        return redirect("kitchen_dashboard")
    return JsonResponse({"status": "error"}, status=400)


def cancel_order_item(request, item_id):
    """Allows customers to delete an item if the kitchen hasn't started cooking it yet."""
    if request.method == "POST":
        try:
            # Only allow deleting if the order is still "received"
            item = OrderItem.objects.get(id=item_id, order__status="received")
            order = item.order

            # Deduct price
            item_price_total = Decimal(str(item.menu_item.price)) * item.quantity
            item.delete()

            # Update the parent order
            order.total_price -= item_price_total
            if order.total_price <= 0 or order.items.count() == 0:
                order.delete()  # If order is empty, delete the whole order
            else:
                order.save()

            return JsonResponse({"status": "success"})
        except OrderItem.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Invalid request method"}, status=405
            )


@user_passes_test(is_staff)
def management_dashboard(request):
    current_tab = request.GET.get("tab", "tables")

    # --- 1. GLOBAL STATS (For all tabs) ---
    all_active_orders = Order.objects.exclude(status="completed")
    total_live_revenue = (
        all_active_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0
    )
    busy_tables_count = all_active_orders.values("table_number").distinct().count()

    # --- 2. LOGIC FOR TABLES TAB ---
    table_data = []
    if current_tab == "tables":
        for i in range(1, 11):
            active_orders = Order.objects.filter(table_number=i).exclude(
                status="completed"
            )
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

    # --- 3. LOGIC FOR INSIGHTS TAB ---
    insights_data = {}
    if current_tab == "insights":
        top_items = (
            OrderItem.objects.filter(order__is_paid=True)
            .values("menu_item__name")
            .annotate(total_sold=Sum("quantity"))
            .order_by("-total_sold")[:5]
        )
        avg_rating = Review.objects.aggregate(Avg("rating"))["rating__avg"] or 0
        hourly_data = (
            Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=7))
            .extra(select={"hour": "strftime('%%H', created_at)"})
            .values("hour")
            .annotate(count=Count("id"))
            .order_by("hour")
        )

        insights_data = {
            "top_items": list(top_items),
            "avg_rating": round(avg_rating, 1),
            "hourly_data": list(hourly_data),
        }

    categories = Category.objects.prefetch_related("items").all()

    context = {
        "tables": table_data,
        "categories": categories,
        "current_tab": current_tab,
        "total_live_revenue": total_live_revenue,
        "busy_tables_count": busy_tables_count,
        "insights": insights_data,  # Pass insights data here
    }
    return render(request, "orders/management_dashboard.html", context)


def order_review_page(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        # If the order is missing, go back to menu
        return redirect("menu")

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
        # Redirect back to cart with the table number in the URL
        return redirect(f"{reverse('cart_detail')}?table={order.table_number}")

    # For a normal click (GET request), just show the form
    return render(request, "orders/review_form.html", {"order": order})


@user_passes_test(is_staff)
def kitchen_dashboard(request):
    # Get active orders
    active_orders = Order.objects.filter(status__in=["received", "preparing"]).order_by(
        "created_at"
    )

    # This creates the summary: e.g. "Chicken Burger: 5"
    item_summary = (
        OrderItem.objects.filter(order__status__in=["received", "preparing"])
        .values("menu_item__name")
        .annotate(total_qty=Sum("quantity"))
    )

    return render(
        request,
        "orders/kitchen.html",
        {"orders": active_orders, "item_summary": item_summary},
    )


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
    active_orders = Order.objects.filter(table_number=table_num).exclude(
        status="completed"
    )

    items = OrderItem.objects.filter(order__in=active_orders)
    total = active_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0
    first_order = active_orders.first()

    qr_code = None
    if first_order:
        local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")
        qr_code = generate_bill_qr(
            {
                "amount": f"{total:,.2f}",
                "order_id": first_order.id,
                "table_number": table_num,
                "timestamp": local_time,
            }
        )

    context = {
        "table_num": table_num,
        "items": items,
        "total": total,
        "date": timezone.localtime(timezone.now()),
        "bill_id": first_order.id if first_order else "000",
        "qr_code": qr_code,
    }
    return render(request, "orders/bill_print.html", context)


def menu_status_api(request):
    """Returns a list of IDs for items that are currently unavailable."""
    sold_out_ids = list(
        MenuItem.objects.filter(is_available=False).values_list("id", flat=True)
    )
    return JsonResponse({"sold_out": sold_out_ids})


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
            "time": timezone.localtime(c.created_at).strftime("%H:%M"),
        }
        for c in calls
    ]
    return JsonResponse({"calls": data})


@user_passes_test(is_staff)
def resolve_waiter_call(request, call_id):
    if request.method == "POST":
        try:
            call = WaiterCall.objects.get(id=call_id)
            call.is_resolved = True
            call.save()
            return JsonResponse({"status": "success"})
        except WaiterCall.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Invalid request method"}, status=405
            )

    return JsonResponse(
        {"status": "error", "message": "Invalid request method"}, status=405
    )


def verify_table_session(request):
    """
    Checks if the user has a valid token for the table they are trying to access.
    If they are new, it gives them a token.
    """
    table_num = request.GET.get("table")
    client_token = request.headers.get("X-Session-Token")

    if not table_num:
        return JsonResponse(
            {"status": "error", "message": "No table specified"}, status=400
        )

    # 1. If client sent a token, verify it matches the table
    if client_token:
        session = TableSession.objects.filter(
            table_number=table_num, session_token=client_token, is_active=True
        ).first()
        if session:
            return JsonResponse(
                {"status": "success", "token": str(session.session_token)}
            )

    new_session = TableSession.objects.create(table_number=table_num)
    return JsonResponse({"status": "success", "token": str(new_session.session_token)})


@user_passes_test(is_staff)
def toggle_item_featured(request, item_id):
    if request.method == "POST":
        item = MenuItem.objects.get(id=item_id)
        item.is_featured = not item.is_featured
        item.save()
    # Redirect back to the Menu tab on the dashboard
    return redirect(f"{request.META.get('HTTP_REFERER', '/management/')}")


def generate_bill_qr(data):
    payload = (
        f"Merchant: {settings.MERCHANT_NAME}\n"
        f"Account: {settings.MERCHANT_ACCOUNT}\n"
        f"Amount: Rs.{data['amount']}\n"
        f"Order_ID: {data['order_id']}\n"
        f"Table: {data['table_number']}\n"
        f"Time: {data['timestamp']}"
    )
    qr = qrcode.make(payload)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def confirm_payment_request(request, table_num):
    """Handles equal split, item-based split, and full payment."""
    active_orders = Order.objects.filter(table_number=table_num).exclude(
        status="completed"
    )

    if not active_orders.exists():
        return JsonResponse(
            {"status": "error", "message": "No active orders"}, status=400
        )

    try:
        if request.method == "POST":
            data = json.loads(request.body)
        else:
            data = request.GET.dict()

        items_to_pay = data.get("items", [])
        manual_amount = Decimal(str(data.get("amount", 0)))
    except:
        manual_amount = Decimal("0")
        items_to_pay = []

    # MODE 1: ITEM-BASED PAY
    if items_to_pay:
        for entry in items_to_pay:
            try:
                order_item = OrderItem.objects.get(id=entry["id"])
                qty = int(entry.get("qty", 1))
                order_item.paid_quantity = (order_item.paid_quantity or 0) + qty
                order_item.save()

                order = order_item.order
                order.paid_amount = (order.paid_amount or Decimal("0")) + (
                    Decimal(str(order_item.menu_item.price)) * qty
                )
                order.save()
            except OrderItem.DoesNotExist:
                pass

    # MODE 2: EQUAL/MANUAL AMOUNT
    elif manual_amount > 0:
        remaining = manual_amount
        for order in active_orders:
            if remaining <= Decimal("0"):
                break
            to_pay = min(remaining, order.remaining_balance)
            order.paid_amount = (order.paid_amount or Decimal("0")) + to_pay
            remaining -= to_pay
            order.save()

    # FINAL CHECK: IS TABLE FULLY PAID?
    all_done = True
    for order in active_orders:
        if order.remaining_balance > Decimal("0.01"):
            all_done = False
        else:
            order.status = "completed"
            order.is_paid = True
            order.paid_at = timezone.now()
            order.save()

    WaiterCall.objects.create(table_number=table_num, reason="paid", is_resolved=False)

    return JsonResponse({"status": "success", "table_cleared": all_done})
