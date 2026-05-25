from django.contrib import admin
from .models import Category, MenuItem, Order, OrderItem, Review


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = [
        "menu_item",
        "quantity",
        "notes",
    ]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "table_number", "status", "total_price", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["table_number", "id"]
    list_editable = ["status"]
    inlines = [OrderItemInline]

    def total_price(self, obj):
        return f"Rs. {obj.total_price}"

    total_price.short_description = "Price"


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ["image_tag", "name", "category", "price", "is_available"]
    list_filter = ["category", "is_available"]
    search_fields = ["name", "description"]
    list_editable = ["price", "is_available"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["menu_item", "rating", "sentiment", "created_at"]
    list_filter = ["sentiment", "rating"]
