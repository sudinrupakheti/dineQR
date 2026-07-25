import json
import difflib
import re
import qrcode   # type: ignore
import io
import base64
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from itertools import combinations
from django.utils import timezone   # type: ignore
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden   # type: ignore
from django.shortcuts import render, redirect, get_object_or_404    # type: ignore
from django.urls import reverse # type: ignore
from django.core.cache import cache # type: ignore
from django.db.models import (  # type: ignore
    Sum,
    Q,
    Avg,
    Count,
    Case,
    When,
    IntegerField,
    Prefetch,
    F,
    ExpressionWrapper,
    DurationField,
)
from django.db.models.functions import ExtractWeekDay, ExtractHour  # type: ignore
from django.contrib.auth import authenticate, login, logout # type: ignore
from django.contrib.auth.models import User # type: ignore
from django.contrib.auth.decorators import login_required, user_passes_test # type: ignore
from django.views.decorators.cache import never_cache   # type: ignore
from django.views.decorators.http import require_POST   # type: ignore
from django.conf import settings    # type: ignore
from django.contrib import messages # type: ignore
from django.db import transaction   # type: ignore
from .ai_utils import analyze_note_sentiment
from .models import (
    Order,
    OrderItem,
    MenuItem,
    Category,
    Review,
    WaiterCall,
    TableSession,
    KitchenBroadcast,
    UserProfile,
    TableCart,
    TableSplitState,
)


def is_management_or_owner(user):
    if not user.is_authenticated:
        return False
    return (
        user.is_superuser
        or user.groups.filter(name__iexact="Management").exists()
        or user.groups.filter(name__iexact="Owner").exists()
    )


def is_kitchen_or_higher(user):
    if not user.is_authenticated:
        return False
    return (
        user.is_superuser
        or user.groups.filter(name__iexact="Kitchen").exists()
        or user.groups.filter(name__iexact="Management").exists()
        or user.groups.filter(name__iexact="Owner").exists()
    )


SEARCH_SYNONYMS = {
    "momo": ["mo:mo", "momos", "dumplings", "dumpling"],
    "mo:mo": ["momo", "momos", "dumplings", "dumpling"],
    "sweet": ["dessert", "desserts", "sweets", "pudding", "ice cream", "cake", "pastry"],
    "dessert": ["sweet", "sweets", "desserts", "pudding", "ice cream", "cake"],
    "drink": ["beverage", "beverages", "drinks", "soda", "juice", "coke", "cold drink", "water"],
    "beverage": ["drink", "drinks", "beverages", "soda", "juice", "cold drink"],
    "chowmein": ["chow mein", "noodles", "noodle"],
    "noodle": ["chowmein", "chow mein", "noodles"],
    "burger": ["burgers", "hamburger", "buns"],
}


def expand_search_query(raw_query):
    expanded_terms = set([raw_query])
    words = raw_query.split()
    for word in words:
        for root_term, related_terms in SEARCH_SYNONYMS.items():
            if word == root_term or word in related_terms:
                expanded_terms.add(root_term)
                expanded_terms.update(related_terms)
    return list(expanded_terms)


def menu_view(request):
    table_num = request.GET.get("table")
    if table_num:
        try:
            table_int = int(table_num)
        except ValueError:
            table_int = None
        if table_int and table_int != 0:
            session = TableSession.objects.filter(table_number=table_int, is_active=True).first()
            if session and session.session_passcode:
                token = request.GET.get("token")
                if not token or token != str(session.session_token):
                    return redirect(f"/welcome/?table={table_int}")

    query = request.GET.get("search", "").lower().strip()
    items = MenuItem.objects.filter(is_available=True)
    categories = Category.objects.all()
    recommended_items = None
    zero_results = False

    if query:
        is_veg = "veg" in query and "non" not in query
        is_spicy = any(w in query for w in ["spicy", "hot", "chili", "spice"])
        is_mild = any(w in query for w in ["mild", "not spicy", "not hot"])
        is_featured = "featured" in query or "special" in query

        words = re.findall(r"[a-z0-9:]+", query)
        intent_keywords = {"veg", "spicy", "hot", "chili", "spice", "mild", "not", "featured", "special"}
        is_pure_intent = all(word in intent_keywords for word in words) if words else False

        if not is_pure_intent:
            search_terms = set([query])
            for word in words:
                search_terms.add(word)
                if word in SEARCH_SYNONYMS:
                    search_terms.update(SEARCH_SYNONYMS[word])

            all_item_words = set()
            for name in MenuItem.objects.filter(is_available=True).values_list("name", flat=True):
                all_item_words.update(re.findall(r"[a-z0-9:]+", name.lower()))

            all_cat_words = set()
            for name in Category.objects.values_list("name", flat=True):
                all_cat_words.update(re.findall(r"[a-z0-9:]+", name.lower()))

            fuzzy_matches = []
            for word in words:
                fuzzy_matches.extend(difflib.get_close_matches(word, list(all_item_words), n=2, cutoff=0.8))
                fuzzy_matches.extend(difflib.get_close_matches(word, list(all_cat_words), n=2, cutoff=0.8))

            search_terms.update([match.lower() for match in fuzzy_matches])

            lookup = Q()
            for term in search_terms:
                lookup |= Q(name__icontains=term)
                lookup |= Q(description__icontains=term)
                lookup |= Q(category__name__icontains=term)

            items = items.filter(lookup)

        if is_spicy:
            items = items.filter(spice_level__in=["medium", "hot"])
        if is_mild:
            items = items.filter(spice_level="mild")
        if is_featured:
            items = items.filter(is_featured=True)
        if is_veg:
            items = items.filter(veg=True)

        if not items.exists():
            zero_results = True
            recommended_items = MenuItem.objects.filter(is_available=True, is_featured=True)[:6]
            items = MenuItem.objects.none()
            categories = Category.objects.none()
        else:
            if not is_pure_intent:
                items = items.annotate(
                    relevance=Case(
                        When(name__iexact=query, then=1),
                        When(name__icontains=query, then=2),
                        When(category__name__icontains=query, then=3),
                        default=4,
                        output_field=IntegerField(),
                    )
                ).order_by("relevance", "-is_featured", "name")
            else:
                items = items.order_by("-is_featured", "name")

    if not zero_results:
        if query:
            category_ids = items.values_list("category_id", flat=True).distinct()
            categories = Category.objects.filter(id__in=category_ids).prefetch_related(
                Prefetch("items", queryset=items)
            )
        else:
            categories = Category.objects.all().prefetch_related(
                Prefetch("items", queryset=items)
            )

    popular_ids = list(
        OrderItem.objects.filter(order__is_paid=True)
        .values("menu_item_id")
        .annotate(total_sold=Sum("quantity"))
        .order_by("-total_sold")
        .values_list("menu_item_id", flat=True)[:5]
    )

    top_companion_map = cache.get("dineqr_companion_map")
    if top_companion_map is None:
        historical_orders = OrderItem.objects.filter(
            order__is_paid=True,
            order__created_at__gte=timezone.now() - timedelta(days=30)
        ).values("order_id", "menu_item_id")

        order_baskets = defaultdict(list)
        for row in historical_orders:
            order_baskets[row["order_id"]].append(row["menu_item_id"])

        pairing_matrix = defaultdict(lambda: defaultdict(int))
        for basket in order_baskets.values():
            for item_a in basket:
                for item_b in basket:
                    if item_a != item_b:
                        pairing_matrix[item_a][item_b] += 1

        top_companion_map = {}
        for item_id, companions in pairing_matrix.items():
            if companions:
                valid_companions = {k: v for k, v in companions.items() if v >= 5}
                if valid_companions:
                    top_companion_map[item_id] = max(valid_companions, key=lambda k: valid_companions[k])

        cache.set("dineqr_companion_map", top_companion_map, 7200)

    companion_ids = {comp_id for comp_id in top_companion_map.values() if comp_id}
    companions_by_id = {
        item.id: item for item in MenuItem.objects.filter(id__in=companion_ids, is_available=True)
    }

    items_list = list(items)
    for item in items_list:
        comp_id = top_companion_map.get(item.id)
        item.frequent_companion = companions_by_id.get(comp_id) if comp_id else None

    current_hour = timezone.localtime(timezone.now()).hour
    if 5 <= current_hour < 12:
        greeting = "Good Morning ☕"
    elif 12 <= current_hour < 17:
        greeting = "Good Afternoon 🍛"
    elif 17 <= current_hour < 22:
        greeting = "Good Evening 🍽️"
    else:
        greeting = "Late Night Cravings? 🌙"

    context = {
        "items": items_list,
        "categories": categories,
        "query": query,
        "zero_results": zero_results,
        "recommended_items": recommended_items,
        "popular_ids": popular_ids,
        "greeting": greeting,
    }
    return render(request, "orders/menu.html", context)


