import json
import difflib
import re
import qrcode
import io
import base64
from decimal import Decimal
from datetime import datetime, timedelta
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.db.models import (
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
from django.db.models.functions import ExtractWeekDay
from django.contrib.auth.decorators import user_passes_test
from django.conf import settings
from collections import defaultdict
from .ai_utils import analyze_note_sentiment
from collections import Counter, defaultdict
from itertools import combinations
from .models import (
    Order,
    OrderItem,
    MenuItem,
    Category,
    Review,
    WaiterCall,
    TableSession,
    KitchenBroadcast,
)


def is_owner(user):
    return user.groups.filter(name="Owner").exists() or user.is_superuser


def is_staff(user):
    return user.groups.filter(name="Staff").exists() or user.is_superuser


SEARCH_SYNONYMS = {
    "momo": ["mo:mo", "momos", "dumplings", "dumpling"],
    "mo:mo": ["momo", "momos", "dumplings", "dumpling"],
    "sweet": [
        "dessert",
        "desserts",
        "sweets",
        "pudding",
        "ice cream",
        "cake",
        "pastry",
    ],
    "dessert": ["sweet", "sweets", "desserts", "pudding", "ice cream", "cake"],
    "drink": [
        "beverage",
        "beverages",
        "drinks",
        "soda",
        "juice",
        "coke",
        "cold drink",
        "water",
    ],
    "beverage": ["drink", "drinks", "beverages", "soda", "juice", "cold drink"],
    "chowmein": ["chow mein", "noodles", "noodle"],
    "noodle": ["chowmein", "chow mein", "noodles"],
    "burger": ["burgers", "hamburger", "buns"],
}


def expand_search_query(raw_query):
    """Takes a raw query and returns a list of synonymous terms."""
    expanded_terms = set([raw_query])
    words = raw_query.split()

    for word in words:
        # Check if the word is a key or a value in our dictionary
        for root_term, related_terms in SEARCH_SYNONYMS.items():
            if word == root_term or word in related_terms:
                expanded_terms.add(root_term)
                expanded_terms.update(related_terms)

    return list(expanded_terms)


def menu_view(request):
    query = request.GET.get("search", "").lower().strip()

    # Base querysets - default to only showing available items to customers
    items = MenuItem.objects.filter(is_available=True)
    categories = Category.objects.all()
    recommended_items = None  # Explicit container for fallback recommendations
    zero_results = False

    if query:
        # 1. Intent Detection
        is_veg = "veg" in query and "non" not in query
        is_spicy = any(w in query for w in ["spicy", "hot", "chili", "spice"])
        is_mild = any(w in query for w in ["mild", "not spicy", "not hot"])
        is_featured = "featured" in query or "special" in query

        # Tokenize query string into clean alphanumeric lowercase words
        words = re.findall(r"[a-z0-9:]+", query)

        intent_keywords = {
            "veg",
            "spicy",
            "hot",
            "chili",
            "spice",
            "mild",
            "not",
            "featured",
            "special",
        }
        is_pure_intent = (
            all(word in intent_keywords for word in words) if words else False
        )

        if not is_pure_intent:
            # 2. Synonym Expansion
            search_terms = set([query])
            for word in words:
                search_terms.add(word)
                if word in SEARCH_SYNONYMS:
                    search_terms.update(SEARCH_SYNONYMS[word])

            # 3. Optimized Fuzzy Word Matching
            all_item_words = set()
            for name in MenuItem.objects.filter(is_available=True).values_list(
                "name", flat=True
            ):
                all_item_words.update(re.findall(r"[a-z0-9:]+", name.lower()))

            all_cat_words = set()
            for name in Category.objects.values_list("name", flat=True):
                all_cat_words.update(re.findall(r"[a-z0-9:]+", name.lower()))

            fuzzy_matches = []
            for word in words:
                fuzzy_matches.extend(
                    difflib.get_close_matches(
                        word, list(all_item_words), n=2, cutoff=0.6
                    )
                )
                fuzzy_matches.extend(
                    difflib.get_close_matches(
                        word, list(all_cat_words), n=2, cutoff=0.6
                    )
                )

            search_terms.update([match.lower() for match in fuzzy_matches])

            # 4. Text Index Lookup Execution
            lookup = Q()
            for term in search_terms:
                lookup |= Q(name__icontains=term)
                lookup |= Q(description__icontains=term)
                lookup |= Q(category__name__icontains=term)

            items = items.filter(lookup)

        # 5. Intent Intersecting Filters
        if is_spicy:
            items = items.filter(spice_level__in=["medium", "hot"])
        if is_mild:
            items = items.filter(spice_level="mild")
        if is_featured:
            items = items.filter(is_featured=True)
        if is_veg:
            items = items.filter(veg=True)

        # 6. Check if search found nothing
        if not items.exists():
            zero_results = True
            # Safely build recommendation slices completely separate from standard items
            recommended_items = MenuItem.objects.filter(
                is_available=True, is_featured=True
            )[:6]
            items = MenuItem.objects.none()
            categories = (
                Category.objects.none()
            )  # Hides sticky category headers when empty
        else:
            # Advanced Scoring Metric Sorting
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

    # 7. Safe Category Sticky-Bar Prefetch (Only runs when results exist)
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

    # Feature 1: Get the top 5 highest-selling item IDs to light up the "TRENDING" UI badge
    popular_ids = list(
        OrderItem.objects.filter(order__is_paid=True)
        .values("menu_item_id")
        .annotate(total_sold=Sum("quantity"))
        .order_by("-total_sold")
        .values_list("menu_item_id", flat=True)[:5]
    )

    # Feature 2: Market Basket Analysis (Frequent Companions)
    historical_orders = OrderItem.objects.filter(order__is_paid=True).values(
        "order_id", "menu_item_id"
    )
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
            # CHANGE: Filter companions to only keep pairings ordered 5 times or more
            valid_companions = {k: v for k, v in companions.items() if v >= 5}
            if valid_companions:
                top_companion_map[item_id] = max(
                    valid_companions, key=valid_companions.get
                )

    # Convert queryset to a list so we can dynamically attach the companion object
    items_list = list(items)
    for item in items_list:
        comp_id = top_companion_map.get(item.id)
        if comp_id:
            try:
                item.frequent_companion = MenuItem.objects.get(
                    id=comp_id, is_available=True
                )
            except MenuItem.DoesNotExist:
                item.frequent_companion = None
        else:
            item.frequent_companion = None

    items = items_list

    # ==========================================================
    # 9. CONTEXT-AWARE GREETING ENGINE
    # ==========================================================
    current_hour = timezone.localtime(timezone.now()).hour
    if 5 <= current_hour < 12:
        greeting = "Good Morning ☕"
    elif 12 <= current_hour < 17:
        greeting = "Good Afternoon 🍛"
    elif 17 <= current_hour < 22:
        greeting = "Good Evening 🍽️"
    else:
        greeting = "Late Night Cravings? 🌙"
    # ==========================================================

    context = {
        "items": items,
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

    # ADDED: Get popular item recommendations for the Cart page
    popular_item_ids = (
        OrderItem.objects.filter(order__is_paid=True)
        .values("menu_item_id")
        .annotate(total_sold=Sum("quantity"))
        .order_by("-total_sold")
        .values_list("menu_item_id", flat=True)[:4]
    )

    popular_items = MenuItem.objects.filter(id__in=popular_item_ids, is_available=True)
    if not popular_items.exists():
        popular_items = MenuItem.objects.filter(is_available=True, is_featured=True)[:4]

    return render(
        request,
        "orders/cart_detail.html",
        {
            "previous_orders": previous_orders,
            "running_total": running_total,
            "any_ready": any_ready,
            "show_thanks": show_thanks,
            "qr_code": qr_code,
            "popular_items": popular_items,  # Sent to template context
        },
    )


def place_order(request):
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Method not allowed"}, status=405
        )

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

    except MenuItem.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Menu item not found"}, status=404
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Malformed JSON payload"}, status=400
        )
    except Exception as e:
        print(f"Order Error: {e}")
        return JsonResponse(
            {"status": "error", "message": "Internal server error"}, status=500
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
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Method not allowed"}, status=405
        )

    try:
        item = OrderItem.objects.get(id=item_id, order__status="received")
        order = item.order

        item_price_total = Decimal(str(item.menu_item.price)) * item.quantity
        item.delete()

        order.total_price -= item_price_total
        if order.total_price <= 0 or order.items.count() == 0:
            order.delete()
        else:
            order.save()
        return JsonResponse({"status": "success"})

    except OrderItem.DoesNotExist:
        # FIX: Return a clean 404 instead of a misleading 405 Method Not Allowed
        return JsonResponse(
            {"status": "error", "message": "Item not found or already being prepared"},
            status=404,
        )


