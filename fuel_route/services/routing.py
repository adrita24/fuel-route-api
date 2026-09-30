"""
Routing Service for Highway Driving Directions via OSRM (Open Source Routing Machine).

Features:
  - Single OSRM route API call returning distance (miles), duration (seconds), and GeoJSON geometry
  - Persistent on-disk caching via RouteCache keyed by rounded coordinates (~11m resolution)
  - Configurable endpoint via OSRM_BASE_URL (defaults to public demo server)
  - Contiguous US boundary validation on both origin and destination coordinates
  - No negative caching (failures and errors are never cached)
  - Concurrency-safe cache insertion (handles IntegrityError races)
"""

import logging
import os
from typing import Dict, Any, Tuple

import requests
from django.db import IntegrityError

logger = logging.getLogger(__name__)

from fuel_route.models import RouteCache
from fuel_route.services.exceptions import (
    InvalidInputError,
    NonUSLocationError,
    NoRouteFoundError,
    RoutingTimeoutError,
    RoutingServiceError,
)
from fuel_route.services.geocoding import is_in_conus

DEFAULT_OSRM_BASE_URL = "https://router.project-osrm.org"
HTTP_TIMEOUT_SECONDS = 10.0
METERS_TO_MILES = 0.000621371


def make_route_key(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> str:
    """Format canonical route cache key with coordinates rounded to 4 decimal places (~11 meters)."""
    return f"{start_lat:.4f},{start_lon:.4f}->{end_lat:.4f},{end_lon:.4f}"


def get_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> Dict[str, Any]:
    """
    Query the driving route between two coordinate points.

    Returns:
      {
        'distance_miles': float,
        'duration_seconds': float,
        'geometry': dict,  # GeoJSON LineString coordinates
        'cached': bool
      }

    Raises:
      InvalidInputError: If coordinates are invalid or missing.
      NonUSLocationError: If start or finish falls outside contiguous US.
      NoRouteFoundError: If no navigable road connection exists between points.
      RoutingTimeoutError: If the routing request times out.
      RoutingServiceError: If the routing service returns an error or fails.
    """
    # 1. Validate coordinate inputs
    for name, val in [('start_lat', start_lat), ('start_lon', start_lon), ('end_lat', end_lat), ('end_lon', end_lon)]:
        if val is None or not isinstance(val, (int, float)):
            raise InvalidInputError(f"Coordinate parameter '{name}' must be a valid number.")

    start_lat, start_lon = float(start_lat), float(start_lon)
    end_lat, end_lon = float(end_lat), float(end_lon)

    # 2. Validate CONUS boundaries for both endpoints
    if not is_in_conus(start_lat, start_lon):
        raise NonUSLocationError(
            f"Start coordinate ({start_lat:.4f}, {start_lon:.4f}) is outside the contiguous United States coverage area."
        )
    if not is_in_conus(end_lat, end_lon):
        raise NonUSLocationError(
            f"Destination coordinate ({end_lat:.4f}, {end_lon:.4f}) is outside the contiguous United States coverage area."
        )

    # 3. Cache-first lookup
    route_key = make_route_key(start_lat, start_lon, end_lat, end_lon)
    cached_entry = RouteCache.objects.filter(route_key=route_key).first()
    if cached_entry:
        logger.info(f"[ROUTING CACHE HIT] Route '{route_key}' retrieved from RouteCache (0 external calls)")
        return {
            'distance_miles': cached_entry.distance_miles,
            'duration_seconds': cached_entry.duration_seconds,
            'geometry': cached_entry.geometry,
            'cached': True,
        }

    logger.info(f"[ROUTING OUTBOUND CALL] Querying OSRM for route '{route_key}'...")
    # 4. Outbound OSRM HTTP request
    base_url = os.getenv('OSRM_BASE_URL', DEFAULT_OSRM_BASE_URL).rstrip('/')
    # Note: OSRM strictly expects coordinates in longitude,latitude order!
    url = f"{base_url}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}"
    params = {
        'overview': 'full',
        'geometries': 'geojson',
        'steps': 'false',
    }

    try:
        response = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise RoutingTimeoutError(
            f"OSRM routing engine timed out after {HTTP_TIMEOUT_SECONDS}s."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RoutingServiceError(
            f"Network error communicating with OSRM routing engine: {exc}."
        ) from exc

    # 5. Handle HTTP status codes
    if response.status_code >= 500:
        raise RoutingServiceError(
            f"OSRM routing server returned an error (HTTP {response.status_code})."
        )

    try:
        data = response.json()
    except Exception as exc:
        raise RoutingServiceError("Failed to parse OSRM routing engine JSON response.") from exc

    osrm_code = data.get('code')
    if osrm_code == 'NoRoute':
        raise NoRouteFoundError(
            f"No driving route found between ({start_lat:.4f}, {start_lon:.4f}) and ({end_lat:.4f}, {end_lon:.4f})."
        )

    if osrm_code != 'Ok' or not data.get('routes'):
        raise RoutingServiceError(
            f"OSRM routing failed with status code '{osrm_code}': {data.get('message', 'No details')}."
        )

    # 6. Parse route details
    best_route = data['routes'][0]
    distance_meters = float(best_route['distance'])
    distance_miles = round(distance_meters * METERS_TO_MILES, 2)
    duration_seconds = round(float(best_route['duration']), 1)
    geometry = best_route.get('geometry', {})

    # 7. Save successful result to cache (concurrency-safe race handling)
    try:
        RouteCache.objects.get_or_create(
            route_key=route_key,
            defaults={
                'distance_miles': distance_miles,
                'duration_seconds': duration_seconds,
                'geometry': geometry,
            }
        )
    except IntegrityError:
        pass  # Another process concurrently saved this key; safe to ignore

    return {
        'distance_miles': distance_miles,
        'duration_seconds': duration_seconds,
        'geometry': geometry,
        'cached': False,
    }
