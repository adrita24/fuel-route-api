"""
Route Planning & Fuel Optimization Orchestrator Service.
Coordinates geocoding, OSRM routing, corridor station matching, and fuel stop optimization.
"""

import logging
from decimal import Decimal
from typing import Dict, Any, List

from django.conf import settings
from django.db import IntegrityError

from fuel_route.models import StationMatchCache
from fuel_route.services.geocoding import geocode
from fuel_route.services.routing import get_route, make_route_key
from fuel_route.services.stations import get_candidate_stations_along_route
from fuel_route.services.optimizer import optimize_fuel_stops

logger = logging.getLogger(__name__)


def get_candidate_stations_with_cache(
    route_key: str,
    route_geometry: Dict[str, Any],
    osrm_distance_miles: float,
    corridor_miles: float = 10.0
) -> List[Dict[str, Any]]:
    """
    Retrieve candidate stations along a route corridor, using StationMatchCache to
    avoid expensive Shapely STRtree spatial projection on repeated identical routes.
    """
    cache_key = f"{route_key}|{corridor_miles}"

    # 1. Cache-first lookup
    cached_entry = StationMatchCache.objects.filter(key=cache_key).first()
    if cached_entry:
        logger.info(f"[STATION MATCH CACHE HIT] Candidate stations for '{cache_key}' retrieved from StationMatchCache (0 spatial queries)")
        stations = []
        for s in cached_entry.matches:
            st = dict(s)
            st['retail_price'] = Decimal(str(st['retail_price']))
            stations.append(st)
        return stations

    logger.info(f"[STATION MATCH CACHE MISS] Computing spatial corridor matching for '{cache_key}'...")
    # 2. Run spatial matching
    matched = get_candidate_stations_along_route(
        route_geometry=route_geometry,
        osrm_distance_miles=osrm_distance_miles,
        corridor_miles=corridor_miles
    )

    # 3. Store in cache (only if valid stations found; do not cache failures or errors)
    if matched:
        serializable_matches = []
        for s in matched:
            st = dict(s)
            st['retail_price'] = str(st['retail_price'])
            serializable_matches.append(st)

        try:
            StationMatchCache.objects.get_or_create(
                key=cache_key,
                defaults={'matches': serializable_matches}
            )
        except IntegrityError:
            pass  # Concurrency-safe: another worker inserted simultaneously

    return matched


def plan_fuel_route(start_query: str, finish_query: str) -> Dict[str, Any]:
    """
    Execute the end-to-end fuel route optimization pipeline:
      1. Forward geocode start and finish locations (OSM Nominatim)
      2. Fetch highway driving route and geometry (OSRM)
      3. Discover and project fuel stations within the route corridor (Shapely + SQL)
      4. Compute minimum-cost fuel stops (Greedy Lookahead Optimizer)
      5. Assemble structured response

    Returns:
      {
        'route': {
          'start': str,
          'finish': str,
          'distance_miles': float,
          'duration_seconds': float,
          'duration_formatted': str,
          'geometry': dict  # GeoJSON LineString
        },
        'fuel_summary': {
          'total_gallons': float,
          'total_fuel_cost': float,
          'stops_count': int,
          'vehicle': {...}
        },
        'fuel_stops': [
          {
            'stop_number': int,
            'opis_id': int,
            'name': str,
            'address': str,
            'city': str,
            'state': str,
            'latitude': float,
            'longitude': float,
            'precision': str,
            'geocode_source': str,
            'distance_from_start_miles': float,
            'gallons_pumped': float,
            'price_per_gallon': float,
            'cost': float
          }, ...
        ]
      }
    """
    # 1. Forward Geocoding
    start_geo = geocode(start_query)
    finish_geo = geocode(finish_query)

    # 2. Highway Routing
    route_data = get_route(
        start_lat=start_geo['latitude'],
        start_lon=start_geo['longitude'],
        end_lat=finish_geo['latitude'],
        end_lon=finish_geo['longitude']
    )

    # 3. Corridor Station Matching
    route_key = make_route_key(
        start_geo['latitude'], start_geo['longitude'],
        finish_geo['latitude'], finish_geo['longitude']
    )
    corridor_miles = getattr(settings, 'ROUTE_CORRIDOR_MILES', 10.0)
    candidate_stations = get_candidate_stations_with_cache(
        route_key=route_key,
        route_geometry=route_data['geometry'],
        osrm_distance_miles=route_data['distance_miles'],
        corridor_miles=corridor_miles
    )

    # 4. Fuel Stop Optimization
    fuel_stops, fuel_summary = optimize_fuel_stops(
        total_route_miles=route_data['distance_miles'],
        candidate_stations=candidate_stations
    )

    # 5. Format human-friendly duration
    duration_secs = route_data['duration_seconds']
    hours = int(duration_secs // 3600)
    minutes = int((duration_secs % 3600) // 60)
    duration_formatted = f"{hours}h {minutes:02d}m"

    return {
        'route': {
            'start': start_geo['display_name'],
            'finish': finish_geo['display_name'],
            'distance_miles': route_data['distance_miles'],
            'duration_seconds': route_data['duration_seconds'],
            'duration_formatted': duration_formatted,
            'geometry': route_data['geometry'],
        },
        'fuel_summary': fuel_summary,
        'fuel_stops': fuel_stops,
    }