def cart_detail(request):
    table_num = request.GET.get("table")
    order_id = request.GET.get("order")

    if table_num:
        try:
            table_int = int(table_num)
        except ValueError:
            return HttpResponseForbidden("Invalid table")

        if table_int != 0:
            client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
            session_valid = TableSession.objects.filter(
                table_number=table_int,
                session_token=client_token,
                is_active=True
            ).exists()
            if not session_valid:
                return HttpResponseForbidden("Invalid or missing session token")

    previous_orders = Order.objects.none()
    running_total = Decimal("0.00")
    show_thanks = False

    if order_id:
        previous_orders = Order.objects.filter(id=order_id).exclude(status__in=["completed", "canceled"]).prefetch_related("items__menu_item")
        if not previous_orders.exists() and Order.objects.filter(id=order_id, status="completed").exists():
            show_thanks = True
    elif table_num:
        previous_orders = Order.objects.filter(table_number=table_num).exclude(status__in=["completed", "canceled"]).order_by("-created_at").prefetch_related("items__menu_item")
        recently_settled = Order.objects.filter(table_number=table_num, status="completed", paid_at__gte=timezone.now() - timedelta(minutes=10)).exists()
        if not previous_orders.exists() and recently_settled:
            show_thanks = True

    for order in previous_orders:
        running_total += order.effective_total

    qr_code = None
    if previous_orders:
        first_order = previous_orders[0]
        local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")
        qr_code = generate_bill_qr({
            "amount": f"{running_total:,.2f}",
            "order_id": first_order.id,
            "table_number": table_num if table_num else f"WalkIn-{first_order.id}",
            "timestamp": local_time,
        })

    popular_item_ids = OrderItem.objects.filter(order__is_paid=True).values("menu_item_id").annotate(total_sold=Sum("quantity")).order_by("-total_sold").values_list("menu_item_id", flat=True)[:4]
    popular_items = MenuItem.objects.filter(id__in=popular_item_ids, is_available=True)
    if not popular_items.exists():
        popular_items = MenuItem.objects.filter(is_available=True, is_featured=True)[:4]

    has_ready_orders = previous_orders.filter(status="ready").exists()

    user_loyalty_points = 0
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        user_loyalty_points = profile.loyalty_points

    return render(request, "orders/cart_detail.html", {
        "previous_orders": previous_orders,
        "running_total": running_total,
        "show_thanks": show_thanks,
        "qr_code": qr_code,
        "popular_items": popular_items,
        "has_ready_orders": has_ready_orders,
        "user_loyalty_points": user_loyalty_points,
    })


def place_order(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        cart = data.get("cart") or {}
        raw_table_number = data.get("table_number")
        requested_points = int(data.get("points_to_redeem", 0))

        if not cart or raw_table_number is None:
            return JsonResponse({"status": "error", "message": "Invalid data"}, status=400)

        try:
            table_num = int(raw_table_number)
            if table_num < 0:
                return JsonResponse({"status": "error", "message": "Table number cannot be negative"}, status=400)
        except ValueError:
            return JsonResponse({"status": "error", "message": "Invalid table format"}, status=400)

        if table_num != 0:
            client_token = request.headers.get("X-Session-Token")
            if not client_token:
                return JsonResponse(
                    {"status": "error", "message": "Session token missing. Please scan the QR code again."},
                    status=401
                )

            session_exists = TableSession.objects.filter(
                table_number=table_num,
                session_token=client_token,
                is_active=True
            ).exists()

            if not session_exists:
                return JsonResponse(
                    {"status": "error", "message": "Invalid session for this table. Please re-scan your table QR code."},
                    status=403
                )

        with transaction.atomic():
            new_order = Order.objects.create(
                user=request.user if request.user.is_authenticated else None,
                table_number=table_num,
                status="received",
                total_price=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
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

            # Handle Point Redemption with select_for_update
            if requested_points > 0 and request.user.is_authenticated:
                profile = UserProfile.objects.select_for_update().get(user=request.user)
                max_redeemable = (min(profile.loyalty_points, int(running_total)) // 100) * 100
                actual_points = min(requested_points - (requested_points % 100), max_redeemable)

                if actual_points >= 100:
                    discount = Decimal(str(actual_points))
                    new_order.discount_amount = discount
                    profile.loyalty_points -= actual_points
                    profile.save()

            new_order.save()

        return JsonResponse({"status": "success", "order_id": new_order.id})

    except MenuItem.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Menu item not found"}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Malformed JSON payload"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": "Internal server error"}, status=500)


def order_success(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, "orders/order_success.html", {"order": order})


def get_order_status(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
        return JsonResponse({"status": order.status})
    except Order.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)


@login_required
@user_passes_test(is_kitchen_or_higher)
def update_order_status(request, order_id):
    if request.method == "POST":
        try:
            order = Order.objects.get(id=order_id)

            if request.content_type == "application/json":
                data = json.loads(request.body)
                new_status = data.get("status", "ready")
            else:
                new_status = request.POST.get("status", "ready")

            valid_statuses = ["preparing", "ready", "completed"]
            if new_status in valid_statuses:
                order.status = new_status

                if new_status in ["ready", "completed"]:
                    order.items.all().update(status="ready")

                    # --- AUTOMATICALLY CALL WAITER TO PICK UP FOOD ---
                    if new_status == "ready":
                        existing_call = WaiterCall.objects.filter(
                            table_number=order.table_number,
                            is_resolved=False
                        ).first()
                        if not existing_call:
                            WaiterCall.objects.create(
                                table_number=order.table_number,
                                reason="food_ready",
                                is_resolved=False
                            )

                order.save()

            if request.content_type == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"status": "success", "new_status": order.status})

        except Order.DoesNotExist:
            if request.content_type == "application/json":
                return JsonResponse({"status": "error", "message": "Order not found"}, status=404)

        return redirect("kitchen_dashboard")

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)



