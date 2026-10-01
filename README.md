# Fuel Route Optimizer Service

A Python & Django backend service that calculates optimal, cost-effective fuel stops for commercial trucking routes across the continental United States.

---

## 📚 Technical Documentation Index

| Document | Topic | Description |
|---|---|---|
| 📋 [ASSESSMENT_CHECKLIST.md](file:///d:/code/assignment/ASSESSMENT_CHECKLIST.md) | **Compliance** | Full requirement-by-requirement specification compliance matrix |
| 🧭 [DEVELOPER_WALKTHROUGH.md](file:///d:/code/assignment/DEVELOPER_WALKTHROUGH.md) | **Reviewer Guide** | Codebase tour, module architecture, and request execution trace |
| 🚀 [01-project-overview.md](file:///d:/code/assignment/docs/01-project-overview.md) | **Overview** | Business motivation, freight fuel economics, problem constraints |
| 🏗️ [02-architecture.md](file:///d:/code/assignment/docs/02-architecture.md) | **Architecture** | End-to-end request lifecycle and subsystem interaction diagram |
| 🌐 [04-geocoding.md](file:///d:/code/assignment/docs/04-geocoding.md) | **Geocoding** | OSM Nominatim client, 1.05s rate limiter, CONUS bounding box |
| 🛣️ [05-routing.md](file:///d:/code/assignment/docs/05-routing.md) | **Routing** | OSRM driving engine integration, GeoJSON geometry extraction |
| ⛽ [06-fuel-station-selection.md](file:///d:/code/assignment/docs/06-fuel-station-selection.md) | **Spatial Pipeline** | SQL BBox prefilter & Shapely STRtree metric projection (<0.001% distortion) |
| 🧠 [07-optimization-algorithm.md](file:///d:/code/assignment/docs/07-optimization-algorithm.md) | **Optimizer** | Greedy lookahead with local minimum filling & worked examples |
| 🔌 [08-api.md](file:///d:/code/assignment/docs/08-api.md) | **REST API** | Endpoint specification, response schemas, and cURL examples |
| ⚡ [09-performance.md](file:///d:/code/assignment/docs/09-performance.md) | **Benchmarks** | Micro-profiling breakdown (5.6s cold vs 0.45s cached) |
| 🧪 [10-testing.md](file:///d:/code/assignment/docs/10-testing.md) | **Testing** | Automated testing strategy (54 tests, 100% mocked offline) |
| ⚖️ [11-decisions-and-tradeoffs.md](file:///d:/code/assignment/docs/11-decisions-and-tradeoffs.md) | **Tradeoffs** | 8 architectural decisions (No PostGIS, DB cache vs Redis, etc.) |
| 💻 [12-locally-running-the-project.md](file:///d:/code/assignment/docs/12-locally-running-the-project.md) | **Setup Guide** | Step-by-step Windows setup, database, migrations, and execution |

---

### What Was Added and Why:
1. **Django Project & Configuration (`config/`):**
   - Built on **Django 6.1.1** (latest stable release) with **Django REST Framework 3.18.1**.
   - Modular settings structure in `config/settings.py` configured via environment variables.
   - Clean, lightweight architecture with **no Redis or Celery overhead**.
2. **PostgreSQL Database with Safe SQLite Fallback:**
   - Powered by `psycopg` 3.3.
   - Configured through standard environment variables (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).
   - If PostgreSQL credentials are not provided (e.g. initial setup or local unit testing), the application gracefully falls back to local SQLite (`db.sqlite3`), ensuring zero-friction local development.
3. **Optimized `FuelStation` Model (`fuel_route/models.py`):**
   - Encapsulates station identity (`opis_id`), location (`address`, `city`, `state`, `latitude`, `longitude`), and pricing (`retail_price`).
   - Stores geocoding metadata (`geocode_source`, `precision`) to track coordinate reliability.
   - **No separate `FuelPrice` table:** As established in the Phase 0 audit, physical stations maintain static prices for the purpose of the route calculation. Storing the minimum retail price directly on `FuelStation` avoids expensive SQL joins and accelerates spatial queries.
   - **Composite Spatial Index:** A composite b-tree index on `(latitude, longitude)` enables sub-millisecond bounding box lookups along route corridors.
4. **Idempotent Ingestion Command (`import_fuel_data`):**
   - Command: `python manage.py import_fuel_data [--fuel-csv <path>] [--coords-csv <path>]`
   - Excludes Canadian province rows (`AB`, `BC`, `MB`, `NB`, `NL`, `NS`, `NT`, `NU`, `ON`, `PE`, `QC`, `SK`, `YT`).
   - Deduplicates exact duplicate CSV rows.
   - Computes minimum price per station (`OPIS Truckstop ID`).
   - Merges station data with precomputed geocoded coordinates.
   - Performs an idempotent upsert (`bulk_create(..., update_conflicts=True)`), safely updating prices and metadata without row duplication.
   - Provides early fail-fast validation if input CSVs are missing.
5. **Route & Vehicle Optimization Configuration:**
   - Default parameters defined in `config/settings.py` and overrideable via environment variables:
     - `MPG = 10.0`
     - `MAX_RANGE_MILES = 500.0`
     - `TANK_CAPACITY_GALLONS = 50.0` (derived as `MAX_RANGE_MILES / MPG`)
     - `ROUTE_CORRIDOR_MILES = 10.0`
6. **Comprehensive Automated Test Suite:**
   - Powered by `pytest` and `pytest-django`.
   - Comprehensive test cases covering minimum price selection, Canadian station filtering, row deduplication, idempotent re-runs, missing coordinate handling, and model constraints using isolated fixtures.

---

## 2. Phase 2: External Services Architecture (Geocoding & Routing)

Phase 2 introduces dedicated external service modules (`fuel_route/services/`) for forward geocoding and driving route calculations:

1. **Forward Geocoding Service (`fuel_route/services/geocoding.py`):**
   - **Provider:** OpenStreetMap Nominatim Search API (`countrycodes=us`).
   - **Contiguous US (CONUS) Validation:** Validates that resolved coordinates fall within the contiguous US bounding box (`[24.0, 50.0]` lat, `[-125.0, -66.5]` lon) derived from 2024 US Census Gazetteer data. Rejects out-of-coverage queries with `NonUSLocationError` (HTTP 422).
   - **Persistent Caching (`geocoding_cache`):** Caches normalized, whitespace-collapsed lowercase queries permanently in PostgreSQL. No repeated external network calls are made for cached queries.
   - **Rate Limiting & Safety:** Enforces $\ge 1.05$-second spacing between outgoing requests via an in-process thread-safe lock. Strictly requires `GEOCODER_CONTACT_EMAIL` for User-Agent compliance.
   - **No Negative Caching:** Failures, timeouts, and rate limits are never cached.
   - **Concurrency Safety:** Employs `get_or_create` with `IntegrityError` handling to eliminate cache insert race conditions.
2. **Driving Route Service (`fuel_route/services/routing.py`):**
   - **Provider:** Open Source Routing Machine (OSRM) Driving API.
   - **Single Query:** Requests full route geometry (`overview=full`, `geometries=geojson`, `steps=false`) and extracts total distance in miles (`meters * 0.000621371`), duration in seconds, and GeoJSON LineString coordinates.
   - **Persistent Caching (`route_cache`):** Caches routes permanently in PostgreSQL using canonical keys rounded to 4 decimal places (~11 meters).
   - **Swappable Endpoint (`OSRM_BASE_URL`):** Defaults to public demo server (`https://router.project-osrm.org`), fully swappable for dedicated or self-hosted OSRM instances.
3. **Three-Tier Persistent Caching Architecture:**
   - **`GeocodingCache` (`geocoding_cache`):** Permanent cache for forward geocoding results, keyed by normalized lowercase query strings.
   - **`RouteCache` (`route_cache`):** Permanent cache for OSRM driving routes and GeoJSON geometries, keyed by start/finish coordinates rounded to 4 decimals (~11m).
   - **`StationMatchCache` (`station_match_cache`):** Persistent cache for candidate fuel stations along a route corridor, keyed by `route_key|corridor_miles`. Reduces station-matching time on repeat routes from ~390 ms down to ~4.5 ms (88x speedup). Automatically invalidated during `import_fuel_data` runs.
4. **Structured Error Taxonomy (`fuel_route/services/exceptions.py`):**
   - Maps domain exceptions to specific error codes and HTTP statuses (`MISSING_INPUT` [400], `LOCATION_NOT_FOUND` [404], `LOCATION_NOT_US` [422], `NO_ROUTE_FOUND` [422], `GEOCODER_RATE_LIMITED` [429], `GEOCODER_ERROR` [502], `ROUTING_ERROR` [502], `GEOCODER_TIMEOUT` [504], `ROUTING_TIMEOUT` [504]).
4. **Service Tradeoffs & Operational Notes:**
   - *In-Process Rate Limiter Limitation:* The 1.05s Nominatim rate limiter operates within a single Python process. Multi-process production deployments (e.g. Gunicorn/uWSGI workers) should synchronize requests via Redis or an outbound proxy.
   - *OSRM Public Demo Server SLA:* The public demo OSRM instance provides no SLA or uptime guarantee. For production deployments, `OSRM_BASE_URL` can be pointed to a dedicated or self-hosted OSRM backend.
   - *Mocked Test Suite:* All unit tests mock HTTP calls via `unittest.mock.patch`; no live external network requests are made during testing.

---

## 3. Core Assumptions

1. **Minimum Retail Price:** Truck stops frequently list separate rows for different fuel formulations, rack IDs, or commercial contracts. Per the project specification, the minimum retail price observed across all rows for a given `OPIS Truckstop ID` is treated as the station's price per gallon.
2. **Starting Fuel State:** The commercial vehicle begins each route with a completely full tank (`50.0` gallons / `500.0` miles range).
4. **Final Coordinate Tier Counts:** Station coordinates in `data/station_coordinates.csv` were produced via a multi-tier geocoding pipeline (Census batch, OpenStreetMap Nominatim POI matching, and Census Gazetteer/GeoNames municipal centroids). The final counts are:
   - **`osm_nominatim` (`poi_match`):** 1,174 stations (17.7%)
   - **`us_census_batch` (`street_interpolated`):** 480 stations (7.2%)
   - **`us_census_gazetteer` (`approximate_city`):** 4,702 stations (71.0%)
   - **`geonames_centroid` (`approximate_city`):** 270 stations (4.1%)
   - **Total:** 6,626 stations (100.0% coverage of US commercial stations)

---

## 3. Windows Execution Steps

### Prerequisites
- Python 3.11+ (Python 3.13 / Anaconda supported)
- PowerShell or Windows Command Prompt

### Step 1: Install Dependencies
```powershell
pip install -r requirements.txt
```

### Step 2: Environment Configuration (PostgreSQL)
The application enforces strict database configuration: PostgreSQL is required by default. If `DB_NAME` or `DB_USER` are missing, Django raises an `ImproperlyConfigured` error immediately (unless `USE_SQLITE=1` is explicitly passed for offline test execution).

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Configure your PostgreSQL connection in `.env` (never commit `.env`):
   ```ini
   DB_NAME=fuel_route
   DB_USER=postgres
   DB_PASSWORD=your_postgres_password
   DB_HOST=localhost
   DB_PORT=5432
   ```

3. **Database Creation on Windows:**
   - If `psql` is on your PATH (or at `C:\Program Files\PostgreSQL\18\bin\psql.exe`):
     ```powershell
     & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE fuel_route;"
     ```
   - Or using Python and `psycopg` directly (non-interactive, connects to maintenance database `postgres` and creates `fuel_route` safely):
     ```powershell
     python -c "import os, psycopg; from dotenv import load_dotenv; load_dotenv(); conn = psycopg.connect(dbname='postgres', user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'), host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'), autocommit=True); cur = conn.cursor(); cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (os.getenv('DB_NAME'),)); (cur.execute('CREATE DATABASE ' + os.getenv('DB_NAME')) if not cur.fetchone() else None); conn.close()"
     ```

### Step 3: Run Database Migrations (PostgreSQL)
```powershell
python manage.py migrate
```

### Step 4: Run Automated Tests
```powershell
python -m pytest
```
*(To run tests offline using SQLite without connecting to PostgreSQL, pass `USE_SQLITE=1`)*:
```powershell
$env:USE_SQLITE="1"; python -m pytest; Remove-Item env:USE_SQLITE
```

### Step 5: Import Fuel & Coordinate Data
```powershell
python manage.py import_fuel_data
```
To test with custom or small fixture CSVs:
```powershell
python manage.py import_fuel_data --fuel-csv path/to/fuel.csv --coords-csv path/to/coords.csv
```