@user_passes_test(is_staff)
def management_dashboard(request):

    current_tab = request.GET.get("tab", "tables")
    sentiment_filter = request.GET.get("sentiment", "all")

    # --- 1. GLOBAL STATS (For all tabs) ---
    all_active_orders = Order.objects.exclude(status="completed")
    total_live_revenue = (
        all_active_orders.aggregate(Sum("total_price"))["total_price__sum"] or 0
    )
    busy_tables_count = all_active_orders.values("table_number").distinct().count()

    # --- INITIALIZE EMPTY VARIABLES ---
    table_data = []
    insights_data = {}
    recent_reviews = []
    context = {}

    # --- 2. LOGIC FOR TABLES TAB ---
    if current_tab in ["tables", "qr"]:
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

    # --- 3. LOGIC FOR INSIGHTS TAB (REAL-TIME TODAY ONLY) ---
    elif current_tab == "insights":
        # A. Core Metrics & Inventory Performance
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

        # B. Dietary Segmentation Share
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

        # C. Category Performance Pillars
        category_shares = (
            OrderItem.objects.filter(order__status="completed")
            .values("menu_item__category__name")
            .annotate(total_qty=Sum("quantity"))
            .order_by("-total_qty")
        )

        # D. Sentiment Index Metrics
        sentiment_counts = Review.objects.values("sentiment").annotate(
            count=Count("id")
        )
        sentiment_dict = {item["sentiment"]: item["count"] for item in sentiment_counts}
        total_reviews = sum(sentiment_dict.values()) or 1
        sentiment_ratios = {
            "positive": round(
                (sentiment_dict.get("positive", 0) / total_reviews) * 100, 1
            ),
            "neutral": round(
                (sentiment_dict.get("neutral", 0) / total_reviews) * 100, 1
            ),
            "negative": round(
                (sentiment_dict.get("negative", 0) / total_reviews) * 100, 1
            ),
        }

        # E. Operational Waiter Assist Telemetry
        waiter_telemetry = (
            WaiterCall.objects.values("reason")
            .annotate(total_calls=Count("id"))
            .order_by("-total_calls")
        )
        formatted_waiter_calls = [
            {
                "reason": dict(WaiterCall.REASON_CHOICES).get(
                    item["reason"], item["reason"]
                ),
                "count": item["total_calls"],
            }
            for item in waiter_telemetry
        ]

        # F. Market Basket Analysis
        order_item_groups = OrderItem.objects.values("order_id", "menu_item__name")
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

        # G. Table Load Performance
        table_revenue = (
            Order.objects.filter(status="completed")
            .values("table_number")
            .annotate(total_earned=Sum("total_price"), total_tickets=Count("id"))
            .order_by("-total_earned")[:5]
        )

        # H. Busiest Days Matrix (Trailing 30 Days)
        days_map = {
            1: "Sun",
            2: "Mon",
            3: "Tue",
            4: "Wed",
            5: "Thu",
            6: "Fri",
            7: "Sat",
        }
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

        # I. Operational Bill Settlement Ratio
        payment_audit = Order.objects.aggregate(
            collected=Count("id", filter=Q(is_paid=True)),
            unsettled=Count("id", filter=Q(is_paid=False)),
        )

        # Service Latency Vector (Table Turnaround Velocity)
        timed_orders = (
            Order.objects.filter(
                status="completed", is_paid=True, paid_at__isnull=False
            )
            .annotate(
                duration=ExpressionWrapper(
                    F("paid_at") - F("created_at"), output_field=DurationField()
                )
            )
            .aggregate(avg_time=Avg("duration"))
        )

        avg_turnaround_mins = 0
        if timed_orders["avg_time"]:
            avg_turnaround_mins = round(
                timed_orders["avg_time"].total_seconds() / 60, 1
            )

        # Financial Leakage Metrics (Revenue Bleed)
        financial_bleed = Order.objects.filter(status="canceled").aggregate(
            lost_cash=Sum("total_price"), lost_count=Count("id")
        )

        # Recipe Quality Risk Index (Toxic Items causing negative sentiment reviews)
        negative_review_order_ids = Review.objects.filter(
            sentiment="negative"
        ).values_list("order_id", flat=True)
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

        # 🌟 NEW FORCED TIME WINDOW: From midnight local time to exactly right now
        now_local = timezone.localtime(timezone.now())
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        shift_orders = Order.objects.filter(
            status="completed", created_at__range=(start_of_day, timezone.now())
        )
        z_metrics = shift_orders.aggregate(
            gross=Sum("total_price"), count=Count("id"), avg_spend=Avg("total_price")
        )
        canceled_count = Order.objects.filter(
            status="canceled", created_at__range=(start_of_day, timezone.now())
        ).count()

        context.update(
            {
                "insights": insights_data,
                "z_gross_sales": z_metrics["gross"] or 0,
                "z_ticket_count": z_metrics["count"] or 0,
                "z_avg_ticket": round(z_metrics["avg_spend"] or 0, 2)
                if z_metrics["avg_spend"]
                else 0,
                "z_canceled_count": canceled_count,
            }
        )

    # --- 4. LOGIC FOR REVIEWS TAB ---
    elif current_tab == "reviews":
        recent_reviews = Review.objects.all().order_by("-created_at")

        if sentiment_filter in ["positive", "neutral", "negative"]:
            recent_reviews = recent_reviews.filter(sentiment=sentiment_filter)

        recent_reviews = recent_reviews[:20]

    categories = Category.objects.prefetch_related("items").all()

    context = {
        "tables": table_data,
        "categories": categories,
        "current_tab": current_tab,
        "total_live_revenue": total_live_revenue,
        "busy_tables_count": busy_tables_count,
        "insights": insights_data,
        "recent_reviews": recent_reviews,
        "current_sentiment": sentiment_filter,
    }

    return render(request, "orders/management_dashboard.html", context)


