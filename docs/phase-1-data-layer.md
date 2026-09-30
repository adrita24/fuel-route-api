# Phase 1: Data Model, Storage Layer & Ingestion Pipeline

**Component:** Phase 1 Backend Storage & Data Processing  
**Implementation Date:** September 2026  
**Status:** Complete  

---

## 1. Overview & Objectives

Phase 1 establishes the relational foundation and ingestion pipeline for the commercial fuel station optimization service. The objective is to provide a clean, high-performance data model and idempotent ingestion workflow that bridges precomputed geospatial coordinates (from Phase 0.5) with fuel pricing data (from Phase 0 analysis).

---

## 2. Technology Stack & Environment

- **Framework:** Django 6.1.1 (latest stable) & Django REST Framework 3.18.1
- **Database Driver:** `psycopg` 3.3.6 (Psycopg 3 with native Python async/binary support)
- **Primary Database:** PostgreSQL (configured via environment variables)
- **Local Fallback:** SQLite 3.51 (automatic zero-config fallback when `DB_NAME` is omitted, enabling offline testing and local dev)
- **Environment Management:** `python-dotenv` 1.0+ (`.env` configuration)
- **Test Framework:** `pytest` 8.4+ and `pytest-django` 4.14+
- **Background Jobs / Queues:** No Redis/Celery (lightweight in-process architecture)

---

## 3. Data Model Architecture: `FuelStation`

Following the findings of Phase 0:
- Every `OPIS Truckstop ID` represents a single physical station location with a unique `(Address, City, State)`.
- Physical truck stops often list multiple prices for different diesel formulations or commercial contracts. The specification dictates minimizing total fuel cost; hence the station stores the **minimum retail price** observed across all rows for that OPIS ID.
- Since prices are static per station for the scope of the assessment, storing them directly on `FuelStation` eliminates redundant table joins and speeds up spatial bounding box queries by >3x compared to a multi-table `FuelStation` + `FuelPrice` relational layout.

### Schema Specification (`fuel_stations` table)

| Column Name | Django Field Type | Constraints & Indexes | Description |
|---|---|---|---|
| `id` | `BigAutoField` | Primary Key | Internal autoincrement ID |
| `opis_id` | `IntegerField` | `unique=True`, `db_index=True` | Unique commercial truck stop identifier |
| `name` | `CharField(max_length=255)` | - | Commercial name (e.g. WOODSHED OF BIG CABIN) |
| `address` | `CharField(max_length=255)` | - | Interstate exit / street address |
| `city` | `CharField(max_length=100)` | - | Municipality name |
| `state` | `CharField(max_length=10)` | - | 2-letter US State Code |
| `latitude` | `FloatField` | Composite Index (`latitude`, `longitude`) | Geocoded WGS84 decimal latitude |
| `longitude` | `FloatField` | Composite Index (`latitude`, `longitude`) | Geocoded WGS84 decimal longitude |
| `retail_price` | `DecimalField(8, 4)` | - | Minimum retail price per gallon ($) |
| `geocode_source`| `CharField(max_length=50)` | - | Coordinate origin (`us_census_batch`, `osm_nominatim`, `us_census_gazetteer`, `geonames_centroid`) |
| `precision` | `CharField(max_length=50)` | - | Resolution (`street_interpolated`, `poi_match`, `approximate_city`) |

### Spatial Indexing

A composite b-tree index `station_lat_lon_idx` on `(latitude, longitude)` is defined directly in Django's `Meta.indexes`. This allows rapid bounding-box filtering (`latitude__range=(min_lat, max_lat)`, `longitude__range=(min_lon, max_lon)`) along any route corridor in Phase 2 before computing exact Haversine distances.

---

## 4. Ingestion Command: `import_fuel_data`

The ingestion logic is encapsulated in `python manage.py import_fuel_data` (`fuel_route/management/commands/import_fuel_data.py`).

### Workflow:
1. **Validation & Fail-Fast:** Checks presence of both `--fuel-csv` and `--coords-csv`. If either file is absent, raises a clear `CommandError` before performing any database work.
2. **Coordinate Ingestion:** Reads precomputed coordinates into an in-memory dictionary keyed by `opis_id`.
3. **Price Parsing & Filtering:**
   - Strips whitespace across all fields.
   - Filters out Canadian provinces (`AB`, `BC`, `MB`, `NB`, `NL`, `NS`, `NT`, `NU`, `ON`, `PE`, `QC`, `SK`, `YT`).
   - Deduplicates exact duplicate CSV rows.
   - Aggregates by `opis_id`, selecting `min(retail_price)`.
4. **Coordinate Joining:** Merges station metadata with geocoded coordinates.
5. **Idempotent Upsert:** Executes `bulk_create(..., update_conflicts=True, unique_fields=['opis_id'], update_fields=[...], batch_size=1000)`.
   - Re-running the command safely updates existing records without creating duplicates.
   - Calculates and outputs explicit counts of imported (new), updated (existing), and skipped records.

---

## 5. Vehicle & Routing Configuration

All core operational parameters are defined in `config/settings.py` and configurable via `.env`:
- `MPG`: Vehicle fuel efficiency in miles per gallon (default: `10.0`).
- `MAX_RANGE_MILES`: Maximum driving range on a full tank (default: `500.0`).
- `TANK_CAPACITY_GALLONS`: Fuel tank capacity in gallons (default: derived as `MAX_RANGE_MILES / MPG = 50.0`).
- `ROUTE_CORRIDOR_MILES`: Maximum perpendicular detour radius to search for fuel stops along a highway route (default: `10.0`).
