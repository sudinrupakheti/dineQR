from django.urls import path
from . import views

urlpatterns = [
    path('view/', views.customer_menu, name='customer_menu'),
]