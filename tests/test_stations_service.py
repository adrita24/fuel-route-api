import pytest
from decimal import Decimal
from fuel_route.models import FuelStation
from fuel_route.services.stations import get_candidate_stations_along_route

@pytest.mark.django_db
class TestStationsService:
    def test_empty_or_invalid_geometry(self):
        assert get_candidate_stations_along_route({}, 100.0) == []
        assert get_candidate_stations_along_route({'coordinates': []}, 100.0) == []
        assert get_candidate_stations_along_route({'coordinates': [[-97.74, 30.26]]}, 100.0) == []

    def test_corridor_matching_and_projection(self):
        """
        Create a straight west-to-east route across Texas along latitude ~32.0:
        Start at (-98.0, 32.0), End at (-96.0, 32.0). Approx 117 miles.
        Station 1: directly on highway (-97.0, 32.0) -> matched at ~58.5 miles.
        Station 2: 5 miles north (-97.0, 32.072) -> within 10 mi corridor, matched.
        Station 3: 25 miles north (-97.0, 32.362) -> outside 10 mi corridor, excluded.
        """
        FuelStation.objects.create(
            opis_id=5001,
            name="Highway Stop",
            address="Exit 10",
            city="Midway",
            state="TX",
            latitude=32.0000,
            longitude=-97.0000,
            retail_price=Decimal("3.1500"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )
        FuelStation.objects.create(
            opis_id=5002,
            name="Near Corridor Stop",
            address="Exit 12",
            city="Midway North",
            state="TX",
            latitude=32.0720,  # ~5 miles north
            longitude=-97.0000,
            retail_price=Decimal("3.0500"),
            geocode_source="osm_nominatim",
            precision="poi_match"
        )
        FuelStation.objects.create(
            opis_id=5003,
            name="Far Off Stop",
            address="Rural Rd 50",
            city="Far Hills",
            state="TX",
            latitude=32.3620,  # ~25 miles north
            longitude=-97.0000,
            retail_price=Decimal("2.9500"),
            geocode_source="us_census_gazetteer",
            precision="approximate_city"
        )

        route_geom = {
            'type': 'LineString',
            'coordinates': [
                [-98.0000, 32.0000],
                [-97.0000, 32.0000],
                [-96.0000, 32.0000],
            ]
        }
        total_miles = 117.0

        matched = get_candidate_stations_along_route(
            route_geometry=route_geom,
            osrm_distance_miles=total_miles,
            corridor_miles=10.0
        )

        matched_ids = [s['opis_id'] for s in matched]
        assert 5001 in matched_ids
        assert 5002 in matched_ids
        assert 5003 not in matched_ids

        s1_result = next(s for s in matched if s['opis_id'] == 5001)
        assert s1_result['distance_from_start_miles'] == pytest.approx(58.5, abs=2.0)
        assert s1_result['cross_track_distance_miles'] == pytest.approx(0.0, abs=0.5)

        s2_result = next(s for s in matched if s['opis_id'] == 5002)
        assert s2_result['cross_track_distance_miles'] == pytest.approx(5.0, abs=1.0)

    def test_station_at_corridor_boundary_and_outside(self):
        """
        Verify precise boundary behavior:
        Route along lat 35.0 from lon -100.0 to -99.0 (~56.5 miles).
        1 degree of latitude = 69.0 miles -> 0.1449 deg lat = 10.0 miles.
        Station inside/on boundary (9.9 miles north): should be included.
        Station outside boundary (10.5 miles north): should be excluded.
        """
        FuelStation.objects.create(
            opis_id=6001,
            name="Boundary Station",
            address="Mile 25 Boundary",
            city="Clinton",
            state="OK",
            latitude=35.0 + (9.9 / 69.0),  # 9.9 miles north
            longitude=-99.5,
            retail_price=Decimal("3.1000"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )
        FuelStation.objects.create(
            opis_id=6002,
            name="Outside Boundary Station",
            address="Mile 25 Outside",
            city="Clinton North",
            state="OK",
            latitude=35.0 + (10.5 / 69.0),  # 10.5 miles north
            longitude=-99.5,
            retail_price=Decimal("2.9900"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )

        route_geom = {
            'type': 'LineString',
            'coordinates': [
                [-100.0, 35.0],
                [-99.0, 35.0]
            ]
        }

        matched = get_candidate_stations_along_route(
            route_geometry=route_geom,
            osrm_distance_miles=56.5,
            corridor_miles=10.0
        )

        matched_ids = [s['opis_id'] for s in matched]
        assert 6001 in matched_ids
        assert 6002 not in matched_ids

    def test_high_latitude_longitude_buffer(self):
        """
        Verify high-latitude longitude expansion:
        At lat 48.5°N (near Canada border, North Dakota):
        cos(48.5 deg) ~ 0.662.
        1 degree lon = 69.0 * 0.662 = 45.7 miles.
        A station 8.0 miles east of the route requires delta_lon = 8.0 / 45.7 = 0.175 deg lon.
        If delta_lon was naive (10 / 69 = 0.145 deg), the SQL bbox would erroneously miss it!
        """
        # Route running north-south along longitude -100.0 from 48.0N to 49.0N (~69 miles)
        route_geom = {
            'type': 'LineString',
            'coordinates': [
                [-100.0, 48.0],
                [-100.0, 49.0]
            ]
        }

        # Station located at lat 48.5N, 8 miles east (lon = -100.0 + 8.0 / (69.0 * cos(48.5 deg)) ~ -99.825)
        # Note: 0.175 deg lon offset is 8.0 miles at this latitude
        lat_test = 48.5
        lon_offset = 8.0 / (69.0 * 0.6626)  # ~0.175 deg
        lon_test = -100.0 + lon_offset

        FuelStation.objects.create(
            opis_id=7001,
            name="High Latitude Border Stop",
            address="Hwy 5",
            city="Bottineau",
            state="ND",
            latitude=lat_test,
            longitude=lon_test,
            retail_price=Decimal("3.2500"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )

        matched = get_candidate_stations_along_route(
            route_geometry=route_geom,
            osrm_distance_miles=69.0,
            corridor_miles=10.0
        )

        matched_ids = [s['opis_id'] for s in matched]
        assert 7001 in matched_ids
        res = next(s for s in matched if s['opis_id'] == 7001)
        assert res['cross_track_distance_miles'] == pytest.approx(8.0, abs=0.5)

    def test_stations_sorted_by_distance_from_start(self):
        """Verify that returned candidate stations are strictly ordered ascending by distance_from_start_miles."""
        route_geom = {
            'type': 'LineString',
            'coordinates': [
                [-100.0, 30.0],
                [-98.0, 30.0]
            ]
        }

        # Create stations out of order along the route
        offsets = [
            (8001, -98.5, Decimal("3.20")),  # furthest (~90 miles)
            (8002, -99.8, Decimal("3.10")),  # closest (~10 miles)
            (8003, -99.2, Decimal("3.05")),  # middle (~50 miles)
        ]
        for oid, lon, pr in offsets:
            FuelStation.objects.create(
                opis_id=oid,
                name=f"Station {oid}",
                address="I-10",
                city="Junction",
                state="TX",
                latitude=30.0,
                longitude=lon,
                retail_price=pr,
                geocode_source="us_census_batch",
                precision="street_interpolated"
            )

        matched = get_candidate_stations_along_route(
            route_geometry=route_geom,
            osrm_distance_miles=120.0,
            corridor_miles=10.0
        )

        matched_ids = [s['opis_id'] for s in matched]
        assert matched_ids == [8002, 8003, 8001]
        distances = [s['distance_from_start_miles'] for s in matched]
        assert distances == sorted(distances)
