"""
Error taxonomy and custom exception classes for external service calls (Geocoding & Routing).
Each exception exposes an error_code (for machine parsing) and http_status (for REST responses).
"""

class ServiceException(Exception):
    """Base exception for all service layer errors."""
    error_code = "SERVICE_ERROR"
    http_status = 500

    def __init__(self, message: str, error_code: str = None, http_status: int = None):
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status

    def to_dict(self):
        return {
            "error": self.error_code,
            "message": self.message,
            "status_code": self.http_status,
        }


class InvalidInputError(ServiceException):
    """Raised when input parameters are missing, empty, or malformed."""
    error_code = "MISSING_INPUT"
    http_status = 400


class LocationNotFoundError(ServiceException):
    """Raised when the geocoder returns 0 results for a location query."""
    error_code = "LOCATION_NOT_FOUND"
    http_status = 404


class NonUSLocationError(ServiceException):
    """Raised when coordinates or location resolve outside the contiguous United States."""
    error_code = "LOCATION_NOT_US"
    http_status = 422


class GeocoderTimeoutError(ServiceException):
    """Raised when the geocoder HTTP request times out."""
    error_code = "GEOCODER_TIMEOUT"
    http_status = 504


class GeocoderRateLimitError(ServiceException):
    """Raised when the geocoder returns HTTP 429 (rate limited)."""
    error_code = "GEOCODER_RATE_LIMITED"
    http_status = 429


class GeocoderServiceError(ServiceException):
    """Raised when the geocoder returns a 5xx error or connection fails."""
    error_code = "GEOCODER_ERROR"
    http_status = 502


class NoRouteFoundError(ServiceException):
    """Raised when the routing engine cannot find a driving route between coordinates."""
    error_code = "NO_ROUTE_FOUND"
    http_status = 422


class RouteNotFeasibleError(ServiceException):
    """Raised when vehicle cannot complete the route due to station-free gaps exceeding vehicle range."""
    error_code = "ROUTE_NOT_FEASIBLE"
    http_status = 422


class RoutingTimeoutError(ServiceException):

    """Raised when the routing engine HTTP request times out."""
    error_code = "ROUTING_TIMEOUT"
    http_status = 504


class RoutingServiceError(ServiceException):
    """Raised when the routing engine returns a 5xx error or connection fails."""
    error_code = "ROUTING_ERROR"
    http_status = 502
