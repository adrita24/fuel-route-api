"""
Geocoding Service for Forward Geocoding via OpenStreetMap Nominatim.

Features:
  - Country-restricted querying (countrycodes=us)
  - Contiguous United States (CONUS) bounding-box validation derived from Census Gazetteer
  - Persistent on-disk caching via GeocodingCache (cache-first)
  - Thread-safe in-process rate limiter (>= 1.05s gap between outgoing requests)
  - No auto-retries that could hammer upstream services
  - No negative caching (failures and errors are never cached)
  - Concurrency-safe cache insertion (handles IntegrityError races)
  - Strict contact email enforcement for User-Agent compliance
"""

import logging
import os
import re
import time
import threading
from typing import Dict, Any, Tuple

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError

logger = logging.getLogger(__name__)

from fuel_route.models import GeocodingCache
from fuel_route.services.exceptions import (
    InvalidInputError,
    LocationNotFoundError,
    NonUSLocationError,
    GeocoderTimeoutError,
    GeocoderRateLimitError,
    GeocoderServiceError,
)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
HTTP_TIMEOUT_SECONDS = 5.0
MIN_REQUEST_INTERVAL_SECONDS = 1.05

# Contiguous United States (CONUS) bounding box derived from 31,523 CONUS places in
# the 2024 US Census Bureau Gazetteer (2024_Gaz_place_national.txt, excluding AK, HI, PR, VI, GU, AS, MP):
#   - Raw Min Latitude:  24.563990° (Key West, FL)      -> padded south by 0.564° to 24.0°
#   - Raw Max Latitude:  49.347409° (NW Angle, MN)      -> padded north by 0.653° to 50.0°
#   - Raw Min Longitude: -124.611559° (Cape Alava, WA)  -> padded west by 0.388° to -125.0°
#   - Raw Max Longitude: -66.989856° (West Quoddy, ME)  -> padded east by 0.490° to -66.5°
# Padding (~25-40 miles) ensures coastal highways, islands, peninsulas, and border stations are fully covered.
CONUS_MIN_LAT = 24.0
CONUS_MAX_LAT = 50.0
CONUS_MIN_LON = -125.0
CONUS_MAX_LON = -66.5

_rate_limit_lock = threading.Lock()
_last_request_timestamp = 0.0


def is_in_conus(latitude: float, longitude: float) -> bool:
    """Return True if coordinates fall within the contiguous United States bounding box."""
    return (
        CONUS_MIN_LAT <= latitude <= CONUS_MAX_LAT
        and CONUS_MIN_LON <= longitude <= CONUS_MAX_LON
    )


def normalize_query(query: str) -> str:
    """Normalize query by stripping whitespace, collapsing multiple spaces, and lowercasing."""
    if not query:
        return ""
    cleaned = re.sub(r'\s+', ' ', query.strip())
    return cleaned.lower()


def _get_user_agent() -> str:
    """Retrieve and validate the contact email for the Nominatim User-Agent."""
    email = os.getenv('GEOCODER_CONTACT_EMAIL')
    if not email or not email.strip():
        raise ImproperlyConfigured(
            "GEOCODER_CONTACT_EMAIL is not set in the environment or .env. "
            "A valid, real contact email is strictly required by OpenStreetMap Nominatim's Acceptable Use Policy."
        )
    return f"SpotterFuelRouteOptimizer/1.0 (contact: {email.strip()})"


def _enforce_rate_limit() -> None:
    """Thread-safe rate limiter ensuring at least 1.05s between successive outbound requests."""
    global _last_request_timestamp
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_timestamp
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        _last_request_timestamp = time.time()


def geocode(query: str) -> Dict[str, Any]:
    """
    Forward geocode a location string into coordinates and formatted display name.

    Returns:
      {
        'latitude': float,
        'longitude': float,
        'display_name': str,
        'cached': bool
      }

    Raises:
      InvalidInputError: If query is missing or whitespace-only.
      LocationNotFoundError: If geocoder returns 0 matches.
      NonUSLocationError: If result is outside the contiguous US.
      GeocoderTimeoutError: If request times out.
      GeocoderRateLimitError: If HTTP 429 received.
      GeocoderServiceError: If HTTP 5xx or unhandled network failure occurs.
    """
    if not query or not query.strip():
        raise InvalidInputError("Location query cannot be empty.")

    cleaned_query = re.sub(r'\s+', ' ', query.strip())
    cache_key = normalize_query(cleaned_query)

    # 1. Cache-first lookup
    cached_entry = GeocodingCache.objects.filter(normalized_query=cache_key).first()
    if cached_entry:
        logger.info(f"[GEOCODE CACHE HIT] '{cleaned_query}' retrieved from GeocodingCache (0 external calls)")
        return {
            'latitude': cached_entry.latitude,
            'longitude': cached_entry.longitude,
            'display_name': cached_entry.display_name,
            'cached': True,
        }

    logger.info(f"[GEOCODE OUTBOUND CALL] Querying Nominatim for '{cleaned_query}'...")
    # 2. Prepare outbound HTTP request
    user_agent = _get_user_agent()
    params = {
        'q': cleaned_query,
        'format': 'jsonv2',
        'countrycodes': 'us',
        'limit': 1,
        'addressdetails': 1,
    }
    headers = {
        'User-Agent': user_agent,
    }

    _enforce_rate_limit()

    try:
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise GeocoderTimeoutError(
            f"Nominatim geocoder timed out after {HTTP_TIMEOUT_SECONDS}s for query: '{cleaned_query}'."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise GeocoderServiceError(
            f"Network error communicating with Nominatim geocoder: {exc}."
        ) from exc

    # 3. Handle HTTP status codes (no retries)
    if response.status_code == 429:
        raise GeocoderRateLimitError("Nominatim geocoder rate limit exceeded (HTTP 429).")

    if response.status_code >= 500:
        raise GeocoderServiceError(
            f"Nominatim geocoder returned server error (HTTP {response.status_code})."
        )

    if response.status_code != 200:
        raise GeocoderServiceError(
            f"Nominatim geocoder returned unexpected status code: {response.status_code}."
        )

    # 4. Parse response JSON
    try:
        data = response.json()
    except Exception as exc:
        raise GeocoderServiceError("Failed to parse Nominatim geocoder JSON response.") from exc

    if not data or len(data) == 0:
        raise LocationNotFoundError(f"Could not resolve location: '{cleaned_query}'.")

    result = data[0]
    try:
        lat = float(result['lat'])
        lon = float(result['lon'])
    except (KeyError, ValueError) as exc:
        raise GeocoderServiceError("Nominatim response missing valid 'lat'/'lon' coordinates.") from exc

    display_name = result.get('display_name', cleaned_query)

    # 5. Contiguous United States Validation
    country_code = result.get('address', {}).get('country_code', '').lower()
    if country_code and country_code != 'us':
        raise NonUSLocationError(
            f"Location '{cleaned_query}' resolved outside the United States (country: '{country_code}')."
        )

    if not is_in_conus(lat, lon):
        raise NonUSLocationError(
            f"Location '{cleaned_query}' coordinates ({lat:.4f}, {lon:.4f}) fall outside the contiguous United States coverage area."
        )

    # 6. Save successful result to cache (concurrency-safe race handling)
    try:
        GeocodingCache.objects.get_or_create(
            normalized_query=cache_key,
            defaults={
                'latitude': lat,
                'longitude': lon,
                'display_name': display_name,
            }
        )
    except IntegrityError:
        pass  # Another process concurrently saved this key; safe to ignore

    return {
        'latitude': lat,
        'longitude': lon,
        'display_name': display_name,
        'cached': False,
    }
