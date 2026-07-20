# orders/admin.py

from django.contrib import admin    #type: ignore
from .models import Category, MenuItem, Order, OrderItem, Review, WaiterCall, TableSession, KitchenBroadcast

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("id", "image_tag", "name", "category", "price", "is_available", "is_featured")
    list_filter = ("category", "is_available", "is_featured", "spice_level")
    search_fields = ("name", "description")
    readonly_fields = ("image_tag",)  # Displays a thumbnail preview in the admin panel


class OrderItemInline(admin.TabularInline):
    """Allows managing items directly inside the Order detail screen"""
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "table_number", "status", "total_price", "is_paid", "created_at")
    list_filter = ("status", "is_paid", "created_at")
    search_fields = ("id", "table_number")
    inlines = [OrderItemInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "menu_item", "rating", "sentiment", "created_at")
    list_filter = ("rating", "sentiment", "created_at")
    search_fields = ("comment",)


@admin.register(WaiterCall)
class WaiterCallAdmin(admin.ModelAdmin):
    list_display = ("id", "table_number", "reason", "is_resolved", "created_at")
    list_filter = ("reason", "is_resolved", "created_at")
    search_fields = ("table_number",)


@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ("table_number", "session_token", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("table_number",)


admin.site.register(KitchenBroadcast)
