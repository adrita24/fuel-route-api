"""
Pure Python Fuel Stop Optimizer (Phase 3).
Decoupled optimization module with ZERO Django imports.

Core Assumptions:
  1. Starting Fuel: Vehicle departs start (mile 0) with a completely full tank (tank_capacity_gallons).
  2. No Minimum Reserve: Fuel can safely reach 0.0 gallons at the exact moment of pulling into a station
     or reaching the final destination.
  3. Constant Fuel Consumption: Fuel consumption is linear at 1.0 / mpg gallons per mile driven.
  4. Precise Math: All arithmetic on fuel volumes, prices, and costs uses Python's Decimal type.
     Rounding is applied only when preparing output data.

Algorithm (Greedy Lookahead with Local Minimum Filling):
  At each position S_curr (initially mile 0 with full tank):
    1. If destination is reachable on current fuel: proceed to destination and finish.
    2. To decide whether a cheaper station exists, use FULL-TANK range (max_range_miles) from S_curr.
       - Case 1: A cheaper station (price < current_price) exists within full-tank range.
         Buy just enough fuel at S_curr to reach the NEAREST (first) cheaper station with 0 fuel remaining.
         (If current fuel is already sufficient, buy 0 gallons). Advance to that station.
       - Case 2: No cheaper station exists within full-tank range (S_curr is the local minimum):
         - Subcase 2a: Destination is within full-tank range:
           Buy just enough fuel to reach destination with 0 fuel remaining. Proceed to destination.
         - Subcase 2b: Destination is NOT within full-tank range:
           Fill tank to FULL capacity at S_curr. Advance to the NEXT immediate station on the route,
           then re-evaluate.
  Feasibility:
    If at any point the distance to the next station (or destination) exceeds max_range_miles,
    raises RouteNotFeasibleError (ROUTE_NOT_FEASIBLE).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Tuple, Optional

from fuel_route.services.exceptions import RouteNotFeasibleError


def _to_decimal(val: Any) -> Decimal:
    """Safely convert float/int/str/Decimal to Decimal."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def optimize_fuel_stops(
    total_route_miles: float,
    candidate_stations: List[Dict[str, Any]],
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
    tank_capacity_gallons: Optional[float] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Compute the cost-optimal fuel stops along a highway route.

    Parameters:
      total_route_miles: Total driving distance of the route in miles.
      candidate_stations: List of candidate stations along the corridor.
                          Each dict must have 'distance_from_start_miles', 'retail_price', and station details.
      max_range_miles: Maximum driving range on a full tank (default: 500.0).
      mpg: Vehicle miles per gallon (default: 10.0).
      tank_capacity_gallons: Tank capacity in gallons (default: max_range_miles / mpg).

    Returns:
      Tuple of:
        (
          fuel_stops: List[Dict[str, Any]],
          fuel_summary: Dict[str, Any]
        )

    Raises:
      RouteNotFeasibleError: If a gap between stations (or to destination) exceeds max range.
    """
    total_miles = _to_decimal(total_route_miles)
    max_range = _to_decimal(max_range_miles)
    mpg_dec = _to_decimal(mpg)
    tank_capacity = _to_decimal(tank_capacity_gallons) if tank_capacity_gallons else (max_range / mpg_dec)

    # 1. Edge Case: 0 or negative route miles
    if total_miles <= Decimal('0'):
        return [], {
            'total_gallons': 0.0,
            'total_fuel_cost': 0.0,
            'stops_count': 0,
            'vehicle': {
                'mpg': float(mpg),
                'max_range_miles': float(max_range_miles),
                'tank_capacity_gallons': float(tank_capacity)
            }
        }

    # 2. Edge Case: Route completes on initial full tank with zero refueling stops
    if total_miles <= max_range:
        return [], {
            'total_gallons': 0.0,
            'total_fuel_cost': 0.0,
            'stops_count': 0,
            'vehicle': {
                'mpg': float(mpg),
                'max_range_miles': float(max_range_miles),
                'tank_capacity_gallons': float(tank_capacity)
            }
        }

    # 3. Clean, deduplicate, and sort stations
    # Filter to stations within [0, total_miles].
    # At identical mile markers, pick the station with the strictly lowest retail price.
    filtered_stations = []
    for s in candidate_stations:
        d = _to_decimal(s['distance_from_start_miles'])
        p = _to_decimal(s['retail_price'])
        if Decimal('0') <= d <= total_miles:
            filtered_stations.append({
                'data': s,
                'dist': d,
                'price': p
            })

    # Sort primarily by distance ascending, secondarily by price ascending
    filtered_stations.sort(key=lambda item: (item['dist'], item['price']))

    # Deduplicate identical mile markers: keep the cheaper station
    unique_stations_by_dist: Dict[Decimal, Dict[str, Any]] = {}
    for item in filtered_stations:
        d = item['dist']
        if d not in unique_stations_by_dist or item['price'] < unique_stations_by_dist[d]['price']:
            unique_stations_by_dist[d] = item

    stations: List[Dict[str, Any]] = sorted(unique_stations_by_dist.values(), key=lambda item: item['dist'])

    # 4. Simulation Setup
    current_pos = Decimal('0')
    current_fuel = tank_capacity  # Departs with full tank
    current_price = Decimal('Infinity')  # Virtual start node has infinite price
    current_station_data: Optional[Dict[str, Any]] = None

    raw_stops: List[Dict[str, Any]] = []
    total_gallons = Decimal('0')
    total_cost = Decimal('0')

    # 5. Greedy Lookahead Loop
    while current_pos < total_miles:
        # Check if destination can be reached with current fuel
        dist_to_dest = total_miles - current_pos
        fuel_needed_for_dest = dist_to_dest / mpg_dec

        if current_fuel >= fuel_needed_for_dest:
            current_fuel -= fuel_needed_for_dest
            current_pos = total_miles
            break

        # Collect candidate stations within full-tank range from current position
        # Note: stations strictly ahead of current_pos
        ahead_stations = [s for s in stations if s['dist'] > current_pos]
        in_range_stations = [s for s in ahead_stations if s['dist'] <= current_pos + max_range]

        # Feasibility check: Can we reach ANY station or destination?
        if not in_range_stations:
            # Check if destination is reachable from here
            if dist_to_dest <= max_range:
                # Local minimum, destination is within full range!
                gallons_to_buy = fuel_needed_for_dest - current_fuel
                if gallons_to_buy > Decimal('0') and current_station_data is not None:
                    cost = gallons_to_buy * current_price
                    total_gallons += gallons_to_buy
                    total_cost += cost
                    raw_stops.append({
                        'station': current_station_data,
                        'dist': current_pos,
                        'price': current_price,
                        'gallons': gallons_to_buy,
                        'cost': cost
                    })
                break
            else:
                raise RouteNotFeasibleError(
                    f"No fuel station reachable within {max_range_miles} miles after mile {float(current_pos):.1f} "
                    f"(destination is {float(dist_to_dest):.1f} miles away)."
                )

        # Check if a cheaper station exists within full range
        cheaper_stations = [s for s in in_range_stations if s['price'] < current_price]

        if cheaper_stations:
            # Case 1: Cheaper station exists within full range.
            # Advance to the FIRST (nearest) cheaper station.
            next_station = cheaper_stations[0]
            dist_to_next = next_station['dist'] - current_pos
            fuel_needed_to_next = dist_to_next / mpg_dec

            # Buy only enough at current station to reach next_station with 0 fuel remaining
            if fuel_needed_to_next > current_fuel:
                gallons_to_buy = fuel_needed_to_next - current_fuel
                if current_station_data is not None:
                    cost = gallons_to_buy * current_price
                    total_gallons += gallons_to_buy
                    total_cost += cost
                    raw_stops.append({
                        'station': current_station_data,
                        'dist': current_pos,
                        'price': current_price,
                        'gallons': gallons_to_buy,
                        'cost': cost
                    })
                current_fuel = Decimal('0')
            else:
                # Existing fuel is already sufficient to reach next_station
                current_fuel -= fuel_needed_to_next

            # Advance to next station
            current_pos = next_station['dist']
            current_price = next_station['price']
            current_station_data = next_station['data']

        else:
            # Case 2: No cheaper station within full range. Current station is a local minimum.
            if dist_to_dest <= max_range:
                # Subcase 2a: Destination is within full range!
                gallons_to_buy = fuel_needed_for_dest - current_fuel
                if gallons_to_buy > Decimal('0') and current_station_data is not None:
                    cost = gallons_to_buy * current_price
                    total_gallons += gallons_to_buy
                    total_cost += cost
                    raw_stops.append({
                        'station': current_station_data,
                        'dist': current_pos,
                        'price': current_price,
                        'gallons': gallons_to_buy,
                        'cost': cost
                    })
                current_pos = total_miles
                break
            else:
                # Subcase 2b: Destination is NOT within full range.
                # Fill tank to FULL capacity at this cheap local minimum.
                gallons_to_buy = tank_capacity - current_fuel
                if gallons_to_buy > Decimal('0') and current_station_data is not None:
                    cost = gallons_to_buy * current_price
                    total_gallons += gallons_to_buy
                    total_cost += cost
                    raw_stops.append({
                        'station': current_station_data,
                        'dist': current_pos,
                        'price': current_price,
                        'gallons': gallons_to_buy,
                        'cost': cost
                    })
                current_fuel = tank_capacity

                # Advance to the NEXT immediate station on the route
                next_station = in_range_stations[0]
                dist_to_next = next_station['dist'] - current_pos
                if dist_to_next > max_range:
                    raise RouteNotFeasibleError(
                        f"Gap of {float(dist_to_next):.1f} miles to next station exceeds vehicle range ({max_range_miles} mi)."
                    )

                current_fuel -= dist_to_next / mpg_dec
                current_pos = next_station['dist']
                current_price = next_station['price']
                current_station_data = next_station['data']

    # 6. Format Output (round only at output boundary)
    formatted_stops = []
    for idx, stop in enumerate(raw_stops, 1):
        s_data = stop['station']
        gallons_val = stop['gallons']
        cost_val = stop['cost']
        price_val = stop['price']
        dist_val = stop['dist']

        formatted_stops.append({
            'stop_number': idx,
            'opis_id': s_data.get('opis_id'),
            'name': s_data.get('name'),
            'address': s_data.get('address'),
            'city': s_data.get('city'),
            'state': s_data.get('state'),
            'latitude': s_data.get('latitude'),
            'longitude': s_data.get('longitude'),
            'precision': s_data.get('precision'),
            'geocode_source': s_data.get('geocode_source'),
            'distance_from_start_miles': float(dist_val.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)),
            'gallons_pumped': float(gallons_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'price_per_gallon': float(price_val.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
            'cost': float(cost_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        })

    # Calculate sum of rounded per-stop costs for exact penny reconciliation
    total_fuel_cost = round(sum(s['cost'] for s in formatted_stops), 2)
    gallons_purchased_val = float(total_gallons.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    gallons_consumed_val = float((total_miles / mpg_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    summary = {
        'gallons_consumed': gallons_consumed_val,
        'gallons_purchased': gallons_purchased_val,
        'total_gallons': gallons_purchased_val,  # Alias for backward compatibility
        'total_fuel_cost': total_fuel_cost,
        'stops_count': len(formatted_stops),
        'starting_tank_note': "Vehicle departs origin with a full 50-gallon tank at no additional cost; gallons_purchased reflects fuel pumped along the route.",
        'vehicle': {
            'mpg': float(mpg),
            'max_range_miles': float(max_range_miles),
            'tank_capacity_gallons': float(tank_capacity)
        }
    }

    return formatted_stops, summary