def order_review_page(request, order_id):
    try:
        current_order = Order.objects.get(id=order_id)
        # Fetch all orders for this specific table that are active or recently filled
        orders_to_review = Order.objects.filter(
            table_number=current_order.table_number,
            status__in=["received", "cooking", "ready", "completed"],
        ).prefetch_related("items__menu_item")

    except Order.DoesNotExist:
        return redirect("menu")

    if request.method == "POST":
        # Process reviews inside a loop for items across all retrieved orders
        for order in orders_to_review:
            for item in order.items.all():
                rating_val = request.POST.get(f"rating_{item.menu_item.id}")
                comment_val = request.POST.get(
                    f"comment_{item.menu_item.id}", ""
                ).strip()
                if rating_val:
                    Review.objects.create(
                        order=order,
                        menu_item=item.menu_item,
                        rating=int(rating_val),
                        comment=comment_val,
                        sentiment=analyze_note_sentiment(comment_val)
                        if comment_val
                        else "neutral",
                    )
        return redirect(f"{reverse('menu')}?table={current_order.table_number}")

    # Gather unique menu items from all current session orders to present in template
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

    # Grab the single newest active broadcast notice if it exists
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
    if not (is_owner(request.user) or is_staff(request.user)):
        return redirect("menu")

    try:
        item = MenuItem.objects.get(id=item_id)
        item.is_available = not item.is_available
        item.save()
    except MenuItem.DoesNotExist:
        pass

    # FIX: Clean parameter mapping prevents duplicate "?tab=menu?tab=menu" strings
    return redirect(f"{reverse('management_dashboard')}?tab=menu")


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
        payment_method = data.get("payment_method", "qr")  # Track payment source
    except:
        manual_amount = Decimal("0")
        items_to_pay = []
        payment_method = "qr"

    # --- CASH MODE FLOW ---
    if payment_method == "cash":
        # Create a waiter notification beacon for manual desk clearance
        WaiterCall.objects.create(
            table_number=table_num, reason="paid", is_resolved=False
        )
        # Keep table_cleared=False so the client stays on screen until staff verifies from dashboard
        return JsonResponse(
            {
                "status": "success",
                "table_cleared": False,
                "message": "Waiter is on the way with the bill.",
            }
        )

    # --- QR DEMO FLOW (AUTO VERIFY) ---
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


