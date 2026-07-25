from django.contrib import admin  # type: ignore
from .models import (
    Category,
    MenuItem,
    Order,
    OrderItem,
    Review,
    WaiterCall,
    TableSession,
    KitchenBroadcast,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "loyalty_points")
    search_fields = ("user__username", "user__email")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("id", "image_tag", "name", "category", "price", "is_available", "is_featured")
    list_filter = ("category", "is_available", "is_featured", "spice_level")
    search_fields = ("name", "description")
    readonly_fields = ("image_tag",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "table_number", "status", "total_price", "discount_amount", "is_paid", "created_at")
    list_filter = ("status", "is_paid", "created_at")
    search_fields = ("id", "table_number", "user__username")
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
    list_display = ("table_number", "host_name", "session_passcode", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("table_number", "host_name")


admin.site.register(KitchenBroadcast)