def cancel_order_item(request, item_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        item = OrderItem.objects.select_related("order").get(id=item_id, order__status="received")
        order = item.order

        if order.table_number != 0:
            client_token = request.headers.get("X-Session-Token")
            session_valid = TableSession.objects.filter(
                table_number=order.table_number,
                session_token=client_token,
                is_active=True
            ).exists()
            if not session_valid:
                return JsonResponse({"status": "error", "message": "Unauthorized session"}, status=403)

        with transaction.atomic():
            item.delete()
            remaining_items = order.items.all()
            if not remaining_items.exists():
                if order.user and order.discount_amount > 0:
                    profile, _ = UserProfile.objects.get_or_create(user=order.user)
                    profile.loyalty_points += int(order.discount_amount)
                    profile.save()
                order.delete()
            else:
                new_total = sum(Decimal(str(i.menu_item.price)) * i.quantity for i in remaining_items)
                order.total_price = new_total
                order.save()

        return JsonResponse({"status": "success"})

    except OrderItem.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Item not found or already being prepared"},
            status=404,
        )


@user_passes_test(is_management_or_owner)
@login_required
def management_dashboard(request):
    try:
        cutoff_date = timezone.now() - timedelta(days=30)
        Review.objects.filter(created_at__lt=cutoff_date).delete()
    except Exception:
        pass

    current_tab = request.GET.get("tab", "tables")
    sentiment_filter = request.GET.get("sentiment", "all")

    all_active_orders = Order.objects.exclude(status="completed")
    total_live_revenue = all_active_orders.aggregate(Sum("total_price"))["total_price__sum"] or Decimal("0.00")
    busy_tables_count = all_active_orders.values("table_number").distinct().count()
    table_data = []
    insights_data = {}
    recent_reviews = []

    context = {}

    if current_tab in ["tables", "qr"]:
        walkin_orders = Order.objects.filter(table_number=0).exclude(status="completed").order_by('-created_at')

        active_table_orders = Order.objects.filter(
            table_number__gte=1, table_number__lte=10
        ).exclude(status="completed")

        orders_by_table = defaultdict(list)
        for ord_obj in active_table_orders:
            orders_by_table[ord_obj.table_number].append(ord_obj)

        locked_tables = set(
            TableSession.objects.filter(
                table_number__gte=1, table_number__lte=10, is_active=True
            ).values_list("table_number", flat=True)
        )

        for i in range(1, 11):
            t_orders = orders_by_table.get(i, [])
            if t_orders:
                total_bill = sum(o.total_price for o in t_orders)
                statuses = [o.status for o in t_orders]
                display_status = (
                    "ready" if "ready" in statuses
                    else ("preparing" if "preparing" in statuses else "received")
                )
                table_data.append({
                    "number": i,
                    "status": display_status,
                    "total": total_bill,
                    "has_orders": True,
                    "is_locked": i in locked_tables,
                })
            else:
                table_data.append({
                    "number": i,
                    "status": "empty",
                    "total": 0,
                    "has_orders": False,
                    "is_locked": i in locked_tables,
                })

        context.update({"walkin_orders": walkin_orders})

    elif current_tab == "insights":
        top_items = (
            OrderItem.objects.filter(order__is_paid=True)
            .values("menu_item__name")
            .annotate(total_sold=Sum("quantity"))
            .order_by("-total_sold")[:5]
        )
        avg_rating = Review.objects.aggregate(Avg("rating"))["rating__avg"] or 0

        hourly_data = (
            Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=7))
            .annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(count=Count("id"))
            .order_by("hour")
        )

        diet_shares = (
            OrderItem.objects.filter(order__is_paid=True)
            .values("menu_item__veg")
            .annotate(total_qty=Sum("quantity"))
        )
        formatted_diet_shares = [
            {
                "label": "Vegetarian" if item["menu_item__veg"] else "Non-Vegetarian",
                "value": item["total_qty"],
            }
            for item in diet_shares
        ]

        category_shares = (
            OrderItem.objects.filter(order__status="completed")
            .values("menu_item__category__name")
            .annotate(total_qty=Sum("quantity"))
            .order_by("-total_qty")
        )

        sentiment_counts = Review.objects.values("sentiment").annotate(count=Count("id"))
        sentiment_dict = {item["sentiment"]: item["count"] for item in sentiment_counts}
        total_reviews = sum(sentiment_dict.values()) or 1
        sentiment_ratios = {
            "positive": round((sentiment_dict.get("positive", 0) / total_reviews) * 100, 1),
            "neutral": round((sentiment_dict.get("neutral", 0) / total_reviews) * 100, 1),
            "negative": round((sentiment_dict.get("negative", 0) / total_reviews) * 100, 1),
        }

        waiter_telemetry = (
            WaiterCall.objects.values("reason")
            .annotate(total_calls=Count("id"))
            .order_by("-total_calls")
        )
        formatted_waiter_calls = [
            {
                "reason": dict(WaiterCall.REASON_CHOICES).get(item["reason"], item["reason"]),
                "count": item["total_calls"],
            }
            for item in waiter_telemetry
        ]

        order_item_groups = OrderItem.objects.filter(
            order__created_at__gte=timezone.now() - timedelta(days=90)
        ).values("order_id", "menu_item__name")

        orders_map = defaultdict(list)
        for entry in order_item_groups:
            orders_map[entry["order_id"]].append(entry["menu_item__name"])

        pair_counter = Counter()
        for items_list in orders_map.values():
            unique_items = sorted(list(set(items_list)))
            for pair in combinations(unique_items, 2):
                pair_counter[pair] += 1

        frequent_pairs = [
            {"item_a": p[0], "item_b": p[1], "support_count": c}
            for p, c in pair_counter.most_common(4)
        ]

        table_revenue = (
            Order.objects.filter(status="completed")
            .values("table_number")
            .annotate(total_earned=Sum("total_price"), total_tickets=Count("id"))
            .order_by("-total_earned")[:5]
        )

        days_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        weekly_traffic = (
            Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=30))
            .annotate(weekday=ExtractWeekDay("created_at"))
            .values("weekday")
            .annotate(volume=Count("id"))
            .order_by("weekday")
        )
        formatted_weekly_traffic = [
            {"day_name": days_map.get(item["weekday"], "Unk"), "volume": item["volume"]}
            for item in weekly_traffic
        ]

        payment_audit = Order.objects.aggregate(
            collected=Count("id", filter=Q(is_paid=True)),
            unsettled=Count("id", filter=Q(is_paid=False)),
        )

        timed_orders = (
            Order.objects.filter(status="completed", is_paid=True, paid_at__isnull=False)
            .annotate(duration=ExpressionWrapper(F("paid_at") - F("created_at"), output_field=DurationField()))
            .aggregate(avg_time=Avg("duration"))
        )

        avg_turnaround_mins = 0
        if timed_orders["avg_time"]:
            avg_turnaround_mins = round(timed_orders["avg_time"].total_seconds() / 60, 1)

        financial_bleed = Order.objects.filter(status="canceled").aggregate(
            lost_cash=Sum("total_price"), lost_count=Count("id")
        )

        negative_review_order_ids = Review.objects.filter(sentiment="negative").values_list("order_id", flat=True)
        toxic_dishes = (
            OrderItem.objects.filter(order_id__in=negative_review_order_ids)
            .values("menu_item__name")
            .annotate(complaint_weight=Count("id"))
            .order_by("-complaint_weight")[:3]
        )

        insights_data = {
            "top_items": list(top_items),
            "avg_rating": round(avg_rating, 1),
            "hourly_data": list(hourly_data),
            "diet_shares": formatted_diet_shares,
            "category_shares": list(category_shares),
            "sentiment_ratios": sentiment_ratios,
            "waiter_telemetry": formatted_waiter_calls,
            "frequent_pairs": frequent_pairs,
            "table_revenue": list(table_revenue),
            "weekly_traffic": formatted_weekly_traffic,
            "payment_audit": payment_audit,
            "avg_turnaround_mins": avg_turnaround_mins,
            "lost_revenue": financial_bleed["lost_cash"] or 0,
            "lost_tickets_count": financial_bleed["lost_count"] or 0,
            "toxic_dishes": list(toxic_dishes),
        }

        today_local = timezone.localdate()
        shift_orders = Order.objects.filter(
            status="completed",
            created_at__date=today_local,
        )
        z_metrics = shift_orders.aggregate(
            gross=Sum("total_price"), count=Count("id"), avg_spend=Avg("total_price")
        )
        canceled_count = Order.objects.filter(
            status="canceled",
            created_at__date=today_local,
        ).count()

        context.update({
            "z_gross_sales": z_metrics["gross"] or 0,
            "z_ticket_count": z_metrics["count"] or 0,
            "z_avg_ticket": round(z_metrics["avg_spend"] or 0, 2) if z_metrics["avg_spend"] else 0,
            "z_canceled_count": canceled_count,
        })

    elif current_tab == "reviews":
        recent_reviews = Review.objects.select_related("menu_item").all().order_by("-created_at")

        sentiment_stats = Review.objects.aggregate(
            total=Count("id"),
            pos=Count("id", filter=Q(sentiment="positive")),
            neu=Count("id", filter=Q(sentiment="neutral")),
            neg=Count("id", filter=Q(sentiment="negative")),
        )

        total_count = sentiment_stats["total"] or 1
        pos_pct = round((sentiment_stats["pos"] / total_count) * 100)
        neu_pct = round((sentiment_stats["neu"] / total_count) * 100)
        neg_pct = round((sentiment_stats["neg"] / total_count) * 100)

        if sentiment_filter in ["positive", "neutral", "negative"]:
            recent_reviews = recent_reviews.filter(sentiment=sentiment_filter)

        recent_reviews = recent_reviews[:20]

        context.update({
            "sentiment_stats": {
                "total": sentiment_stats["total"],
                "pos": sentiment_stats["pos"],
                "neu": sentiment_stats["neu"],
                "neg": sentiment_stats["neg"],
                "pos_pct": pos_pct,
                "neu_pct": neu_pct,
                "neg_pct": neg_pct,
            }
        })

    categories = Category.objects.prefetch_related("items").all()

    context.update({
        "tables": table_data,
        "categories": categories,
        "current_tab": current_tab,
        "total_live_revenue": total_live_revenue,
        "busy_tables_count": busy_tables_count,
        "insights": insights_data,
        "recent_reviews": recent_reviews,
        "current_sentiment": sentiment_filter,
    })

    return render(request, "orders/management_dashboard.html", context)


