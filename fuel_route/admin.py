from django.contrib import admin
from .models import FuelStation, GeocodingCache, RouteCache, StationMatchCache

@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('opis_id', 'name', 'city', 'state', 'retail_price', 'precision', 'geocode_source')
    search_fields = ('opis_id', 'name', 'city', 'state', 'address')
    list_filter = ('state', 'precision', 'geocode_source')

@admin.register(GeocodingCache)
class GeocodingCacheAdmin(admin.ModelAdmin):
    list_display = ('normalized_query', 'latitude', 'longitude', 'created_at')
    search_fields = ('normalized_query', 'display_name')

@admin.register(RouteCache)
class RouteCacheAdmin(admin.ModelAdmin):
    list_display = ('route_key', 'distance_miles', 'duration_seconds', 'created_at')
    search_fields = ('route_key',)

@admin.register(StationMatchCache)
class StationMatchCacheAdmin(admin.ModelAdmin):
    list_display = ('key', 'created_at')
    search_fields = ('key',)

