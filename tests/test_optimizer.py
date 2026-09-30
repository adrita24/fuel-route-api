import pytest
from decimal import Decimal
from fuel_route.services.optimizer import optimize_fuel_stops
from fuel_route.services.exceptions import RouteNotFeasibleError

class TestOptimizer:
    def test_short_route_under_max_range(self):
        """Routes under 500 miles complete on the initial full tank with zero stops."""
        stations = [
            {'opis_id': 1, 'name': 'Stop 1', 'distance_from_start_miles': 150.0, 'retail_price': 3.20},
            {'opis_id': 2, 'name': 'Stop 2', 'distance_from_start_miles': 280.0, 'retail_price': 3.10},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=350.0, candidate_stations=stations)
        assert stops == []
        assert summary['stops_count'] == 0
        assert summary['total_gallons'] == 0.0
        assert summary['total_fuel_cost'] == 0.0

    def test_exactly_max_range_route(self):
        """Route exactly equal to 500 miles completes on initial full tank with 0 stops."""
        stations = [
            {'opis_id': 1, 'name': 'Stop 1', 'distance_from_start_miles': 250.0, 'retail_price': 3.00}
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=500.0, candidate_stations=stations)
        assert stops == []
        assert summary['stops_count'] == 0

    def test_brief_ab_destination_example(self):
        """
        Brief example:
        Route: Start at 0, Station A at 300 ($3.50), Station B at 450 ($3.00), Destination at 700.
        Vehicle skips Station A and refuels only at cheaper Station B.
        Fuel needed at B to reach dest: (700 - 450) / 10 = 25 gal.
        Fuel in tank upon arrival at B: 50 - 45 = 5 gal.
        Gallons to buy at B: 25 - 5 = 20 gal.
        Cost: 20 * $3.00 = $60.00.
        """
        stations = [
            {'opis_id': 101, 'name': 'Station A', 'distance_from_start_miles': 300.0, 'retail_price': 3.50},
            {'opis_id': 102, 'name': 'Station B', 'distance_from_start_miles': 450.0, 'retail_price': 3.00},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=700.0, candidate_stations=stations)

        assert len(stops) == 1
        assert stops[0]['opis_id'] == 102
        assert stops[0]['name'] == 'Station B'
        assert stops[0]['gallons_pumped'] == 20.0
        assert stops[0]['price_per_gallon'] == 3.00
        assert stops[0]['cost'] == 60.00
        assert summary['total_gallons'] == 20.0
        assert summary['total_fuel_cost'] == 60.00

    def test_cheaper_station_beyond_current_fuel_but_within_full_range(self):
        """
        User Rule 1 Test:
        At Station 1 (mile 300, price $3.50), fuel remaining is 20 gal (current range = 200 mi, reaches mile 500).
        Station 2 is at mile 600 with price $3.00 (cheaper!).
        Station 2 is beyond current fuel (mile 500), but within full-tank range from Station 1 (300 + 500 = 800 mi).
        At Station 1: Buy just enough to reach Station 2 (300 mi / 10 = 30 gal needed; 30 - 20 = 10 gal to buy).
        At Station 2: Buy 20 gal to finish the 800 mi route (800 - 600 = 200 mi / 10 = 20 gal).
        """
        stations = [
            {'opis_id': 1, 'name': 'Station 1', 'distance_from_start_miles': 300.0, 'retail_price': 3.50},
            {'opis_id': 2, 'name': 'Station 2', 'distance_from_start_miles': 600.0, 'retail_price': 3.00},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=800.0, candidate_stations=stations)

        assert len(stops) == 2
        # Station 1
        assert stops[0]['opis_id'] == 1
        assert stops[0]['distance_from_start_miles'] == 300.0
        assert stops[0]['gallons_pumped'] == 10.0
        assert stops[0]['cost'] == 35.00
        # Station 2
        assert stops[1]['opis_id'] == 2
        assert stops[1]['distance_from_start_miles'] == 600.0
        assert stops[1]['gallons_pumped'] == 20.0
        assert stops[1]['cost'] == 60.00

        assert summary['total_gallons'] == 30.0
        assert summary['total_fuel_cost'] == 95.00

    def test_cheaper_station_beyond_full_range_triggers_local_minimum_fill(self):
        """
        User Rule 2 Test:
        Station 1 at 300 mi ($3.50). Full range is 300 + 500 = 800 mi.
        Station 2 at 450 mi ($3.80 - more expensive).
        Station 3 at 850 mi ($2.50 - cheaper, but beyond 800 mi full range).
        Station 1 is a local minimum: fills to full (30 gal at $3.50), advances to next station (Station 2 at 450).
        At Station 2: Station 3 (850 mi) is within Station 2's full range (450 + 500 = 950 mi) and cheaper!
        Buys just enough at Station 2 to reach Station 3.
        """
        stations = [
            {'opis_id': 1, 'name': 'Station 1', 'distance_from_start_miles': 300.0, 'retail_price': 3.50},
            {'opis_id': 2, 'name': 'Station 2', 'distance_from_start_miles': 450.0, 'retail_price': 3.80},
            {'opis_id': 3, 'name': 'Station 3', 'distance_from_start_miles': 850.0, 'retail_price': 2.50},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=1000.0, candidate_stations=stations)

        assert len(stops) == 3
        # Stop 1 at Station 1: fills to full
        assert stops[0]['opis_id'] == 1
        assert stops[0]['gallons_pumped'] == 30.0  # 50 - 20
        assert stops[0]['cost'] == 105.00

        # Stop 2 at Station 2: arrives with 35 gal, needs 40 gal to reach Station 3 -> buys 5 gal
        assert stops[1]['opis_id'] == 2
        assert stops[1]['gallons_pumped'] == 5.0
        assert stops[1]['cost'] == 19.00

        # Stop 3 at Station 3: arrives with 0 gal, needs 15 gal to reach destination 1000 -> buys 15 gal
        assert stops[2]['opis_id'] == 3
        assert stops[2]['gallons_pumped'] == 15.0
        assert stops[2]['cost'] == 37.50

        assert summary['total_gallons'] == 50.0
        assert summary['total_fuel_cost'] == 161.50

    def test_two_stations_at_identical_mile_marker(self):
        """
        User Rule 3 Test:
        Two stations at the exact same mile marker (e.g. across the street at mile 350).
        The optimizer must select the cheaper station and ignore the more expensive one.
        """
        stations = [
            {'opis_id': 201, 'name': 'Expensive Stop', 'distance_from_start_miles': 350.0, 'retail_price': 3.89},
            {'opis_id': 202, 'name': 'Cheap Stop', 'distance_from_start_miles': 350.0, 'retail_price': 3.09},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=700.0, candidate_stations=stations)

        assert len(stops) == 1
        assert stops[0]['opis_id'] == 202
        assert stops[0]['name'] == 'Cheap Stop'
        assert stops[0]['price_per_gallon'] == 3.09

    def test_two_stations_at_nearly_same_mile_marker_tie_break(self):
        """
        Two stations at nearly the same mile marker (e.g. 0.2 miles apart: 350.0 vs 350.2).
        The optimizer must handle this as a price tie-break (1 stop total at cheaper station), not two stops.
        """
        stations = [
            {'opis_id': 301, 'name': 'Expensive Near Stop', 'distance_from_start_miles': 350.0, 'retail_price': 3.89},
            {'opis_id': 302, 'name': 'Cheap Near Stop', 'distance_from_start_miles': 350.2, 'retail_price': 3.09},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=700.0, candidate_stations=stations)

        assert len(stops) == 1
        assert stops[0]['opis_id'] == 302
        assert stops[0]['name'] == 'Cheap Near Stop'
        assert stops[0]['distance_from_start_miles'] == 350.2
        assert stops[0]['price_per_gallon'] == 3.09

    def test_station_at_mile_zero_and_at_destination(self):
        """
        User Rule 4 Test:
        Station at mile 0 (cannot pump because starting tank is full).
        Station at destination (cannot pump because trip is completed).
        """
        stations = [
            {'opis_id': 1, 'name': 'Start Station', 'distance_from_start_miles': 0.0, 'retail_price': 2.80},
            {'opis_id': 2, 'name': 'Mid Station', 'distance_from_start_miles': 400.0, 'retail_price': 3.10},
            {'opis_id': 3, 'name': 'End Station', 'distance_from_start_miles': 700.0, 'retail_price': 2.50},
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=700.0, candidate_stations=stations)

        # Only Mid Station is used
        assert len(stops) == 1
        assert stops[0]['opis_id'] == 2
        assert stops[0]['distance_from_start_miles'] == 400.0

    def test_route_not_feasible_gap_over_max_range(self):
        """Gaps between stations exceeding max range raise RouteNotFeasibleError."""
        stations = [
            {'opis_id': 1, 'name': 'Station 1', 'distance_from_start_miles': 200.0, 'retail_price': 3.20},
            {'opis_id': 2, 'name': 'Station 2', 'distance_from_start_miles': 750.0, 'retail_price': 3.10},  # 550 mi gap!
        ]
        with pytest.raises(RouteNotFeasibleError, match="No fuel station reachable|exceeds vehicle range"):
            optimize_fuel_stops(total_route_miles=900.0, candidate_stations=stations)

    def test_route_not_feasible_no_stations_on_long_route(self):
        """Long route with zero stations raises RouteNotFeasibleError."""
        with pytest.raises(RouteNotFeasibleError, match="No fuel station reachable"):
            optimize_fuel_stops(total_route_miles=800.0, candidate_stations=[])

    def test_transcontinental_long_route(self):
        """Long route (2,800 miles) with multiple consecutive stops completes cleanly."""
        stations = [
            {'opis_id': i, 'name': f'Stop {i}', 'distance_from_start_miles': float(i * 200), 'retail_price': 3.00 + (i % 3) * 0.20}
            for i in range(1, 14)  # 200, 400, 600, ... 2600
        ]
        stops, summary = optimize_fuel_stops(total_route_miles=2800.0, candidate_stations=stations)

        assert len(stops) >= 5
        # Total distance driven after initial 500 miles = 2300 miles -> 230 gallons needed
        assert summary['total_gallons'] == pytest.approx(230.0, abs=0.5)
        assert summary['total_fuel_cost'] > 0.0
