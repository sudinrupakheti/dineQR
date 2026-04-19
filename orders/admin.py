from django.contrib import admin
from .models import Category, MenuItem, Order, OrderItem, Review


# 1. This allows the owner to see the items INSIDE the order detail page.
# Very important for the kitchen!
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0  # Prevents showing 3 empty rows by default
    readonly_fields = [
        "menu_item",
        "quantity",
        "notes",
    ]  # Staff shouldn't change the customer's order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "table_number", "status", "total_price", "created_at"]
    list_filter = ["status", "created_at"]  # Sidebar filters
    search_fields = ["table_number", "id"]  # Search bar
    list_editable = ["status"]  # Change status directly from the list view!
    inlines = [OrderItemInline]  # Show items inside the order


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "price", "is_available"]
    list_filter = ["category", "is_available"]
    search_fields = ["name", "description"]
    list_editable = ["price", "is_available"]  # Quick updates for "Sold Out" items


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["menu_item", "rating", "created_at"]
    readonly_fields = [
        "menu_item",
        "rating",
        "comment",
        "created_at",
    ]  # Reviews should be permanent
