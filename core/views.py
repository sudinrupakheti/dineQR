from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Count
from .models import MenuItem, Order, OrderItem, DishRating
from datetime import datetime, timedelta


@require_http_methods(["GET", "POST"])
def admin_login(request):
    """Admin login page"""
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_staff:
            login(request, user)
            return redirect("admin_dashboard")
        else:
            return render(
                request,
                "admin/login.html",
                {"error": "Invalid credentials or not admin"},
            )

    return render(request, "admin/login.html")


@login_required(login_url="admin_login")
def admin_dashboard(request):
    """Admin dashboard with stats"""
    if not request.user.is_staff:
        return redirect("admin_login")

    today = datetime.now().date()

    # Today stats
    today_orders = Order.objects.filter(created_at__date=today)
    total_revenue = (
        today_orders.aggregate(
            total=Sum("orderitem__quantity") * Sum("orderitem__menu_item__price")
        )["total"]
        or 0
    )

    orders_count = today_orders.count()

    # Menu items
    menu_items = MenuItem.objects.all()
    available_items = menu_items.filter(is_available=True).count()

    context = {
        "today_date": today,
        "orders_count": orders_count,
        "total_revenue": total_revenue,
        "total_menu_items": menu_items.count(),
        "available_items": available_items,
        "recent_orders": today_orders.order_by("-created_at")[:5],
    }

    return render(request, "admin/dashboard.html", context)


@login_required(login_url="admin_login")
def menu_management(request):
    """Manage menu items"""
    if not request.user.is_staff:
        return redirect("admin_login")

    items = MenuItem.objects.all()

    context = {
        "menu_items": items,
    }
    return render(request, "admin/menu.html", context)


@login_required(login_url="admin_login")
def menu_item_toggle(request, item_id):
    """Toggle menu item availability"""
    if not request.user.is_staff:
        return redirect("admin_login")

    item = MenuItem.objects.get(id=item_id)
    item.is_available = not item.is_available
    item.save()

    return redirect("menu_management")


@login_required(login_url="admin_login")
def orders_view(request):
    """View all orders with status"""
    if not request.user.is_staff:
        return redirect("admin_login")

    status = request.GET.get("status", "all")

    if status == "all":
        orders = Order.objects.all()
    else:
        orders = Order.objects.filter(status=status)

    context = {
        "orders": orders.order_by("-created_at"),
        "statuses": ["received", "preparing", "ready"],
        "current_status": status,
    }
    return render(request, "admin/orders.html", context)


@login_required(login_url="admin_login")
def update_order_status(request, order_id):
    """Update order status"""
    if not request.user.is_staff:
        return redirect("admin_login")

    order = Order.objects.get(id=order_id)
    new_status = request.POST.get("status")

    if new_status in ["received", "preparing", "ready"]:
        order.status = new_status
        order.save()

    return redirect("orders_view")


@login_required(login_url="admin_login")
def analytics_view(request):
    """Analytics dashboard"""
    if not request.user.is_staff:
        return redirect("admin_login")

    # Last 7 days
    last_7_days = datetime.now().date() - timedelta(days=7)

    # Revenue by day
    revenue_data = (
        Order.objects.filter(created_at__date__gte=last_7_days)
        .values("created_at__date")
        .annotate(count=Count("id"))
        .order_by("created_at__date")
    )

    # Top dishes
    top_dishes = (
        OrderItem.objects.filter(order__created_at__date__gte=last_7_days)
        .values("menu_item__name")
        .annotate(sold=Count("id"), revenue=Sum("menu_item__price") * Count("id"))
        .order_by("-sold")[:5]
    )

    # Ratings
    avg_rating = (
        DishRating.objects.filter(created_at__date__gte=last_7_days).aggregate(
            avg=Sum("score") / Count("id")
        )["avg"]
        or 0
    )

    context = {
        "revenue_data": revenue_data,
        "top_dishes": top_dishes,
        "avg_rating": round(avg_rating, 2),
        "total_ratings": DishRating.objects.filter(
            created_at__date__gte=last_7_days
        ).count(),
    }

    return render(request, "admin/analytics.html", context)


def admin_logout(request):
    """Logout admin"""
    logout(request)
    return redirect("admin_login")
