# Phase 4: Fuel Route Planning API

**Endpoint:** `POST /api/v1/route/`  
**Content-Type:** `application/json`  
**Status:** Complete  

---

## 1. Overview & Purpose

The Fuel Route Planning API provides automated route calculation and optimal fuel stop recommendations for commercial freight vehicles operating across the contiguous United States. Given an origin (`start`) and destination (`finish`), the service:
1. Geocodes both locations using OpenStreetMap Nominatim.
2. Validates that both endpoints reside within the contiguous US (CONUS).
3. Queries the Open Source Routing Machine (OSRM) for turn-by-turn driving trajectory and road distance.
4. Identifies commercial diesel fuel stations within a 10-mile perpendicular highway detour corridor.
5. Employs a greedy lookahead optimization algorithm to calculate the cheapest sequence of fuel stops, exact gallons to pump, and total fuel expenditure without exceeding the vehicle's 500-mile tank range.
6. Returns a structured JSON payload containing route geometry, fuel summary metrics, and stop-by-stop purchase instructions.

---

## 2. API Specification

### 2.1 Request Schema

`POST /api/v1/route/`

#### Headers
| Header | Value | Required | Description |
|---|---|---|---|
| `Content-Type` | `application/json` | Yes | Request payload format |
| `Accept` | `application/json` | Optional | Desired response format |

#### Request Body (JSON)
| Field | Type | Required | Max Length | Description |
|---|---|---|---|---|
| `start` | `string` | **Yes** | 255 | Human-readable origin (e.g., `"Austin, TX"` or `"Seattle, WA"`) |
| `finish` | `string` | **Yes** | 255 | Human-readable destination (e.g., `"Nashville, TN"` or `"Miami, FL"`) |

#### Example Request
```json
{
  "start": "Austin, TX",
  "finish": "Nashville, TN"
}
```

---

### 2.2 Response Schema

#### Success Response (`200 OK`)
```json
{
  "route": {
    "start": "Austin, Travis County, Texas, United States",
    "finish": "Nashville-Davidson, Davidson County, Middle Tennessee, Tennessee, United States",
    "distance_miles": 862.4,
    "duration_seconds": 47250.0,
    "duration_formatted": "13h 07m",
    "geometry": {
      "type": "LineString",
      "coordinates": [
        [-97.7431, 30.2672],
        [-94.0477, 33.4255],
        [-86.7816, 36.1627]
      ]
    }
  },
  "fuel_summary": {
    "gallons_consumed": 86.24,
    "gallons_purchased": 36.24,
    "total_gallons": 36.24,
    "total_fuel_cost": 108.72,
    "stops_count": 1,
    "starting_tank_note": "Vehicle departs origin with a full 50-gallon tank at no additional cost; gallons_purchased reflects fuel pumped along the route.",
    "vehicle": {
      "mpg": 10.0,
      "max_range_miles": 500.0,
      "tank_capacity_gallons": 50.0
    }
  },
  "fuel_stops": [
    {
      "stop_number": 1,
      "opis_id": 68421,
      "name": "Love's Travel Stop #412",
      "address": "1500 Interstate 30",
      "city": "Texarkana",
      "state": "AR",
      "latitude": 33.4352,
      "longitude": -94.0128,
      "precision": "ROOFTOP",
      "geocode_source": "nominatim_exact",
      "distance_from_start_miles": 382.6,
      "gallons_pumped": 36.24,
      "price_per_gallon": 3.0000,
      "cost": 108.72
    }
  ]
}
```

#### Field Specifications & Precision
* `route.distance_miles`: Float, rounded to 1 decimal place (odometer miles).
* `route.duration_seconds`: Float, total estimated driving seconds.
* `route.duration_formatted`: Human-friendly string (e.g. `"13h 07m"`).
* `route.geometry`: GeoJSON `LineString` with coordinates `[longitude, latitude]`.
* `fuel_summary.gallons_consumed`: Float, rounded to 2 decimal places (`distance_miles / mpg`).
* `fuel_summary.gallons_purchased`: Float, rounded to 2 decimal places (total fuel pumped along the route).
* `fuel_summary.total_gallons`: Float, alias for `gallons_purchased`.
* `fuel_summary.total_fuel_cost`: Float, rounded to 2 decimal places (exact sum of per-stop costs).
* `fuel_summary.stops_count`: Integer count of recommended stops.
* `fuel_summary.starting_tank_note`: Explanatory note confirming starting tank is not charged.
* `fuel_summary.vehicle`: Parameters applied during optimization (`mpg`: 10.0, `max_range_miles`: 500.0, `tank_capacity_gallons`: 50.0).
* `fuel_stops[].precision`: Geocoding precision level (`ROOFTOP`, `RANGE_INTERPOLATED`, `GEOMETRIC_CENTER`, `APPROXIMATE`).
* `fuel_stops[].distance_from_start_miles`: Float, rounded to 1 decimal place.
* `fuel_stops[].gallons_pumped`: Float, rounded to 2 decimal places.
* `fuel_stops[].price_per_gallon`: Float, 4 decimal places ($/gal).
* `fuel_stops[].cost`: Float, rounded to 2 decimal places ($).

