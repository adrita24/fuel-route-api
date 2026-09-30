# 02: System Architecture & Request Lifecycle

**Component:** System Architecture  
**Status:** Complete  

---

## 1. High-Level System Architecture

The service is organized into a clean, layered architecture separating HTTP serialization, service orchestration, spatial geometry processing, and pure mathematical optimization:

```
[ Client Request: POST /api/v1/route/ ]
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│ 1. API Transport Layer (fuel_route/views.py)            │
│   - DRF RouteRequestSerializer: validates start/finish  │
│   - DRF custom_exception_handler: uniform error format  │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Orchestration Layer (fuel_route/services/planner.py) │
│   - Coordinates pipeline execution                      │
│   - Formats human-friendly travel metrics               │
└───────────┬───────────────┬───────────────┬─────────────┘
            │               │               │
            ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────────────┐
│ Geocoding       │ │ Routing     │ │ Spatial Matching    │
│ (geocoding.py)  │ │ (routing.py)│ │ (stations.py)       │
│ - OSM Nominatim │ │ - OSRM API  │ │ - SQL Bbox Prefilter│
│ - Rate Limiter  │ │ - GeoJSON   │ │ - Shapely STRtree   │
│ - CONUS Filter  │ │ - RouteCache│ │ - Segment-Local     │
│ - GeocodingCache│ │             │ │   Metric Projection │
└─────────────────┘ └─────────────┘ └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ Pure Optimizer      │
                                    │ (optimizer.py)      │
                                    │ - Greedy Lookahead  │
                                    │ - Local Min Fill    │
                                    │ - Decimal Math      │
                                    └─────────────────────┘
```

---

## 2. End-to-End Request Lifecycle

When a client sends a `POST /api/v1/route/` request (e.g. `{"start": "Austin, TX", "finish": "Nashville, TN"}`), the application executes a 6-step pipeline:

### Step 1: Input Validation
* Handled by `RouteRequestSerializer` in [`fuel_route/serializers.py`](file:///d:/code/assignment/fuel_route/serializers.py).
* Checks that `start` and `finish` are provided, non-empty, trimmed, and $\le 255$ characters.
* Malformed input immediately raises a validation error, mapped to HTTP `400 Bad Request` with code `MISSING_INPUT`.

### Step 2: Forward Geocoding & CONUS Validation
* Handled by `geocode()` in [`fuel_route/services/geocoding.py`](file:///d:/code/assignment/fuel_route/services/geocoding.py).
* **Cache Check:** Normalizes the query and inspects `GeocodingCache`. If found, returns coordinates in `< 2 ms`.
* **Outbound Call:** If missing, verifies `GEOCODER_CONTACT_EMAIL`, enforces the $\ge 1.05\text{s}$ thread-safe rate limit, and queries OpenStreetMap Nominatim with `countrycodes=us`.
* **Bounding Box Validation:** Ensures coordinates fall within the contiguous US bounding box (`[24.0, 50.0]` lat, `[-125.0, -66.5]` lon) derived from Census Gazetteer places. Rejects non-contiguous US coordinates (e.g. Anchorage, AK) with `LOCATION_NOT_US` (HTTP 422). Overseas queries (e.g. Paris, France) return zero results from Nominatim due to `countrycodes=us`, raising `LOCATION_NOT_FOUND` (HTTP 404).
* **Cache Write:** On success, permanently stores the resolved location in `GeocodingCache`.

### Step 3: Highway Driving Route Fetch
* Handled by `get_route()` in [`fuel_route/services/routing.py`](file:///d:/code/assignment/fuel_route/services/routing.py).
* **Cache Check:** Rounds start/finish coordinates to 4 decimal places (~11 meters) to form a canonical route key (e.g. `30.2672,-97.7431->36.1627,-86.7816`). Checks `RouteCache`.
* **Outbound Call:** If missing, queries OSRM (`/route/v1/driving/`) requesting full GeoJSON geometry.
* Validates OSRM status code; transforms distance from meters to miles.
* Permanently stores the route geometry, odometer miles, and duration in `RouteCache`.

### Step 4: Spatial Corridor Detour Filtering & Projection
* Handled by `get_candidate_stations_along_route()` in [`fuel_route/services/stations.py`](file:///d:/code/assignment/fuel_route/services/stations.py).
* **Stage 1 (SQL Bounding Box):** Calculates the route bounding box with high-latitude longitude expansion ($\Delta \text{lon} \propto \frac{1}{\cos(\text{lat})}$). Executes a single indexed SQL query against `fuel_stations` (0 N+1 queries), pruning 6,626 stations down to ~50–300 candidates in `< 5 ms`.
* **Stage 2 (Shapely STRtree Projection):** Indexes route segments in an $O(M \log N)$ spatial R-tree. Projects candidate stations onto nearby highway segments using segment-local metric Cartesian projection, bounding local curvature distortion to $< 0.001\%$.
* Retains stations with perpendicular cross-track distance $\le 10.0\text{ miles}$.
* Scales cumulative segment distance to match OSRM's authoritative odometer mileage.

### Step 5: Fuel Stop Optimization
* Handled by `optimize_fuel_stops()` in [`fuel_route/services/optimizer.py`](file:///d:/code/assignment/fuel_route/services/optimizer.py).
* Pure Python module with zero database or Django dependencies.
* Evaluates fuel inventory using Decimal arithmetic.
* Checks destination reachability on current fuel.
* Looks ahead up to a full tank range (500 miles):
  * If a cheaper station exists within full range $\implies$ purchases just enough fuel at current station to reach the nearest cheaper stop.
  * If current station is a local minimum $\implies$ fills to full capacity (50 gal) and advances to next immediate station.
* Validates that every leg between stops $\le 500\text{ miles}$.

### Step 6: Response Assembly & Delivery
* Handled by `plan_fuel_route()` in [`fuel_route/services/planner.py`](file:///d:/code/assignment/fuel_route/services/planner.py).
* Assembles route summary, stop-by-stop purchase table, gallons consumed vs purchased, and returns HTTP 200 JSON payload.
