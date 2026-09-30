"""
Unit & Integration Tests for Route Planning API Endpoint (POST /api/v1/route/).
Uses the DRF test client (APIClient) with all external HTTP services mocked.
Verifies response schemas, HTTP statuses, custom exception handling, and cache idempotency.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from fuel_route.models import FuelStation


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def sample_stations(db):
    """Create sample fuel stations along a route corridor."""
    FuelStation.objects.create(
        opis_id=101,
        name="Pilot Travel Center #101",
        address="100 Highway Rd",
        city="Hope",
        state="AR",
        retail_price=Decimal("3.5000"),
        latitude=33.5000,
        longitude=-93.5000,
        precision="ROOFTOP",
        geocode_source="test"
    )
    FuelStation.objects.create(
        opis_id=102,
        name="Love's Travel Stop #102",
        address="200 Interstate Way",
        city="Pine Bluff",
        state="AR",
        retail_price=Decimal("3.0000"),
        latitude=34.2500,
        longitude=-92.0000,
        precision="ROOFTOP",
        geocode_source="test"
    )
    FuelStation.objects.create(
        opis_id=103,
        name="Flying J #103",
        address="300 Express Blvd",
        city="Forrest City",
        state="AR",
        retail_price=Decimal("3.2000"),
        latitude=35.0000,
        longitude=-90.5000,
        precision="ROOFTOP",
        geocode_source="test"
    )


def _make_geo_response(lat, lon, display_name="City, State, USA", country_code="us"):
    """Helper creating a distinct mock response for OSM Nominatim."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = [
        {
            "lat": str(lat),
            "lon": str(lon),
            "display_name": display_name,
            "address": {"country_code": country_code}
        }
    ]
    return mock


def _make_osrm_response(start_coords, end_coords, distance_miles=800.0, code="Ok"):
    """Helper to mock an OSRM driving route response."""
    s_lon, s_lat = start_coords
    e_lon, e_lat = end_coords
    coords = [
        [s_lon, s_lat],
        [s_lon + (e_lon - s_lon) * 0.25, s_lat + (e_lat - s_lat) * 0.25],
        [s_lon + (e_lon - s_lon) * 0.50, s_lat + (e_lat - s_lat) * 0.50],
        [s_lon + (e_lon - s_lon) * 0.75, s_lat + (e_lat - s_lat) * 0.75],
        [e_lon, e_lat],
    ]
    distance_meters = distance_miles * 1609.344
    duration_seconds = distance_miles * 60

    mock = MagicMock()
    mock.status_code = 200
    if code != "Ok":
        mock.json.return_value = {"code": code, "message": "No route found"}
    else:
        mock.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": distance_meters,
                    "duration": duration_seconds,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    }
                }
            ]
        }
    return mock