def order_review_page(request, order_id):
    try:
        current_order = Order.objects.get(id=order_id)
        if current_order.table_number == 0:
            orders_to_review = Order.objects.filter(id=current_order.id).prefetch_related("items__menu_item")
        else:
            orders_to_review = Order.objects.filter(
                table_number=current_order.table_number,
                created_at__gte=current_order.created_at - timedelta(hours=3),
                status__in=["received", "preparing", "ready", "completed"],
            ).prefetch_related("items__menu_item")
    except Order.DoesNotExist:
        return redirect("menu")

    if current_order.table_number != 0:
        client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
        session_valid = TableSession.objects.filter(
            table_number=current_order.table_number,
            session_token=client_token,
            is_active=True
        ).exists()
        if not session_valid:
            return HttpResponseForbidden("Invalid session")

    if request.method == "POST":
        reviewed_menu_item_ids = set()
        for order in orders_to_review:
            for item in order.items.all():
                menu_item_id = item.menu_item.id
                if menu_item_id in reviewed_menu_item_ids:
                    continue

                rating_val = request.POST.get(f"rating_{menu_item_id}")
                comment_val = request.POST.get(f"comment_{menu_item_id}", "").strip()

                if rating_val:
                    try:
                        parsed_rating = int(rating_val)
                    except ValueError:
                        continue

                    Review.objects.create(
                        order=order,
                        menu_item=item.menu_item,
                        rating=parsed_rating,
                        comment=comment_val,
                        sentiment=analyze_note_sentiment(comment_val) if comment_val else "neutral",
                    )
                    reviewed_menu_item_ids.add(menu_item_id)

        return redirect(f"{reverse('menu')}cart/?table={current_order.table_number}")

    items_to_review = []
    seen_items = set()
    for o in orders_to_review:
        for i in o.items.all():
            if i.menu_item.id not in seen_items:
                items_to_review.append(i.menu_item)
                seen_items.add(i.menu_item.id)

    return render(
        request,
        "orders/order_review.html",
        {"order": current_order, "items_to_review": items_to_review},
    )


@login_required
@user_passes_test(is_kitchen_or_higher)
def kitchen_dashboard(request):
    active_orders = Order.objects.filter(
        status__in=["received", "preparing"]
    ).prefetch_related("items__menu_item").order_by("created_at")

    item_summary = (
        OrderItem.objects.filter(order__status__in=["received", "preparing"])
        .values("menu_item__name")
        .annotate(total_qty=Sum("quantity"))
    )

    latest_broadcast = KitchenBroadcast.objects.last()
    broadcast_message = latest_broadcast.message if latest_broadcast else None

    return render(
        request,
        "orders/kitchen.html",
        {
            "orders": active_orders,
            "item_summary": item_summary,
            "broadcast_message": broadcast_message,
        },
    )


