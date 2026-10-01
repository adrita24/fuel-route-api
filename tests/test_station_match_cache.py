import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command

from fuel_route.models import FuelStation, StationMatchCache
from fuel_route.services.planner import plan_fuel_route
from fuel_route.services.optimizer import optimize_fuel_stops


@pytest.fixture
def sample_corridor_stations(db):
    """Seed sample stations along a straight path for corridor matching."""
    FuelStation.objects.create(
        opis_id=9001,
        name="Test Corridor Station 1",
        address="Interstate 10 Exit 1",
        city="Midway",
        state="TX",
        retail_price=Decimal("3.2500"),
        latitude=31.0000,
        longitude=-97.0000,
        precision="poi_match",
        geocode_source="test"
    )
    FuelStation.objects.create(
        opis_id=9002,
        name="Test Corridor Station 2",
        address="Interstate 10 Exit 2",
        city="Midway East",
        state="TX",
        retail_price=Decimal("2.9500"),
        latitude=31.5000,
        longitude=-96.0000,
        precision="poi_match",
        geocode_source="test"
    )


@pytest.fixture
def mock_geo_and_routing():
    """Mock geocoding and routing to return deterministic 600-mile route."""
    with patch("fuel_route.services.planner.geocode") as mock_geo, \
         patch("fuel_route.services.planner.get_route") as mock_route:

        mock_geo.side_effect = lambda q: {
            "latitude": 30.5000 if "Start" in q else 32.5000,
            "longitude": -97.5000 if "Start" in q else -95.5000,
            "display_name": f"{q} Resolved Address, TX, USA",
            "cached": True
        }

        mock_route.return_value = {
            "distance_miles": 600.0,
            "duration_seconds": 36000.0,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-97.5000, 30.5000],
                    [-97.0000, 31.0000],
                    [-96.0000, 31.5000],
                    [-95.5000, 32.5000]
                ]
            },
            "cached": True
        }

        yield mock_geo, mock_route


@pytest.mark.django_db
class TestStationMatchCache:

    def test_repeated_identical_request_calls_matching_once(
        self, mock_geo_and_routing, sample_corridor_stations
    ):
        """Asserts that repeated identical request calls get_candidate_stations_along_route once, not twice."""
        with patch(
            "fuel_route.services.planner.get_candidate_stations_along_route",
            wraps=plan_fuel_route.__globals__["get_candidate_stations_along_route"]
        ) as spy_matching:
            # First call: cache miss -> runs matching and populates StationMatchCache
            res1 = plan_fuel_route("Start Location", "Finish Location")
            assert spy_matching.call_count == 1
            assert StationMatchCache.objects.count() == 1

            # Second call: cache hit -> skips matching
            res2 = plan_fuel_route("Start Location", "Finish Location")
            assert spy_matching.call_count == 1  # Still 1! Not called again
            assert res1 == res2

    def test_response_body_identical_cold_and_warm(
        self, mock_geo_and_routing, sample_corridor_stations
    ):
        """Asserts that the response body is identical field-for-field with cold and warm cache."""
        StationMatchCache.objects.all().delete()

        # Cold request
        cold_res = plan_fuel_route("Start Point", "Finish Point")

        # Warm request
        warm_res = plan_fuel_route("Start Point", "Finish Point")

        # Exact equality check including all nested fields and values
        assert cold_res == warm_res
        assert cold_res["fuel_summary"]["total_fuel_cost"] == warm_res["fuel_summary"]["total_fuel_cost"]
        assert cold_res["fuel_stops"] == warm_res["fuel_stops"]

    def test_different_corridor_miles_produces_different_cache_key(
        self, mock_geo_and_routing, sample_corridor_stations, monkeypatch
    ):
        """Asserts that changing ROUTE_CORRIDOR_MILES produces a distinct cache key without cross-contamination."""
        StationMatchCache.objects.all().delete()

        # Run with 10.0 miles corridor
        monkeypatch.setattr(settings, "ROUTE_CORRIDOR_MILES", 10.0)
        plan_fuel_route("Start Point", "Finish Point")
        assert StationMatchCache.objects.filter(key__endswith="|10.0").exists()

        # Run with 15.0 miles corridor
        monkeypatch.setattr(settings, "ROUTE_CORRIDOR_MILES", 15.0)
        plan_fuel_route("Start Point", "Finish Point")
        assert StationMatchCache.objects.filter(key__endswith="|15.0").exists()

        # Both cache entries exist independently
        assert StationMatchCache.objects.count() == 2

    def test_changing_mpg_or_range_uses_same_station_cache_and_gives_different_optimizer_output(
        self, mock_geo_and_routing, sample_corridor_stations
    ):
        """Asserts candidate stations from StationMatchCache can be fed to optimizer with different vehicle parameters."""
        StationMatchCache.objects.all().delete()
        plan_fuel_route("Start Point", "Finish Point")
        cached_entry = StationMatchCache.objects.first()
        assert cached_entry is not None

        # Pass cached candidate stations directly into optimizer with different vehicle parameters
        stops1, summary1 = optimize_fuel_stops(
            total_route_miles=600.0,
            candidate_stations=cached_entry.matches,
            mpg=10.0,
            max_range_miles=500.0
        )
        stops2, summary2 = optimize_fuel_stops(
            total_route_miles=600.0,
            candidate_stations=cached_entry.matches,
            mpg=5.0,
            max_range_miles=250.0
        )

        assert summary1["vehicle"]["mpg"] == 10.0
        assert summary1["gallons_consumed"] == 60.0  # 600 / 10
        assert summary2["vehicle"]["mpg"] == 5.0
        assert summary2["gallons_consumed"] == 120.0  # 600 / 5

    def test_import_fuel_data_clears_cache(self, tmp_path):
        """Asserts that import_fuel_data clears StationMatchCache at the end of a successful run."""
        # Pre-seed cache with dummy records
        StationMatchCache.objects.create(key="test_route_1|10.0", matches=[])
        StationMatchCache.objects.create(key="test_route_2|10.0", matches=[])
        assert StationMatchCache.objects.count() == 2

        # Create minimal CSV files for import_fuel_data command
        fuel_csv = tmp_path / "fuel.csv"
        fuel_csv.write_text(
            "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
            "9999,Test Truckstop,123 Interstate,Austin,TX,1,2.8900\n",
            encoding="utf-8"
        )
        coords_csv = tmp_path / "coords.csv"
        coords_csv.write_text(
            "opis_id,latitude,longitude,geocode_source,precision\n"
            "9999,30.2672,-97.7431,test_source,poi_match\n",
            encoding="utf-8"
        )

        out = io.StringIO()
        call_command(
            "import_fuel_data",
            fuel_csv=str(fuel_csv),
            coords_csv=str(coords_csv),
            stdout=out
        )
        output = out.getvalue()

        # Cache must be completely wiped
        assert StationMatchCache.objects.count() == 0
        assert "StationMatchCache rows cleared: 2" in output
