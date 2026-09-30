"""
Route Planning & Fuel Optimization Orchestrator Service.
Coordinates geocoding, OSRM routing, corridor station matching, and fuel stop optimization.
"""

from typing import Dict, Any

from fuel_route.services.geocoding import geocode
from fuel_route.services.routing import get_route
from fuel_route.services.stations import get_candidate_stations_along_route
from fuel_route.services.optimizer import optimize_fuel_stops


def plan_fuel_route(start_query: str, finish_query: str) -> Dict[str, Any]:
    """
    Execute the end-to-end fuel route optimization pipeline:
      1. Forward geocode start and finish locations (OSM Nominatim)
      2. Fetch highway driving route and geometry (OSRM)
      3. Discover and project fuel stations within the route corridor (Shapely + SQL)
      4. Compute minimum-cost fuel stops (Greedy Lookahead Optimizer)
      5. Assemble structured response

    Returns:
      {
        'route': {
          'start': str,
          'finish': str,
          'distance_miles': float,
          'duration_seconds': float,
          'duration_formatted': str,
          'geometry': dict  # GeoJSON LineString
        },
        'fuel_summary': {
          'total_gallons': float,
          'total_fuel_cost': float,
          'stops_count': int,
          'vehicle': {...}
        },
        'fuel_stops': [
          {
            'stop_number': int,
            'opis_id': int,
            'name': str,
            'address': str,
            'city': str,
            'state': str,
            'latitude': float,
            'longitude': float,
            'precision': str,
            'geocode_source': str,
            'distance_from_start_miles': float,
            'gallons_pumped': float,
            'price_per_gallon': float,
            'cost': float
          }, ...
        ]
      }
    """
    # 1. Forward Geocoding
    start_geo = geocode(start_query)
    finish_geo = geocode(finish_query)

    # 2. Highway Routing
    route_data = get_route(
        start_lat=start_geo['latitude'],
        start_lon=start_geo['longitude'],
        end_lat=finish_geo['latitude'],
        end_lon=finish_geo['longitude']
    )

    # 3. Corridor Station Matching
    candidate_stations = get_candidate_stations_along_route(
        route_geometry=route_data['geometry'],
        osrm_distance_miles=route_data['distance_miles']
    )

    # 4. Fuel Stop Optimization
    fuel_stops, fuel_summary = optimize_fuel_stops(
        total_route_miles=route_data['distance_miles'],
        candidate_stations=candidate_stations
    )

    # 5. Format human-friendly duration
    duration_secs = route_data['duration_seconds']
    hours = int(duration_secs // 3600)
    minutes = int((duration_secs % 3600) // 60)
    duration_formatted = f"{hours}h {minutes:02d}m"

    return {
        'route': {
            'start': start_geo['display_name'],
            'finish': finish_geo['display_name'],
            'distance_miles': route_data['distance_miles'],
            'duration_seconds': route_data['duration_seconds'],
            'duration_formatted': duration_formatted,
            'geometry': route_data['geometry'],
        },
        'fuel_summary': fuel_summary,
        'fuel_stops': fuel_stops,
    }