---

## 3. Error Handling Taxonomy

All service, validation, and network errors are caught and returned in a uniform JSON format via a custom DRF exception handler:

```json
{
  "error": {
    "code": "<MACHINE_READABLE_CODE>",
    "message": "<Human-readable explanation of error>"
  }
}
```

### Complete Error Code & Status Reference
| HTTP Status | Error Code (`code`) | Trigger Condition |
|---|---|---|
| `400 Bad Request` | `MISSING_INPUT` | Missing `start` or `finish`, blank strings, or string exceeding 255 chars. |
| `404 Not Found` | `LOCATION_NOT_FOUND` | Nominatim geocoder returned 0 matching places for the query string. |
| `422 Unprocessable Entity` | `LOCATION_NOT_US` | Geocoded coordinate or query resolves outside the contiguous US bounding box. |
| `422 Unprocessable Entity` | `NO_ROUTE_FOUND` | OSRM routing engine cannot compute a driving route between the coordinates. |
| `422 Unprocessable Entity` | `ROUTE_NOT_FEASIBLE` | Route distance exceeds 500 miles and has a station gap exceeding vehicle range. |
| `429 Too Many Requests` | `GEOCODER_RATE_LIMITED` | Outbound geocoder request was rejected with HTTP 429. |
| `502 Bad Gateway` | `GEOCODER_ERROR` | Geocoder returned HTTP 5xx or network connection was dropped. |
| `502 Bad Gateway` | `ROUTING_ERROR` | OSRM routing engine returned HTTP 5xx or connection failed. |
| `504 Gateway Timeout` | `GEOCODER_TIMEOUT` | Geocoder HTTP request exceeded the configured timeout threshold. |
| `504 Gateway Timeout` | `ROUTING_TIMEOUT` | OSRM HTTP request exceeded the configured timeout threshold. |

> [!NOTE]
> **Distinction Between 404 and 422 for Locations:**
> * `404 LOCATION_NOT_FOUND`: Returned when Nominatim returns 0 results within the US. This occurs for unresolvable strings (e.g. `"asdkjhqwe"`) as well as overseas queries (e.g. `"Paris, France"`), because the geocoder strictly enforces `countrycodes=us`.
> * `422 LOCATION_NOT_US`: Returned when Nominatim resolves a US address or territory, but the coordinates fall outside the contiguous 48 US states bounding box (e.g. `"Anchorage, AK"` or `"Honolulu, HI"`).

---

## 4. Caching & Performance Architecture

The API implements a two-tier persistent database caching architecture that ensures high throughput and idempotency:

1. **`GeocodingCache`:**
   - Normalizes queries (lowercase, alphanumeric alphanumeric tokens).
   - Permanent cache row per unique location.
   - Eliminates redundant calls to OpenStreetMap Nominatim.
2. **`RouteCache`:**
   - Keys route requests by rounded 4-decimal coordinates: `route:{start_lat}:{start_lon}:{end_lat}:{end_lon}`.
   - Stores full GeoJSON geometry, distance, and duration.
   - Eliminates redundant calls to the OSRM server.
3. **Cache Hit Guarantee:**
   - A repeated identical request makes **zero outbound HTTP calls**, executing in sub-25 milliseconds.

---

## 5. Example cURL Invocations

### 5.1 Successful Route Optimization
```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Austin, TX", "finish": "Nashville, TN"}'
```

### 5.2 Missing Input Error (400)
```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Austin, TX"}'
```
Response:
```json
{
  "error": {
    "code": "MISSING_INPUT",
    "message": "Parameter \"finish\" is required."
  }
}
```

### 5.3 Non-US Location Error (422)
```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "London, UK", "finish": "Nashville, TN"}'
```
Response:
```json
{
  "error": {
    "code": "LOCATION_NOT_US",
    "message": "Location \"London, UK\" (51.5074, -0.1278) resolves outside the contiguous United States coverage area."
  }
}
```
