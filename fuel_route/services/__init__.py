"""
External services and routing optimization package.
"""

from .exceptions import (
    ServiceException,
    InvalidInputError,
    LocationNotFoundError,
    NonUSLocationError,
    GeocoderTimeoutError,
    GeocoderRateLimitError,
    GeocoderServiceError,
    NoRouteFoundError,
    RouteNotFeasibleError,
    RoutingTimeoutError,
    RoutingServiceError,
)
from .geocoding import geocode, is_in_conus, normalize_query
from .routing import get_route, make_route_key
from .stations import get_candidate_stations_along_route
from .optimizer import optimize_fuel_stops

__all__ = [
    'ServiceException',
    'InvalidInputError',
    'LocationNotFoundError',
    'NonUSLocationError',
    'GeocoderTimeoutError',
    'GeocoderRateLimitError',
    'GeocoderServiceError',
    'NoRouteFoundError',
    'RouteNotFeasibleError',
    'RoutingTimeoutError',
    'RoutingServiceError',
    'geocode',
    'is_in_conus',
    'normalize_query',
    'get_route',
    'make_route_key',
    'get_candidate_stations_along_route',
    'optimize_fuel_stops',
]
