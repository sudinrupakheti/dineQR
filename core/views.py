from django.shortcuts import render, redirect, get_object_or_404
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

@login_required(login_url="admin_login")
def menu_item_add(request):
    """Add a new menu item"""
    if not request.user.is_staff:
        return redirect("admin_login")

    if request.method == "POST":
        name = request.POST.get("name")
        description = request.POST.get("description", "")
        price = request.POST.get("price")
        category = request.POST.get("category", "main")
        photo = request.FILES.get("photo")

        item = MenuItem(
            name=name,
            description=description,
            price=price,
            category=category,
        )
        if photo:
            item.photo = photo
        item.save()
        return redirect("menu_management")

    categories = MenuItem.CATEGORY_CHOICES
    return render(request, "admin/menu_add.html", {"categories": categories})


@login_required(login_url="admin_login")
def menu_item_edit(request, item_id):
    """Edit an existing menu item"""
    if not request.user.is_staff:
        return redirect("admin_login")

    item = get_object_or_404(MenuItem, id=item_id)

    if request.method == "POST":
        item.name = request.POST.get("name")
        item.description = request.POST.get("description", "")
        item.price = request.POST.get("price")
        item.category = request.POST.get("category", "main")
        photo = request.FILES.get("photo")
        if photo:
            item.photo = photo
        item.save()
        return redirect("menu_management")

    categories = MenuItem.CATEGORY_CHOICES
    return render(request, "admin/menu_edit.html", {"item": item, "categories": categories})


@login_required(login_url="admin_login")
def menu_item_delete(request, item_id):
    """Delete a menu item"""
    if not request.user.is_staff:
        return redirect("admin_login")

    item = get_object_or_404(MenuItem, id=item_id)
    if request.method == "POST":
        item.delete()
        return redirect("menu_management")
    return render(request, "admin/menu_confirm_delete.html", {"item": item})


def customer_menu(request):
    """Public menu page for customers"""
    table_number = request.GET.get("table", "")
    categories = MenuItem.CATEGORY_CHOICES
    menu_by_category = {}

    for cat_key, cat_label in categories:
        items = MenuItem.objects.filter(category=cat_key, is_available=True)
        if items.exists():
            menu_by_category[cat_label] = items

    return render(request, "admin/customer_menu.html", {
        "menu_by_category": menu_by_category,
        "table_number": table_number,
    })

def admin_logout(request):
    """Logout admin"""
    logout(request)
    return redirect("admin_login")

import qrcode
import io
import base64
@login_required(login_url="admin_login")
def qr_code_view(request):
    """Generate QR code for the restaurant menu"""
    if not request.user.is_staff:
        return redirect("admin_login")

    # Build the full URL that the QR code will point to
    base_url = request.build_absolute_uri('/menu/view/').replace('127.0.0.1', request.META.get('HTTP_HOST', '127.0.0.1').split(':')[0])
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(base_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert image to base64 so we can embed it in HTML
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return render(request, "admin/qr_code.html", {
        "qr_image": img_base64,
        "menu_url": base_url,
    })