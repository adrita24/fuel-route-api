from unittest.mock import patch, MagicMock
import pytest
import requests

from fuel_route.models import RouteCache
from fuel_route.services.routing import get_route, make_route_key
from fuel_route.services.exceptions import (
    InvalidInputError,
    NonUSLocationError,
    NoRouteFoundError,
    RoutingTimeoutError,
    RoutingServiceError,
)

@pytest.mark.django_db
class TestRoutingService:
    def test_make_route_key(self):
        key = make_route_key(30.267153, -97.743061, 32.776664, -96.796988)
        assert key == "30.2672,-97.7431->32.7767,-96.7970"

    @patch('requests.get')
    def test_get_route_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': 'Ok',
            'routes': [
                {
                    'distance': 313822.0,  # ~195 miles in meters
                    'duration': 10800.0,   # 3 hours
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': [[-97.7431, 30.2672], [-96.7970, 32.7767]]
                    }
                }
            ]
        }
        mock_get.return_value = mock_resp

        # Austin, TX to Dallas, TX
        res = get_route(30.2672, -97.7431, 32.7767, -96.7970)

        assert res['distance_miles'] == pytest.approx(195.0, abs=1.0)
        assert res['duration_seconds'] == 10800.0
        assert res['geometry']['type'] == 'LineString'
        assert res['cached'] is False

        # Verify cached in database
        key = make_route_key(30.2672, -97.7431, 32.7767, -96.7970)
        cached = RouteCache.objects.filter(route_key=key).first()
        assert cached is not None
        assert cached.distance_miles == res['distance_miles']

    @patch('requests.get')
    def test_get_route_cache_hit_makes_zero_external_calls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': 'Ok',
            'routes': [
                {
                    'distance': 160934.4,  # 100 miles
                    'duration': 5400.0,
                    'geometry': {'type': 'LineString', 'coordinates': []}
                }
            ]
        }
        mock_get.return_value = mock_resp

        # First call hits mock
        res1 = get_route(35.0, -90.0, 36.0, -89.0)
        assert res1['cached'] is False
        assert mock_get.call_count == 1

        # Second call with micro-differences that round to same 4 decimals must hit cache
        res2 = get_route(35.00001, -90.00002, 36.00003, -88.99998)
        assert res2['cached'] is True
        assert res2['distance_miles'] == res1['distance_miles']
        assert mock_get.call_count == 1  # Zero additional external calls

    def test_get_route_invalid_coordinates(self):
        with pytest.raises(InvalidInputError, match="must be a valid number"):
            get_route(None, -97.7431, 32.7767, -96.7970)

        with pytest.raises(InvalidInputError, match="must be a valid number"):
            get_route("not_a_number", -97.7431, 32.7767, -96.7970)

    def test_get_route_non_us_coordinates(self):
        # Origin outside CONUS (e.g. London, UK)
        with pytest.raises(NonUSLocationError, match="outside the contiguous United States"):
            get_route(51.5074, -0.1278, 32.7767, -96.7970)

        # Destination outside CONUS (e.g. Hawaii)
        with pytest.raises(NonUSLocationError, match="outside the contiguous United States"):
            get_route(30.2672, -97.7431, 21.3069, -157.8583)

    @patch('requests.get')
    def test_get_route_no_route_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': 'NoRoute',
            'message': 'Impossible route between points'
        }
        mock_get.return_value = mock_resp

        with pytest.raises(NoRouteFoundError, match="No driving route found"):
            get_route(30.2672, -97.7431, 32.7767, -96.7970)

        # Verify no negative caching
        key = make_route_key(30.2672, -97.7431, 32.7767, -96.7970)
        assert not RouteCache.objects.filter(route_key=key).exists()

    @patch('requests.get')
    def test_get_route_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Read timeout")

        with pytest.raises(RoutingTimeoutError, match="timed out"):
            get_route(30.2672, -97.7431, 32.7767, -96.7970)

        key = make_route_key(30.2672, -97.7431, 32.7767, -96.7970)
        assert not RouteCache.objects.filter(route_key=key).exists()

    @patch('requests.get')
    def test_get_route_server_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_get.return_value = mock_resp

        with pytest.raises(RoutingServiceError, match="server returned an error"):
            get_route(30.2672, -97.7431, 32.7767, -96.7970)

        key = make_route_key(30.2672, -97.7431, 32.7767, -96.7970)
        assert not RouteCache.objects.filter(route_key=key).exists()