def get_contextual_recommendations(current_cart_item_ids=None):
    """
    Returns up to 3 smart item recommendations.
    If the cart is empty, it serves highly-rated featured dishes.
    If the cart contains items, it serves popular complements from different categories.
    """
    if not current_cart_item_ids:
        return MenuItem.objects.filter(is_available=True, is_featured=True)[:3]

    # Find matching orders containing these items to track companion selections
    related_order_ids = (
        OrderItem.objects.filter(menu_item_id__in=current_cart_item_ids)
        .values_list("order_id", flat=True)
        .distinct()
    )

    # Recommend common accompaniments that aren't already in the current cart
    recommended_items = (
        MenuItem.objects.filter(
            orderitem__order_id__in=related_order_ids, is_available=True
        )
        .exclude(id__in=current_cart_item_ids)
        .annotate(order_count=Count("orderitem"))
        .order_by("-order_count")[:3]
    )

    if not recommended_items.exists():
        # Fallback to general favorites if pairing history is sparse
        recommended_items = MenuItem.objects.filter(is_available=True).exclude(
            id__in=current_cart_item_ids
        )[:3]

    return recommended_items


def generate_split_qr_api(request):
    table_num = request.GET.get("table")
    amount = request.GET.get("amount", "0.00")

    active_orders = Order.objects.filter(table_number=table_num).exclude(
        status="completed"
    )
    first_order = active_orders.first()
    order_id = first_order.id if first_order else "000"
    local_time = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")

    # Generate QR targeting the specific split portion amount
    qr_base64 = generate_bill_qr(
        {
            "amount": f"{float(amount):,.2f}",
            "order_id": order_id,
            "table_number": table_num,
            "timestamp": local_time,
        }
    )
    return JsonResponse({"qr_code": qr_base64})


@user_passes_test(is_staff)
def serve_table_qr(request, table_num):
    # 1. Dynamic Local IP detection matching your root domain routing path
    host_address = request.build_absolute_uri("/")
    target_url = f"{host_address}?table={table_num}"

    # 2. Configure High Error Correction (Handles restaurant wear-and-tear)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    # 3. Draw image and stream directly from RAM memory
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


@user_passes_test(is_staff)
def update_kitchen_broadcast(request):
    if request.method == "POST":
        new_message = request.POST.get("message", "").strip()

        # Clear out any old broadcast messages so the kitchen only sees the newest one
        KitchenBroadcast.objects.all().delete()

        if new_message:
            KitchenBroadcast.objects.create(message=new_message)

    return redirect(request.META.get("HTTP_REFERER", "management_dashboard"))