@login_required
@user_passes_test(is_management_or_owner)
def mark_table_paid(request, table_num):
    if request.method == "POST":
        active_orders = Order.objects.filter(table_number=table_num).exclude(status="completed")
        with transaction.atomic():
            for order in active_orders.select_for_update():
                order.is_paid = True
                order.paid_at = timezone.localtime()
                order.status = "completed"
                order.save()

                if order.user:
                    profile, _ = UserProfile.objects.select_for_update().get_or_create(user=order.user)
                    earned_pts = int(order.effective_total // 10)
                    if earned_pts > 0:
                        profile.loyalty_points += earned_pts
                        profile.save()
    return redirect("management_dashboard")

@login_required
@user_passes_test(is_management_or_owner)
def toggle_item_availability(request, item_id):
    try:
        item = MenuItem.objects.get(id=item_id)
        item.is_available = not item.is_available
        item.save()
    except MenuItem.DoesNotExist:
        pass
    return redirect(f"{reverse('management_dashboard')}?tab=menu")


def table_bill(request, table_num):
    if table_num:
        try:
            table_int = int(table_num)
        except ValueError:
            return HttpResponseForbidden("Invalid table")

        if table_int != 0:
            client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
            session_valid = TableSession.objects.filter(
                table_number=table_int,
                session_token=client_token,
                is_active=True
            ).exists()
            if not session_valid:
                return HttpResponseForbidden("Invalid or missing session token")

    active_orders = Order.objects.filter(table_number=table_num).exclude(status="completed")
    items = OrderItem.objects.filter(order__in=active_orders).select_related("menu_item")
    total = active_orders.aggregate(Sum("total_price"))["total_price__sum"] or Decimal("0.00")
    first_order = active_orders.first()

    qr_code = None
    if first_order:
        local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")
        qr_code = generate_bill_qr({
            "amount": f"{total:,.2f}",
            "order_id": first_order.id,
            "table_number": table_num,
            "timestamp": local_time,
        })

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
    sold_out_ids = list(MenuItem.objects.filter(is_available=False).values_list("id", flat=True))
    return JsonResponse({"sold_out": sold_out_ids})


def call_waiter_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            raw_table_num = data.get("table_number")
            reason = data.get("reason") or "help"

            if raw_table_num is None:
                return JsonResponse({"status": "error", "message": "Table number missing."}, status=400)

            # Map 'KITCHEN' or 'COUNTER' text strings to integer 0
            if str(raw_table_num).upper() in ["KITCHEN", "COUNTER"]:
                table_num = 0
            else:
                try:
                    table_num = int(raw_table_num)
                except ValueError:
                    return JsonResponse({"status": "error", "message": "Table number must be a valid integer."}, status=400)

            # Prevent duplicate active calls for the same table/kitchen
            existing_call = WaiterCall.objects.filter(table_number=table_num, is_resolved=False).first()
            if existing_call:
                display_name = "Kitchen/Counter" if table_num == 0 else f"Table {table_num}"
                return JsonResponse({
                    "status": "error",
                    "message": f"Staff is already dispatched for {display_name}!",
                }, status=400)

            WaiterCall.objects.create(table_number=table_num, reason=reason)
            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": "Internal error processing waiter call."}, status=500)

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@login_required
@user_passes_test(is_kitchen_or_higher)
def get_active_waiter_calls(request):
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


@login_required
@user_passes_test(is_kitchen_or_higher)
def resolve_waiter_call(request, call_id):
    if request.method == "POST":
        try:
            call = WaiterCall.objects.get(id=call_id)
            call.is_resolved = True
            call.save()
            return JsonResponse({"status": "success"})
        except WaiterCall.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Waiter call record not found"}, status=404)

    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)


def verify_table_session(request):
    table_num = request.GET.get("table")
    client_token = request.headers.get("X-Session-Token")

    body_data = {}
    if request.body:
        try:
            body_data = json.loads(request.body)
        except json.JSONDecodeError:
            pass

    passcode = request.GET.get("passcode") or body_data.get("passcode")
    # Default host_name to "Guest" automatically
    host_name = request.GET.get("host_name") or body_data.get("host_name") or "Guest"

    if not table_num:
        return JsonResponse({"status": "error", "message": "No table specified"}, status=400)

    try:
        table_int = int(table_num)
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid table format"}, status=400)

    session = TableSession.objects.filter(
        table_number=table_int, is_active=True
    ).first()

    if session:
        if client_token and str(session.session_token) == client_token:
            return JsonResponse({"status": "success", "token": str(session.session_token)})

        if session.session_passcode:
            if passcode and passcode == session.session_passcode:
                return JsonResponse({"status": "success", "token": str(session.session_token)})
            return JsonResponse(
                {"status": "password_required", "message": "Table session password required"},
                status=401
            )

        return JsonResponse({"status": "success", "token": str(session.session_token)})

    # Create new table session (caller is host)
    host_user = request.user if request.user.is_authenticated else None
    new_session = TableSession.objects.create(
        table_number=table_int,
        session_passcode=passcode if passcode else None,
        host_name=host_name,
        host_user=host_user,
        is_active=True,
    )

    return JsonResponse({"status": "success", "token": str(new_session.session_token), "is_host": True})


