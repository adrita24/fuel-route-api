from unittest.mock import patch, MagicMock
import pytest
import requests
from django.core.exceptions import ImproperlyConfigured

from fuel_route.models import GeocodingCache
from fuel_route.services.geocoding import geocode, is_in_conus, normalize_query
from fuel_route.services.exceptions import (
    InvalidInputError,
    LocationNotFoundError,
    NonUSLocationError,
    GeocoderTimeoutError,
    GeocoderRateLimitError,
    GeocoderServiceError,
)

@pytest.fixture(autouse=True)
def ensure_contact_email(monkeypatch):
    """Ensure GEOCODER_CONTACT_EMAIL is populated for all tests."""
    monkeypatch.setenv('GEOCODER_CONTACT_EMAIL', 'test_contact@example.com')

@pytest.mark.django_db
class TestGeocodingService:
    def test_normalize_query(self):
        assert normalize_query("  Austin,   TX  ") == "austin, tx"
        assert normalize_query("NEW YORK, NY") == "new york, ny"
        assert normalize_query("") == ""

    def test_conus_bounding_box_checks(self):
        # Austin, TX (valid)
        assert is_in_conus(30.2672, -97.7431) is True
        # Seattle, WA (valid)
        assert is_in_conus(47.6062, -122.3321) is True
        # Honolulu, HI (outside CONUS)
        assert is_in_conus(21.3069, -157.8583) is False
        # Anchorage, AK (outside CONUS)
        assert is_in_conus(61.2181, -149.9003) is False
        # London, UK (outside CONUS)
        assert is_in_conus(51.5074, -0.1278) is False

    @patch('requests.get')
    def test_geocode_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'lat': '30.267153',
                'lon': '-97.743061',
                'display_name': 'Austin, Travis County, Texas, United States',
                'address': {'country_code': 'us', 'state': 'Texas'}
            }
        ]
        mock_get.return_value = mock_resp

        result = geocode("Austin, TX")

        assert result['latitude'] == pytest.approx(30.267153)
        assert result['longitude'] == pytest.approx(-97.743061)
        assert "Austin" in result['display_name']
        assert result['cached'] is False

        # Verify cached in database
        cached = GeocodingCache.objects.filter(normalized_query="austin, tx").first()
        assert cached is not None
        assert cached.latitude == pytest.approx(30.267153)

    @patch('requests.get')
    def test_geocode_cache_hit_makes_zero_external_calls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'lat': '39.739236',
                'lon': '-104.984862',
                'display_name': 'Denver, Colorado, United States',
                'address': {'country_code': 'us'}
            }
        ]
        mock_get.return_value = mock_resp

        # First call hits mock
        res1 = geocode("Denver, CO")
        assert res1['cached'] is False
        assert mock_get.call_count == 1

        # Second call with variation in casing and spacing must hit cache with zero HTTP calls
        res2 = geocode("   denver,   co   ")
        assert res2['cached'] is True
        assert res2['latitude'] == pytest.approx(39.739236)
        assert mock_get.call_count == 1  # Still 1! No additional call

    def test_geocode_missing_or_empty_input(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            geocode("")

        with pytest.raises(InvalidInputError, match="cannot be empty"):
            geocode("   ")

    @patch('requests.get')
    def test_geocode_location_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        with pytest.raises(LocationNotFoundError, match="Could not resolve location"):
            geocode("NonexistentFictionalTown12345")

        # Verify no negative caching
        assert not GeocodingCache.objects.filter(normalized_query="nonexistentfictionaltown12345").exists()

    @patch('requests.get')
    def test_geocode_non_us_country(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'lat': '43.6532',
                'lon': '-79.3832',
                'display_name': 'Toronto, Ontario, Canada',
                'address': {'country_code': 'ca'}
            }
        ]
        mock_get.return_value = mock_resp

        with pytest.raises(NonUSLocationError, match="outside the United States"):
            geocode("Toronto, ON")

        # Verify no negative caching
        assert not GeocodingCache.objects.filter(normalized_query="toronto, on").exists()

    @patch('requests.get')
    def test_geocode_out_of_conus_bounding_box(self, mock_get):
        # Hawaii is US, but outside Contiguous US (CONUS)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'lat': '21.3069',
                'lon': '-157.8583',
                'display_name': 'Honolulu, Hawaii, United States',
                'address': {'country_code': 'us'}
            }
        ]
        mock_get.return_value = mock_resp

        with pytest.raises(NonUSLocationError, match="outside the contiguous United States"):
            geocode("Honolulu, HI")

        assert not GeocodingCache.objects.filter(normalized_query="honolulu, hi").exists()

    @patch('requests.get')
    def test_geocode_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        with pytest.raises(GeocoderTimeoutError, match="timed out"):
            geocode("Chicago, IL")

        assert not GeocodingCache.objects.filter(normalized_query="chicago, il").exists()

    @patch('requests.get')
    def test_geocode_rate_limited(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp

        with pytest.raises(GeocoderRateLimitError, match="rate limit exceeded"):
            geocode("Dallas, TX")

        assert not GeocodingCache.objects.filter(normalized_query="dallas, tx").exists()

    @patch('requests.get')
    def test_geocode_server_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        with pytest.raises(GeocoderServiceError, match="server error"):
            geocode("Atlanta, GA")

        assert not GeocodingCache.objects.filter(normalized_query="atlanta, ga").exists()

    def test_geocode_missing_email_raises_improperly_configured(self, monkeypatch):
        monkeypatch.delenv('GEOCODER_CONTACT_EMAIL', raising=False)
        with pytest.raises(ImproperlyConfigured, match="GEOCODER_CONTACT_EMAIL is not set"):
            geocode("Miami, FL")
