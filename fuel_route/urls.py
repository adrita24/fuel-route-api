"""
URL patterns for the fuel_route application.
"""

from django.urls import path
from fuel_route.views import RoutePlanView

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
]
