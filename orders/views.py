from django.shortcuts import render
from .models import MenuItem, Category


def menu_view(request):
    items = MenuItem.objects.filter(is_available=True)
    categories = Category.objects.all()

    context = {
        "items": items,
        "categories": categories,
    }
    return render(request, "orders/menu.html", context)
