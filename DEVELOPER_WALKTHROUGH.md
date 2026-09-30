# Developer & Interviewer Walkthrough

**Service:** Fuel Route Optimizer API  
**Language/Framework:** Python 3.13, Django 6.1.1, Django REST Framework 3.18.1  
**Target Audience:** Evaluating Engineers, Architects, and Technical Interviewers  

---

## 1. Quick Repository Tour & Directory Map

```
assignment/
├── config/                        # Django configuration & settings
│   ├── settings.py                # Strict DB settings, vehicle params, DRF handlers
│   └── urls.py                    # Root URL router (/api/v1/ routing)
├── fuel_route/                    # Main Django application
│   ├── models.py                  # FuelStation, GeocodingCache, RouteCache
│   ├── serializers.py             # RouteRequestSerializer (start/finish validation)
│   ├── views.py                   # Thin RoutePlanView APIView
│   ├── handlers.py                # Uniform exception handler {"error": {"code", "message"}}
│   ├── urls.py                    # App routing (/route/)
│   ├── services/                  # Decoupled business & computational logic
│   │   ├── exceptions.py          # Structured error taxonomy & status mapping
│   │   ├── geocoding.py           # Nominatim client, 1.05s rate limiter, CONUS check
│   │   ├── routing.py             # OSRM driving route client & GeoJSON parser
│   │   ├── stations.py            # SQL BBox prefilter & Shapely STRtree projection
│   │   ├── optimizer.py           # Pure Python greedy lookahead fuel optimizer
│   │   └── planner.py             # Pipeline orchestrator
│   └── management/commands/
│       └── import_fuel_data.py    # Idempotent CSV ingestion command
├── data/                          # Preprocessed coordinates and cache
│   ├── station_coordinates.csv    # 6,626 geocoded station coordinates
│   └── nominatim_cache.json       # 3,050 cached Nominatim query responses
├── docs/                          # Comprehensive technical design documentation
│   ├── 01-project-overview.md     # Motivation, constraints, deliverables
│   ├── 02-architecture.md         # Request lifecycle & layer diagram
│   ├── 04-geocoding.md            # Geocoder provider, rate limits, caching
│   ├── 05-routing.md              # OSRM routing, geometries, error taxonomy
│   ├── 06-fuel-station-selection.md # Spatial corridor matching & projection math
│   ├── 07-optimization-algorithm.md # Greedy lookahead rules & worked examples
│   ├── 08-api.md                  # REST endpoint specification & OpenAPI schemas
│   ├── 09-performance.md          # Latency benchmarks & micro-profiling breakdown
│   ├── 10-testing.md              # Automated testing philosophy & invariants
│   ├── 11-decisions-and-tradeoffs.md # Architectural decisions & alternatives
│   ├── 12-locally-running-the-project.md # Windows setup & running instructions
│   ├── sample_response_ny_to_chicago.json # Real 289 KB production API response
│   └── fuel_route_optimizer.postman_collection.json # Postman 2.1 collection
├── tests/                         # Automated pytest suite (54 tests, 100% pass)
├── requirements.txt               # Locked dependencies
├── README.md                      # Primary project documentation
├── ASSESSMENT_CHECKLIST.md        # Specification compliance matrix
└── DEVELOPER_WALKTHROUGH.md       # (This file)
```

---

## 2. Core Service Deep-Dive

### 2.1 The Data Layer ([`fuel_route/models.py`](file:///d:/code/assignment/fuel_route/models.py))
* **`FuelStation`:** Encapsulates the physical truck stop, price ($/gal), and spatial coordinates. A composite index on `(latitude, longitude)` guarantees sub-5ms bounding box filtering across 6,626 stations.
* **`GeocodingCache` & `RouteCache`:** Permanent PostgreSQL cache tables indexed by normalized query strings and 4-decimal coordinate keys.

### 2.2 Geocoding & CONUS Boundary Validation ([`fuel_route/services/geocoding.py`](file:///d:/code/assignment/fuel_route/services/geocoding.py))
* Uses OpenStreetMap Nominatim with an in-process thread-safe lock ensuring $\ge 1.05\text{s}$ spacing between outbound requests.
* Derives contiguous US boundaries directly from all 31,523 Census Gazetteer places (`[24.0, 50.0]` lat, `[-125.0, -66.5]` lon). Rejects non-US points immediately with HTTP 422.

### 2.3 Spatial Highway Detour Corridor Matching ([`fuel_route/services/stations.py`](file:///d:/code/assignment/fuel_route/services/stations.py))
* Solves the distortion problem of transcontinental routes (where a single equirectangular projection incurs up to $+18.9\%$ error).
* Implements **segment-local metric projection with Shapely `STRtree`**:
  * Evaluates candidates against nearby highway segments centered on the segment midpoint, bounding local curvature error to **$< 0.001\%$**.
  * Scales cumulative vertex distances to match OSRM's authoritative odometer mileage.

### 2.4 Pure Optimizer ([`fuel_route/services/optimizer.py`](file:///d:/code/assignment/fuel_route/services/optimizer.py))
* Pure Python module with zero database or Django imports.
* **Rule 1 (Cheaper Station Ahead):** If a cheaper station exists within full-tank range (500 miles), purchase only enough fuel to reach the nearest cheaper stop.
* **Rule 2 (Local Minimum Fill):** If the current station is cheaper than any station within reach, exploit its price by **filling the tank to capacity (50 gal)** and advancing to the next station.
* Employs `Decimal` arithmetic throughout to prevent floating point drift.

---

## 3. Request Trace Walkthrough: "New York, NY" $\to$ "Chicago, IL"

When `POST /api/v1/route/` is called with `{"start": "New York, NY", "finish": "Chicago, IL"}`:
1. `RouteRequestSerializer` validates input.
2. `geocode("New York, NY")` and `geocode("Chicago, IL")` fetch coordinates in 2.7 ms from `GeocodingCache`.
3. `get_route()` retrieves the 790.6-mile driving trajectory from `RouteCache` in 12.2 ms.
4. `get_candidate_stations_along_route()` executes a single SQL bounding box prefilter on PostgreSQL in 4.2 ms, finding ~120 candidates, then projects them onto the highway line string using Shapely in 336 ms.
5. `optimize_fuel_stops()` determines the 2 optimal stops in 1.2 ms:
   * Departs New York with 50 gal.
   * Reaches **SHEETZ #639** (Youngstown, OH at mile 391.0) with 10.9 gal remaining; pumps 5.67 gal at $3.059/gal ($17.34).
   * Reaches **S&G #88** (Toledo, OH at mile 556.7) with 0.0 gal remaining; pumps 23.39 gal at $3.009/gal ($70.38).
   * Reaches Chicago destination (mile 790.6) with 0.0 gal remaining.
6. DRF serializes the response and returns HTTP 200 in **453 ms total turnaround**.

---

## 4. How to Verify & Review

```powershell
# 1. Run the entire automated test suite (54 tests, all mocked, ~22s)
python -m pytest

# 2. Check the live API with curl
curl.exe -X POST http://127.0.0.1:8000/api/v1/route/ `
  -H "Content-Type: application/json" `
  -d '{\"start\": \"New York, NY\", \"finish\": \"Chicago, IL\"}'
```
