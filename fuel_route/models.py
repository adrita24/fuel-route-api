from django.db import models

class FuelStation(models.Model):
    """
    Represents a unique commercial fuel station.
    
    Fields:
      - opis_id: Unique identifier from the OPIS dataset.
      - name: Truckstop name (e.g. WOODSHED OF BIG CABIN).
      - address: Physical street / interstate interchange address.
      - city: Municipality name.
      - state: 2-letter US state code.
      - latitude: Geocoded WGS84 latitude.
      - longitude: Geocoded WGS84 longitude.
      - retail_price: Minimum retail price per gallon ($) recorded for this station.
      - geocode_source: Tier source of coordinates (e.g. us_census_batch, osm_nominatim, us_census_gazetteer, geonames_centroid).
      - precision: Precision indicator (e.g. street_interpolated, poi_match, approximate_city).
    """
    opis_id = models.IntegerField(unique=True, db_index=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=255, help_text="Truckstop Name")
    address = models.CharField(max_length=255, help_text="Physical Address")
    city = models.CharField(max_length=100, help_text="City")
    state = models.CharField(max_length=10, help_text="2-letter US State Code")
    latitude = models.FloatField(help_text="Latitude in decimal degrees")
    longitude = models.FloatField(help_text="Longitude in decimal degrees")
    retail_price = models.DecimalField(max_digits=8, decimal_places=4, help_text="Minimum retail price per gallon ($)")
    geocode_source = models.CharField(max_length=50, help_text="Source of coordinates")
    precision = models.CharField(max_length=50, help_text="Precision classification")

    class Meta:
        db_table = 'fuel_stations'
        indexes = [
            models.Index(fields=['latitude', 'longitude'], name='station_lat_lon_idx'),
        ]
        verbose_name = 'Fuel Station'
        verbose_name_plural = 'Fuel Stations'

    def __str__(self):
        return f"[{self.opis_id}] {self.name} - {self.city}, {self.state} (${self.retail_price})"


class GeocodingCache(models.Model):
    """
    Persistent on-disk cache for forward geocoding queries via OSM Nominatim.
    Keys are normalized lowercase whitespace-collapsed query strings.
    """
    normalized_query = models.CharField(max_length=255, unique=True, db_index=True)
    latitude = models.FloatField(help_text="WGS84 latitude")
    longitude = models.FloatField(help_text="WGS84 longitude")
    display_name = models.CharField(max_length=500, help_text="Formatted address returned by geocoder")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'geocoding_cache'
        verbose_name = 'Geocoding Cache Entry'
        verbose_name_plural = 'Geocoding Cache Entries'

    def __str__(self):
        return f"'{self.normalized_query}' -> ({self.latitude:.4f}, {self.longitude:.4f})"


class RouteCache(models.Model):
    """
    Persistent on-disk cache for driving routes queried from OSRM.
    Keys are canonical strings of start/end coordinates rounded to 4 decimals (~11m).
    """
    route_key = models.CharField(max_length=120, unique=True, db_index=True)
    distance_miles = models.FloatField(help_text="Total driving distance in miles")
    duration_seconds = models.FloatField(help_text="Total estimated driving duration in seconds")
    geometry = models.JSONField(help_text="GeoJSON LineString geometry coordinates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'route_cache'
        verbose_name = 'Route Cache Entry'
        verbose_name_plural = 'Route Cache Entries'

    def __str__(self):
        return f"{self.route_key}: {self.distance_miles:.1f} mi ({self.duration_seconds/3600:.1f} hrs)"


class StationMatchCache(models.Model):
    """
    Persistent on-disk cache for candidate stations matched and projected
    along a driving route corridor.
    Key format: '{route_key}|{corridor_miles}'
    Matches: JSON list of matched station dictionaries with price stored as string.
    """
    key = models.CharField(max_length=255, unique=True, db_index=True, help_text="Cache key: route_key|corridor_miles")
    matches = models.JSONField(help_text="List of candidate stations along route corridor")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'station_match_cache'
        verbose_name = 'Station Match Cache Entry'
        verbose_name_plural = 'Station Match Cache Entries'

    def __str__(self):
        match_count = len(self.matches) if isinstance(self.matches, list) else 0
        return f"{self.key}: {match_count} candidate stations"

