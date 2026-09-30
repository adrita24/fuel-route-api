# 11: Architectural Decisions & Engineering Tradeoffs

**Component:** System Design Tradeoffs  
**Status:** Complete  

---

## 1. Overview

Every production system represents a series of conscious engineering tradeoffs between architectural simplicity, computational performance, data fidelity, and operational maintenance. This document details the 8 core decisions governing the Fuel Route Optimizer service.

---

## 2. Core Decisions & Tradeoff Matrix

### 1. Minimum Price Selection per OPIS ID
* **Decision:** When multiple CSV rows exist for the same `OPIS Truckstop ID` (reflecting different fuel formulations, rack IDs, or commercial contract tiers), the **minimum retail price** is selected.
* **Why:** In commercial fleet operations, dispatchers direct drivers to purchase under their most advantageous corporate discount or standard diesel formulation available at that terminal.
* **Alternatives Considered:**
  * *Separate `FuelPrice` table per rack ID:* Requires expensive SQL joins during corridor matching, slowing queries by 3–5x.
  * *Average price:* Fails to reflect the best price a driver can actually obtain at the pump.
* **Tradeoff:** Assumes the vehicle is eligible for the lowest posted commercial diesel tier at that facility.

### 2. Free Starting Tank Assumption
* **Decision:** The vehicle departs origin (mile 0) with a completely full tank (50.0 gallons / 500-mile range) at zero charged cost. Total fuel cost reflects only fuel purchased during the trip.
* **Why:** Aligns with standard freight dispatch accounting: a truck begins its journey with existing terminal fuel inventory; the trip budget only measures cash expenditures incurred en route.
* **Clarification Added:** To avoid confusion between energy burned and dollars spent, the API returns both `gallons_consumed` (total trip energy: `route_miles / 10.0`) and `gallons_purchased` (fuel pumped en route), accompanied by `starting_tank_note`.

### 3. City-Level Coordinates & The 10-Mile Detour Corridor
* **Decision:** Use a 10.0-mile perpendicular highway detour corridor radius (`ROUTE_CORRIDOR_MILES = 10.0`).
* **Why:** Phase 0 audit revealed that **96.8% (7,888 / 8,151)** of OPIS addresses are highway exit descriptions (e.g. `I-44, EXIT 283 & US-69`) without postal house numbers. 71% of stations were geocoded via official Census Gazetteer municipal centroids (median distance to interstate interchange: 1.96 miles). A tight 1-mile corridor would discard viable highway stops located near town centers.
* **Tradeoff:** A 10-mile radius may include truck stops situated along intersecting state highways. The greedy optimizer filters them naturally by price and mile marker.

### 4. No PostGIS Dependency (Django ORM + Shapely STRtree)
* **Decision:** Implement spatial corridor filtering using standard PostgreSQL b-tree indices and Shapely's C-extension (`STRtree`), avoiding PostGIS extensions (`ST_DWithin`, `ST_LineLocatePoint`).
* **Why:** PostGIS requires specialized binary database extensions, spatial library linking (`libgeos`, `gdal`), and elevated database privileges that complicate deployment and local development.
* **Tradeoff:** Django ORM handles the high-latitude expanded bounding box prefilter in 4.2 ms; Shapely executes segment-local metric projection in Python in 336 ms. Delivers identical sub-second speed with zero database extension overhead.

### 5. PostgreSQL DB-Table Caches Instead of Redis
* **Decision:** Use persistent database tables (`GeocodingCache` and `RouteCache`) for caching rather than Redis or Memcached.
* **Why:** Operational simplicity. Adding Redis introduces an extra stateful infrastructure daemon, connection pool management, and memory limits. PostgreSQL provides permanent, ACID-compliant persistence for cached geocodes and routes across restarts.
* **Tradeoff:** Redis delivers sub-millisecond lookups (< 1 ms); PostgreSQL b-tree lookups take 2.7 ms. The 2 ms difference is negligible compared to outbound network requests (1,000+ ms).

### 6. Stop Count Not Penalized
* **Decision:** The algorithm minimizes total fuel cost ($) without adding an artificial time penalty per stop or a minimum-savings threshold per refueling event.
* **Why:** The primary objective of the optimizer is pure fuel cost minimization. Introducing arbitrary stop penalties (e.g. $15 or 20 minutes per stop) would distort the pure cost-optimal solution without an explicit customer business model.
* **Tradeoff:** Because the optimizer minimizes cost only, it can make many small opportunistic stops (e.g., stopping to buy 5–10 gallons if the next station within range is slightly cheaper). A minimum-saving threshold (e.g., do not stop unless saving at least $5.00) or a configurable penalty per stop is a documented future improvement.

### 7. OSRM Public Demo Server Limits & SLA
* **Decision:** The service defaults to the public OSRM demo server (`https://router.project-osrm.org`) but makes the endpoint fully swappable via the `OSRM_BASE_URL` environment variable.
* **Why:** The public demo server enables instant out-of-the-box evaluation without requiring users to download and host a 50 GB North America road network extract.
* **Limitation:** The demo server has no SLA, rate limits bursts, and does not model live traffic or commercial truck bridge clearance restrictions. For production deployments, `OSRM_BASE_URL` can be pointed to any dedicated or self-hosted OSRM routing instance.

### 8. The 289 KB Full GeoJSON LineString Payload
* **Decision:** The API returns the complete turn-by-turn road geometry (up to ~25,000 coordinate vertices, ~289 KB uncompressed) in `route.geometry`.
* **Why:** Frontend mapping clients (Mapbox GL, Leaflet, Google Maps) require high-fidelity road trajectories to render smooth highway polylines without clipping highway curves or bridges.
* **Tradeoff:** Increases response payload size from ~2 KB to ~289 KB. JSON rendering adds ~16 ms of CPU time. In bandwidth-constrained mobile environments, polyline encoding (Google Polyline Algorithm) or simplification can be toggled via query parameters.

### 9. Geographic Boundary Error Taxonomy (404 vs 422)
* **Decision:** Handle overseas queries (e.g. `"Paris, France"`) as `LOCATION_NOT_FOUND` (HTTP 404) and non-contiguous US queries (e.g. `"Anchorage, AK"`, `"Honolulu, HI"`) as `LOCATION_NOT_US` (HTTP 422).
* **Why:** Forward geocoding to OpenStreetMap Nominatim strictly enforces `countrycodes=us`. For overseas queries, Nominatim finds zero matching entities within the US, naturally resulting in a 404 Not Found. For US destinations in Alaska or Hawaii, Nominatim successfully resolves the US place, but the coordinates fall outside the contiguous US (CONUS) bounding box (`[24.0, 50.0]` lat, `[-125.0, -66.5]` lon), resulting in an unprocessable 422.