@pytest.mark.django_db
class TestRouteAPIView:
    """Test suite for POST /api/v1/route/ endpoint."""

    ROUTE_URL = "/api/v1/route/"

    def test_missing_or_empty_input(self, api_client):
        """Asserts 400 MISSING_INPUT when parameters are missing or blank."""
        # 1. Missing both fields
        res = api_client.post(self.ROUTE_URL, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "MISSING_INPUT"

        # 2. Missing finish
        res = api_client.post(self.ROUTE_URL, {"start": "Austin, TX"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert data["error"]["code"] == "MISSING_INPUT"
        assert 'finish' in data["error"]["message"].lower()

        # 3. Blank start
        res = api_client.post(self.ROUTE_URL, {"start": "   ", "finish": "Nashville, TN"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert data["error"]["code"] == "MISSING_INPUT"
        assert 'empty' in data["error"]["message"].lower() or 'blank' in data["error"]["message"].lower()

        # 4. Exceeds max length
        res = api_client.post(self.ROUTE_URL, {"start": "A" * 300, "finish": "Nashville, TN"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert data["error"]["code"] == "MISSING_INPUT"

    @patch("requests.get")
    def test_location_not_found(self, mock_get, api_client):
        """Asserts 404 LOCATION_NOT_FOUND when geocoder returns 0 results."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        payload = {"start": "NonExistentPlaceXYZ123", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_404_NOT_FOUND
        data = res.json()
        assert data["error"]["code"] == "LOCATION_NOT_FOUND"
        assert "NonExistentPlaceXYZ123" in data["error"]["message"]

    @patch("requests.get")
    def test_non_us_location(self, mock_get, api_client):
        """Asserts 422 LOCATION_NOT_US when a location resolves outside CONUS."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "lat": "51.5074",
                "lon": "-0.1278",
                "display_name": "London, Greater London, England, United Kingdom",
                "address": {"country_code": "gb"}
            }
        ]
        mock_get.return_value = mock_resp

        payload = {"start": "London, UK", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        data = res.json()
        assert data["error"]["code"] == "LOCATION_NOT_US"

    @patch("requests.get")
    def test_no_route_found(self, mock_get, api_client):
        """Asserts 422 NO_ROUTE_FOUND when OSRM cannot find a driving path."""
        def side_effect(url, *args, **kwargs):
            if "search" in url:
                params = kwargs.get("params", {})
                q = params.get("q", "")
                if "Austin" in q:
                    return _make_geo_response(30.2672, -97.7431, "Austin, Texas, USA")
                return _make_geo_response(36.1627, -86.7816, "Nashville, Tennessee, USA")
            return _make_osrm_response((-97.7431, 30.2672), (-86.7816, 36.1627), code="NoRoute")

        mock_get.side_effect = side_effect

        payload = {"start": "Austin, TX", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        data = res.json()
        assert data["error"]["code"] == "NO_ROUTE_FOUND"

    @patch("requests.get")
    def test_route_not_feasible(self, mock_get, api_client):
        """Asserts 422 ROUTE_NOT_FEASIBLE when distance exceeds 500 miles and no stations exist."""
        start_coords = (-97.7431, 30.2672)
        end_coords = (-86.7816, 36.1627)

        def side_effect(url, *args, **kwargs):
            if "search" in url:
                params = kwargs.get("params", {})
                q = params.get("q", "")
                if "Austin" in q:
                    return _make_geo_response(start_coords[1], start_coords[0], "Austin, Texas, USA")
                return _make_geo_response(end_coords[1], end_coords[0], "Nashville, Tennessee, USA")
            return _make_osrm_response(start_coords, end_coords, distance_miles=850.0)

        mock_get.side_effect = side_effect

        # Ensure NO fuel stations exist in the database
        FuelStation.objects.all().delete()

        payload = {"start": "Austin, TX", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        data = res.json()
        assert data["error"]["code"] == "ROUTE_NOT_FEASIBLE"
        assert "No fuel station reachable" in data["error"]["message"]

    @patch("requests.get")
    def test_route_success_with_stations(self, mock_get, api_client, sample_stations):
        """Asserts 200 OK and validates full response structure and precision."""
        start_coords = (-94.5000, 33.0000)
        end_coords = (-89.5000, 35.5000)

        def side_effect(url, *args, **kwargs):
            if "search" in url:
                params = kwargs.get("params", {})
                q = params.get("q", "")
                if "Texarkana" in q:
                    return _make_geo_response(start_coords[1], start_coords[0], "Texarkana Area, TX, USA")
                return _make_geo_response(end_coords[1], end_coords[0], "Memphis Area, TN, USA")
            return _make_osrm_response(start_coords, end_coords, distance_miles=600.0)

        mock_get.side_effect = side_effect

        payload = {"start": "Texarkana, TX", "finish": "Memphis, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        # Validate top-level keys
        assert "route" in data
        assert "fuel_summary" in data
        assert "fuel_stops" in data

        # Validate route shape
        route = data["route"]
        assert route["start"] == "Texarkana Area, TX, USA"
        assert route["finish"] == "Memphis Area, TN, USA"
        assert route["distance_miles"] == 600.0
        assert "duration_seconds" in route
        assert "duration_formatted" in route
        assert route["geometry"]["type"] == "LineString"

        # Validate fuel_summary shape
        summary = data["fuel_summary"]
        assert isinstance(summary["total_gallons"], float)
        assert isinstance(summary["gallons_purchased"], float)
        assert isinstance(summary["gallons_consumed"], float)
        assert summary["gallons_consumed"] == pytest.approx(60.0)  # 600 miles / 10 mpg
        assert "starting_tank_note" in summary
        assert isinstance(summary["total_fuel_cost"], float)
        assert isinstance(summary["stops_count"], int)
        assert summary["vehicle"] == {
            "mpg": 10.0,
            "max_range_miles": 500.0,
            "tank_capacity_gallons": 50.0
        }

        # Validate fuel_stops shape and precision
        stops = data["fuel_stops"]
        assert len(stops) == summary["stops_count"]
        for stop in stops:
            assert isinstance(stop["stop_number"], int)
            assert isinstance(stop["opis_id"], int)
            assert isinstance(stop["name"], str)
            assert isinstance(stop["address"], str)
            assert isinstance(stop["city"], str)
            assert isinstance(stop["state"], str)
            assert isinstance(stop["latitude"], float)
            assert isinstance(stop["longitude"], float)
            assert isinstance(stop["precision"], str)
            assert isinstance(stop["geocode_source"], str)
            assert isinstance(stop["distance_from_start_miles"], float)
            assert isinstance(stop["gallons_pumped"], float)
            assert isinstance(stop["price_per_gallon"], float)
            assert isinstance(stop["cost"], float)

    @patch("requests.get")
    def test_repeated_identical_request_makes_zero_external_calls(
        self, mock_get, api_client, sample_stations
    ):
        """
        Critical test: Asserts that after the first request populates GeocodingCache
        and RouteCache, an identical subsequent request makes ZERO external HTTP calls.
        """
        start_coords = (-94.5000, 33.0000)
        end_coords = (-89.5000, 35.5000)

        def side_effect(url, *args, **kwargs):
            if "search" in url:
                params = kwargs.get("params", {})
                q = params.get("q", "")
                if "Origin" in q:
                    return _make_geo_response(start_coords[1], start_coords[0], "Origin City, TX, USA")
                return _make_geo_response(end_coords[1], end_coords[0], "Dest City, TN, USA")
            return _make_osrm_response(start_coords, end_coords, distance_miles=600.0)

        mock_get.side_effect = side_effect

        payload = {"start": "Cached Origin, TX", "finish": "Cached Dest, TN"}

        # First request (populates cache)
        res1 = api_client.post(self.ROUTE_URL, payload, format="json")
        assert res1.status_code == status.HTTP_200_OK

        initial_calls = mock_get.call_count
        assert initial_calls == 3  # 2 geocodes + 1 route

        # Second identical request (must hit GeocodingCache and RouteCache)
        res2 = api_client.post(self.ROUTE_URL, payload, format="json")
        assert res2.status_code == status.HTTP_200_OK

        # Verify ZERO additional outbound calls were made!
        assert mock_get.call_count == initial_calls
        assert res1.json() == res2.json()

    @patch("requests.get")
    def test_geocoder_timeout_maps_to_504(self, mock_get, api_client):
        """Asserts 504 GEOCODER_TIMEOUT when geocoder times out."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        payload = {"start": "Austin, TX", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = res.json()
        assert data["error"]["code"] == "GEOCODER_TIMEOUT"

    @patch("requests.get")
    def test_geocoder_rate_limited_maps_to_429(self, mock_get, api_client):
        """Asserts 429 GEOCODER_RATE_LIMITED when geocoder returns 429."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp

        payload = {"start": "Austin, TX", "finish": "Nashville, TN"}
        res = api_client.post(self.ROUTE_URL, payload, format="json")

        assert res.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        data = res.json()
        assert data["error"]["code"] == "GEOCODER_RATE_LIMITED"
