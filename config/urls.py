"""URL configuration for the Fuel Route Optimization service."""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('fuel_route.urls')),
]