@login_required
@user_passes_test(is_management_or_owner)
def toggle_item_featured(request, item_id):
    if request.method == "POST":
        item = get_object_or_404(MenuItem, id=item_id)
        item.is_featured = not item.is_featured
        item.save()
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
    try:
        table_int = int(table_num)
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid table number"}, status=400)

    if not request.user.is_authenticated:
        client_token = request.headers.get("X-Session-Token")
        if not client_token or not TableSession.objects.filter(table_number=table_int, session_token=client_token, is_active=True).exists():
            return JsonResponse({"status": "error", "message": "Unauthorized session token"}, status=403)

    try:
        if request.method == "POST":
            data = json.loads(request.body)
        else:
            data = request.GET.dict()

        items_to_pay = data.get("items", [])
        manual_amount = Decimal(str(data.get("amount", 0)))
        payment_method = data.get("payment_method", "qr")
        order_id = data.get("order_id")
    except (json.JSONDecodeError, InvalidOperation, ValueError):
        return JsonResponse({"status": "error", "message": "Malformed request parameters"}, status=400)

    if order_id:
        active_orders = Order.objects.filter(id=order_id).exclude(status="completed")
    else:
        active_orders = Order.objects.filter(table_number=table_int).exclude(status="completed")

    if not active_orders.exists():
        return JsonResponse({"status": "error", "message": "No active orders"}, status=400)

    if payment_method == "cash":
        WaiterCall.objects.create(table_number=table_int, reason="cash", is_resolved=False)
        return JsonResponse({
            "status": "success",
            "table_cleared": False,
            "message": "Waiter is on the way with the bill.",
        })

    order_ids = list(active_orders.values_list("id", flat=True))

    with transaction.atomic():
        if items_to_pay:
            for entry in items_to_pay:
                try:
                    order_item = OrderItem.objects.select_for_update().select_related(
                        "menu_item", "order"
                    ).get(id=entry["id"])
                    share_count = max(1, int(entry.get("shareCount", 1)))

                    unpaid_qty = Decimal(str(order_item.quantity)) - (order_item.paid_quantity or Decimal("0"))
                    qty_share = Decimal(str(order_item.quantity)) / share_count
                    qty_share = min(qty_share, unpaid_qty)

                    if qty_share <= 0:
                        continue

                    order_item.paid_quantity = (order_item.paid_quantity or Decimal("0")) + qty_share
                    order_item.save()

                    order = Order.objects.select_for_update().get(id=order_item.order_id)
                    order.paid_amount = (order.paid_amount or Decimal("0")) + (
                        Decimal(str(order_item.menu_item.price)) * qty_share
                    )
                    order.save()
                except (OrderItem.DoesNotExist, ValueError, InvalidOperation):
                    pass

        elif manual_amount > 0:
            remaining = manual_amount
            locked_orders = Order.objects.select_for_update().filter(id__in=order_ids)
            for order in locked_orders:
                if remaining <= Decimal("0"):
                    break
                to_pay = min(remaining, order.remaining_balance)
                order.paid_amount = (order.paid_amount or Decimal("0")) + to_pay
                remaining -= to_pay
                order.save()

        all_done = True
        locked_orders = Order.objects.select_for_update().filter(id__in=order_ids)
        for order in locked_orders:
            if order.remaining_balance > Decimal("0.01"):
                all_done = False
            else:
                order.status = "completed"
                order.is_paid = True
                order.paid_at = timezone.now()
                order.save()

                if order.user:
                    profile, _ = UserProfile.objects.select_for_update().get_or_create(user=order.user)
                    earned_points = int(order.effective_total // 10)
                    if earned_points > 0:
                        profile.loyalty_points += earned_points
                        profile.save()

    WaiterCall.objects.create(table_number=table_int, reason="paid", is_resolved=False)

    if all_done:
        TableSession.objects.filter(table_number=table_int, is_active=True).update(is_active=False)

    return JsonResponse({"status": "success", "table_cleared": all_done})


def generate_split_qr_api(request):
    table_num = request.GET.get("table")
    amount = request.GET.get("amount", "0.00")

    if table_num:
        try:
            table_int = int(table_num)
        except ValueError:
            return HttpResponseForbidden("Invalid table")

        if table_int != 0:
            client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
            session_valid = TableSession.objects.filter(
                table_number=table_int,
                session_token=client_token,
                is_active=True
            ).exists()
            if not session_valid:
                return HttpResponseForbidden("Invalid or missing session token")

    try:
        parsed_amount = float(amount)
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid amount payload"}, status=400)

    active_orders = Order.objects.filter(table_number=table_num).exclude(status="completed")
    first_order = active_orders.first()
    order_id = first_order.id if first_order else "000"
    local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")

    qr_base64 = generate_bill_qr({
        "amount": f"{parsed_amount:,.2f}",
        "order_id": order_id,
        "table_number": table_num,
        "timestamp": local_time,
    })
    return JsonResponse({"qr_code": qr_base64})


@login_required
@user_passes_test(is_management_or_owner)
def serve_table_qr(request, table_num):
    host_address = 'https://reversion-bounce-drew.ngrok-free.dev/'
    target_url = f"{host_address}welcome/?table={table_num}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


@login_required
@user_passes_test(is_kitchen_or_higher)
def update_kitchen_broadcast(request):
    if request.method == "POST":
        new_message = request.POST.get("message", "").strip()
        KitchenBroadcast.objects.all().delete()
        if new_message:
            KitchenBroadcast.objects.create(message=new_message)
    return redirect(request.META.get("HTTP_REFERER", "management_dashboard"))


@login_required
@user_passes_test(is_management_or_owner)
def save_menu_item(request, item_id=None):
    if request.method == "POST":
        category_id = request.POST.get("category")
        category = get_object_or_404(Category, id=category_id)

        if item_id:
            item = get_object_or_404(MenuItem, id=item_id)
        else:
            item = MenuItem()

        item.name = request.POST.get("name")
        item.category = category
        item.price = request.POST.get("price")
        item.description = request.POST.get("description", "")
        item.preparation_time = request.POST.get("preparation_time", 15)
        item.spice_level = request.POST.get("spice_level", "neutral")
        item.veg = request.POST.get("veg") == "true"

        if "image" in request.FILES:
            item.image = request.FILES["image"]

        item.save()
    return redirect(f"{reverse('management_dashboard')}?tab=menu")


@login_required
@user_passes_test(is_management_or_owner)
def save_category(request, category_id=None):
    if request.method == "POST":
        if category_id:
            category = get_object_or_404(Category, id=category_id)
        else:
            category = Category()

        category.name = request.POST.get("name")
        category.save()
    return redirect(f"{reverse('management_dashboard')}?tab=menu")


@login_required
@user_passes_test(is_management_or_owner)
def unified_delete(request, model_type, object_id):
    if request.method != "POST":
        return HttpResponseForbidden("Must use POST to delete.")

    return_tab = "menu"
    try:
        if model_type == "menu_item":
            obj = get_object_or_404(MenuItem, id=object_id)
        elif model_type == "category":
            obj = get_object_or_404(Category, id=object_id)
        elif model_type == "review":
            obj = get_object_or_404(Review, id=object_id)
            return_tab = "reviews"
        elif model_type == "order":
            obj = get_object_or_404(Order, id=object_id)
            return_tab = "tables"
        else:
            return HttpResponseForbidden("Invalid model type.")

        obj.delete()
    except Exception:
        pass

    return redirect(f"{reverse('management_dashboard')}?tab={return_tab}")


@login_required
@user_passes_test(is_management_or_owner)
def staff_place_order(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        table_num = int(data.get("table_number", 0))
        cart = data.get("cart", [])

        if not cart:
            return JsonResponse({"status": "error", "message": "Cart is empty"}, status=400)

        with transaction.atomic():
            new_order = Order.objects.create(
                table_number=table_num,
                status="received",
                total_price=Decimal("0.00")
            )

            running_total = Decimal("0.00")
            for item in cart:
                menu_item = MenuItem.objects.get(id=item.get("id"))
                qty = int(item.get("qty", item.get("quantity", 1)))

                OrderItem.objects.create(
                    order=new_order,
                    menu_item=menu_item,
                    quantity=qty,
                    notes=item.get("notes", "")
                )
                running_total += Decimal(str(menu_item.price)) * qty

            new_order.total_price = running_total
            new_order.save()

        return JsonResponse({"status": "success"})
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Malformed JSON payload"}, status=400)


@login_required
@user_passes_test(is_management_or_owner)
def get_table_orders(request, table_num):
    active_orders = Order.objects.filter(table_number=table_num).exclude(status="completed").prefetch_related("items__menu_item")
    items_data = []

    for order in active_orders:
        for item in order.items.all():
            items_data.append({
                "item_id": item.id,
                "name": item.menu_item.name,
                "qty": item.quantity,
                "price": float(item.menu_item.price),
                "notes": item.notes,
                "order_status": order.status,
                "order_id": order.id
            })

    return JsonResponse({"items": items_data, "table": table_num})


@login_required
@user_passes_test(is_management_or_owner)
def modify_order_item(request, item_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        action = data.get("action")
        item = OrderItem.objects.select_related("order", "menu_item").get(id=item_id)
        order = item.order
        item_price = Decimal(str(item.menu_item.price))

        with transaction.atomic():
            if action == "increase":
                item.quantity += 1
                item.save()
                order.total_price += item_price
            elif action == "decrease":
                if item.quantity > 1:
                    item.quantity -= 1
                    item.save()
                    order.total_price -= item_price
                else:
                    order.total_price -= item_price
                    item.delete()
            elif action == "delete":
                order.total_price -= (item_price * item.quantity)
                item.delete()

            order.save()

            if order.items.count() == 0:
                order.delete()

        return JsonResponse({"status": "success"})
    except OrderItem.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Item not found"}, status=404)


@login_required
@user_passes_test(is_management_or_owner)
def mark_order_paid(request, order_id):
    if request.method == "POST":
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), id=order_id)
            order.is_paid = True
            order.paid_at = timezone.now()
            order.status = "completed"
            order.save()

            if order.user:
                profile, _ = UserProfile.objects.select_for_update().get_or_create(user=order.user)
                earned_pts = int(order.effective_total // 10)
                if earned_pts > 0:
                    profile.loyalty_points += earned_pts
                    profile.save()
    return redirect("management_dashboard")


@login_required
@user_passes_test(is_management_or_owner)
def single_order_bill(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    items = order.items.select_related("menu_item").all()
    total = order.total_price

    qr_code = generate_bill_qr({
        "amount": f"{total:,.2f}",
        "order_id": order.id,
        "table_number": "Counter",
        "timestamp": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p"),
    })

    context = {
        "table_num": f"Walk-In #{order.id}",
        "items": items,
        "total": total,
        "date": timezone.localtime(timezone.now()),
        "bill_id": order.id,
        "qr_code": qr_code,
    }
    return render(request, "orders/bill_print.html", context)


@login_required
@user_passes_test(is_management_or_owner)
def get_drawer_items(request):
    table_num = request.GET.get('table')
    order_id = request.GET.get('order')

    if order_id:
        active_orders = Order.objects.filter(id=order_id).prefetch_related("items__menu_item")
    elif table_num:
        active_orders = Order.objects.filter(table_number=table_num).exclude(status="completed").prefetch_related("items__menu_item")
    else:
        return JsonResponse({"items": []})

    items_data = []
    for order in active_orders:
        for item in order.items.all():
            items_data.append({
                "item_id": item.id,
                "name": item.menu_item.name,
                "qty": item.quantity,
                "price": float(item.menu_item.price),
                "notes": item.notes,
                "order_status": order.status,
                "order_id": order.id
            })
    return JsonResponse({"items": items_data})


@login_required
@user_passes_test(is_management_or_owner)
def clear_old_reviews(request):
    if request.method == "POST":
        days_threshold = 30
        cutoff_date = timezone.now() - timedelta(days=days_threshold)
        deleted_count, _ = Review.objects.filter(created_at__lt=cutoff_date).delete()
        messages.success(request, f"Successfully cleared {deleted_count} reviews older than {days_threshold} days.")
    return redirect(f"{reverse('management_dashboard')}?tab=reviews")


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        if is_management_or_owner(request.user):
            return redirect('management_dashboard')
        elif is_kitchen_or_higher(request.user):
            return redirect('kitchen_dashboard')
        else:
            return redirect('menu')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if is_management_or_owner(user):
                return redirect('management_dashboard')
            elif is_kitchen_or_higher(user):
                return redirect('kitchen_dashboard')
            else:
                return redirect('menu')
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'orders/login.html')


@never_cache
def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
@user_passes_test(is_kitchen_or_higher)
def kitchen_orders_api(request):
    """API Endpoint for lightweight 5-second AJAX polling"""
    station_filter = request.GET.get('station', 'ALL')

    # Base Queryset
    active_orders = Order.objects.filter(
        status__in=["received", "preparing"]
    ).prefetch_related("items__menu_item").order_by("created_at")

    orders_data = []
    for order in active_orders:
        items = []
        for item in order.items.all():
            # Apply station filter if selected
            if station_filter != 'ALL' and item.menu_item.station != station_filter:
                continue

            items.append({
                "id": item.id,
                "name": item.menu_item.name,
                "quantity": item.quantity,
                "notes": item.notes,
                "status": item.status,
                "station": item.menu_item.station,
            })

        # Skip ticket if no items match the active station filter
        if not items:
            continue

        orders_data.append({
            "id": order.id,
            "table_number": order.table_number,
            "status": order.status,
            "created_at": order.created_at.isoformat(),
            "items": items,
        })

    # Summary breakdown
    summary_qs = OrderItem.objects.filter(order__status__in=["received", "preparing"])
    if station_filter != 'ALL':
        summary_qs = summary_qs.filter(menu_item__station=station_filter)

    summary = list(
        summary_qs.values("menu_item__name")
        .annotate(total_qty=Sum("quantity"))
    )

    broadcast = KitchenBroadcast.objects.last()

    return JsonResponse({
        "orders": orders_data,
        "summary": summary,
        "broadcast": broadcast.message if broadcast else None,
    })

@login_required
@user_passes_test(is_kitchen_or_higher)
def update_item_status(request, item_id):
    """Checkbox toggle: Sets item to 'preparing' or 'received'"""
    try:
        data = json.loads(request.body)
        new_status = data.get("status")  # Will be 'preparing' or 'received'

        if new_status not in ["received", "preparing", "ready"]:
            return JsonResponse({"status": "error", "message": "Invalid status"}, status=400)

        item = OrderItem.objects.select_related("order").get(id=item_id)
        item.status = new_status
        item.save()

        # Update order to 'preparing' if any item starts cooking
        order = item.order
        if order.status == "received" and new_status == "preparing":
            order.status = "preparing"
            order.save()

        return JsonResponse({"status": "success", "item_status": item.status})
    except OrderItem.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Item not found"}, status=404)

@login_required
@user_passes_test(is_kitchen_or_higher)
def get_recent_completed_orders(request):
    """Fetches orders completed in the last 30 minutes for the Recall feature"""
    cutoff = timezone.now() - timedelta(minutes=30)
    completed_orders = Order.objects.filter(
        status="ready",
        updated_at__gte=cutoff # assumes updated_at field or fallback to created_at
    ).prefetch_related("items__menu_item").order_by("-id")[:10]

    data = []
    for o in completed_orders:
        data.append({
            "id": o.id,
            "table_number": o.table_number,
            "items_summary": ", ".join([f"{i.quantity}x {i.menu_item.name}" for i in o.items.all()])
        })
    return JsonResponse({"completed_orders": data})


@login_required
@user_passes_test(is_kitchen_or_higher)
@require_POST
def recall_order_api(request, order_id):
    """Restores a completed/ready order back to active 'preparing' status"""
    try:
        order = Order.objects.get(id=order_id)
        order.status = "preparing"
        order.save()

        # Reset items back to preparing
        order.items.all().update(status="preparing")
        return JsonResponse({"status": "success"})
    except Order.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Order not found"}, status=404)

def welcome_view(request):
    table_num = request.GET.get("table")
    if not table_num:
        return redirect("menu")

    try:
        table_int = int(table_num)
    except ValueError:
        return redirect("menu")

    active_session = TableSession.objects.filter(
        table_number=table_int, is_active=True
    ).first()

    context = {
        "table_num": table_int,
        "active_session": active_session,
        "has_password": bool(active_session and active_session.session_passcode),
    }
    return render(request, "orders/welcome.html", context)


def customer_signup_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        email = data.get("email", "").strip()

        if not username or not password:
            return JsonResponse({"status": "error", "message": "Username and password required"}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "error", "message": "Username already taken"}, status=400)

        user = User.objects.create_user(username=username, password=password, email=email)
        UserProfile.objects.create(user=user, loyalty_points=0)

        login(request, user)
        return JsonResponse({"status": "success", "username": user.username})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def customer_login_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            return JsonResponse({
                "status": "success",
                "username": user.username,
                "points": profile.loyalty_points
            })
        return JsonResponse({"status": "error", "message": "Invalid credentials"}, status=400)

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def convert_guest_account_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        order_id = data.get("order_id")

        if not username or not password:
            return JsonResponse({"status": "error", "message": "Username and password required"}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "error", "message": "Username already taken"}, status=400)

        user = User.objects.create_user(username=username, password=password)
        profile = UserProfile.objects.create(user=user, loyalty_points=0)
        login(request, user)

        if order_id:
            try:
                order = Order.objects.get(id=order_id)
                order.user = user
                order.save()

                earned_pts = int(order.effective_total // 10)
                profile.loyalty_points += earned_pts
                profile.save()
            except Order.DoesNotExist:
                pass

        return JsonResponse({
            "status": "success",
            "username": user.username,
            "points": profile.loyalty_points
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def user_order_history_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"status": "error", "message": "Authentication required"}, status=401)

    orders = Order.objects.filter(user=request.user).order_by("-created_at").prefetch_related("items__menu_item")
    history = []
    for o in orders:
        items = [{"name": i.menu_item.name, "qty": i.quantity, "price": float(i.menu_item.price)} for i in o.items.all()]
        history.append({
            "order_id": o.id,
            "table_number": o.table_number,
            "status": o.status,
            "total_price": float(o.total_price),
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            "items": items,
        })

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return JsonResponse({"history": history, "loyalty_points": profile.loyalty_points})

@login_required
def customer_portal(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at").prefetch_related("items__menu_item")
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(
        request,
        "orders/customer_portal.html",
        {
            "orders": orders,
            "loyalty_points": profile.loyalty_points,
        },
    )

def update_table_cart(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        table_num = int(data.get("table_number"))
        cart = data.get("cart", {})
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"status": "error", "message": "Invalid payload"}, status=400)

    if table_num != 0:
        client_token = request.headers.get("X-Session-Token")
        session_valid = TableSession.objects.filter(
            table_number=table_num,
            session_token=client_token,
            is_active=True
        ).exists()
        if not session_valid:
            return JsonResponse({"status": "error", "message": "Unauthorized session"}, status=403)

    table_cart, _ = TableCart.objects.update_or_create(
        table_number=table_num,
        defaults={"cart_data": cart}
    )
    return JsonResponse({"status": "success", "updated_at": table_cart.updated_at.isoformat()})

def get_table_cart(request):
    table_num = request.GET.get("table")
    if not table_num:
        return JsonResponse({"status": "error", "message": "No table specified"}, status=400)

    try:
        table_int = int(table_num)
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid table format"}, status=400)

    if table_int != 0:
        client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
        session_valid = TableSession.objects.filter(
            table_number=table_int,
            session_token=client_token,
            is_active=True
        ).exists()
        if not session_valid:
            return JsonResponse({"status": "error", "message": "Invalid or missing session token"}, status=401)

    try:
        table_cart = TableCart.objects.get(table_number=table_int)
        return JsonResponse({
            "status": "success",
            "cart": table_cart.cart_data,
            "updated_at": table_cart.updated_at.isoformat(),
        })
    except TableCart.DoesNotExist:
        return JsonResponse({"status": "success", "cart": {}, "updated_at": None})

@login_required
@user_passes_test(is_management_or_owner)
def reset_table_session(request, table_num):
    if request.method == "POST":
        TableSession.objects.filter(table_number=table_num, is_active=True).update(is_active=False)
        TableCart.objects.filter(table_number=table_num).delete()
        messages.success(request, f"Table {table_num} session reset.")
    return redirect(f"{reverse('management_dashboard')}?tab=tables")

def update_table_split(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
        table_num = int(data.get("table_number"))
        state = data.get("state", {})
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"status": "error", "message": "Invalid payload"}, status=400)

    if table_num != 0:
        client_token = request.headers.get("X-Session-Token")
        if not TableSession.objects.filter(table_number=table_num, session_token=client_token, is_active=True).exists():
            return JsonResponse({"status": "error", "message": "Unauthorized session"}, status=403)

    obj, _ = TableSplitState.objects.update_or_create(
        table_number=table_num, defaults={"state_data": state}
    )
    return JsonResponse({"status": "success", "updated_at": obj.updated_at.isoformat()})


def get_table_split(request):
    table_num = request.GET.get("table")
    if not table_num:
        return JsonResponse({"status": "error", "message": "No table specified"}, status=400)
    try:
        table_int = int(table_num)
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid table format"}, status=400)

    if table_int != 0:
        client_token = request.headers.get("X-Session-Token") or request.GET.get("token")
        if not TableSession.objects.filter(table_number=table_int, session_token=client_token, is_active=True).exists():
            return JsonResponse({"status": "error", "message": "Invalid or missing session token"}, status=401)

    try:
        obj = TableSplitState.objects.get(table_number=table_int)
        return JsonResponse({"status": "success", "state": obj.state_data, "updated_at": obj.updated_at.isoformat()})
    except TableSplitState.DoesNotExist:
        return JsonResponse({"status": "success", "state": {}, "updated_at": None})
