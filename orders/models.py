from django.db import models
from django.utils.html import format_html
import uuid


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    image = models.ImageField(upload_to="menu_items/", blank=True, null=True)
    is_available = models.BooleanField(default=True)

    # New operational fields
    veg = models.BooleanField(default=False)
    SPICE_CHOICES = [
        ("sweet", "Sweet"),
        ("neutral", "Neutral"),
        ("mild", "Mild"),
        ("medium", "Medium"),
        ("hot", "Hot"),
    ]
    spice_level = models.CharField(
        max_length=10, choices=SPICE_CHOICES, default="neutral"
    )
    preparation_time = models.PositiveIntegerField(default=15)
    is_featured = models.BooleanField(
        default=False, verbose_name="Featured/Recommended"
    )

    def image_tag(self):
        if self.image:
            return format_html(
                '<img src="{}" style="width: 50px; height:50px; object-fit:cover; border-radius:5px;" />',
                self.image.url,
            )
        return "No Image"

    image_tag.short_description = "Preview"

    def __str__(self):
        return self.name


class Order(models.Model):
    id: int
    STATUS_CHOICES = [
        ("received", "Received"),
        ("preparing", "Preparing"),
        ("ready", "Ready"),
        ("completed", "Completed"),
    ]

    table_number = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="received")
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)  # type: ignore

    # Billing fields
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def remaining_balance(self):
        return self.total_price - self.paid_amount

    @property
    def has_review(self):
        return self.reviews.exists()  # type: ignore

    def __str__(self):
        return f"Order {self.id} - Table {self.table_number}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True, null=True)
    paid_quantity = models.PositiveIntegerField(default=0)

    @property
    def remaining_quantity(self):
        return self.quantity - self.paid_quantity

    @property
    def is_fully_paid(self):
        return self.paid_quantity >= self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.menu_item.name}"


class Review(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="reviews", null=True
    )
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    rating = models.IntegerField(default=5)
    comment = models.TextField(blank=True)
    sentiment = models.CharField(max_length=20, default="neutral")
    created_at = models.DateTimeField(auto_now_add=True)


class WaiterCall(models.Model):
    REASON_CHOICES = [
        ("water", "Need Water"),
        ("bill", "Bring Bill"),
        ("clean", "Clean Table"),
        ("help", "Need Assistance"),
        ("paid", "Payment Done"),
    ]

    table_number = models.CharField(max_length=10)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="help")
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        reason_label = getattr(self, "get_reason_display")()
        return f"Table {self.table_number} - {reason_label}"


class TableSession(models.Model):
    table_number = models.IntegerField()
    session_token = models.UUIDField(default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Table {self.table_number} - {self.session_token}"


class KitchenBroadcast(models.Model):
    message = models.TextField()
    created_at = models.DateTimeField(auto_now=True)
