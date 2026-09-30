# Phase 0: Comprehensive CSV Analysis & Architecture Findings

**Dataset File:** `fuel-prices-for-be-assessment.csv`  
**Analysis Date:** September 2026  
**Analyst:** Senior Backend Engineer  

---

## 1. Executive Summary

A comprehensive statistical and structural audit was conducted on `fuel-prices-for-be-assessment.csv` prior to designing the database schema and application pipeline. 

### Key Discoveries
1. **No Geocoordinates:** The dataset contains **zero latitude and longitude coordinates**. All proximity routing requires an offline/preprocessed geocoding solution to prevent 6,600+ external API calls at runtime.
2. **Interchange Addresses:** 96.8% (7,888 of 8,151) of addresses describe highway/interstate exits (e.g., `I-44, EXIT 283 & US-69`, `I-94, EXIT 143 & US-12`) rather than standard postal street addresses.
3. **Multiple Records Per Station:** 678 stations (`OPIS Truckstop ID`) have between 2 and 6 records, with 597 exhibiting differing retail prices for the same physical location.
4. **Geographic Scope (US & Canada):** While 7,531 records cover the 48 contiguous US states, 620 records belong to Canadian provinces (`ON`, `AB`, `BC`, `MB`, `SK`, `YT`, `QC`, `NS`, `NB`). The assessment focuses on US routes.
5. **Data Quality:** Zero null or empty cells; prices are 100% valid positive numbers ranging from **$2.6873** to **$6.3990**.

---

## 2. Statistical Findings

### 2.1 File & Row Counts
- **Total Lines in CSV:** 8,152 (1 header line + 8,151 data rows)
- **Data Rows:** 8,151
- **Columns:** 7

### 2.2 Column Schema & Data Types
| Column Name | Inferred Data Type | Postgres / Django Target | Null Count | Sample Value |
|---|---|---|---|---|
| `OPIS Truckstop ID` | Integer (64-bit safe) | `IntegerField` / `BigIntegerField` | 0 | `7`, `20`, `105` |
| `Truckstop Name` | String | `CharField(max_length=255)` | 0 | `WOODSHED OF BIG CABIN` |
| `Address` | String | `CharField(max_length=255)` | 0 | `I-44, EXIT 283 & US-69` |
| `City` | String (has trailing whitespace) | `CharField(max_length=100)` | 0 | `Big Cabin`, `New Castle` |
| `State` | String (2-letter code) | `CharField(max_length=10)` | 0 | `OK`, `WI`, `AZ` |
| `Rack ID` | Integer | `IntegerField` | 0 | `307`, `420`, `930` |
| `Retail Price` | Float / High-precision Decimal | `DecimalField(max_digits=8, decimal_places=4)` | 0 | `3.00733333`, `3.8990` |

### 2.3 Duplicates & Station Identifiers
- **Exact Duplicate Rows:** 15 distinct rows repeated, creating 26 redundant rows.
- **Unique OPIS Truckstop IDs:** 6,738
- **Stations with Multiple Records:** 678 stations (10.1% of all stations).
  - 1 record: 6,060 stations
  - 2 records: 381 stations
  - 3 records: 99 stations
  - 4 records: 63 stations
  - 5 records: 30 stations
  - 6 records: 105 stations
- **Physical Station Relationship:**
  - Every single `OPIS Truckstop ID` strictly maps to **one unique Address, City, State, and Rack ID** across the entire dataset (0 variations in location or Rack ID).
  - The only fields that vary for the same OPIS ID are `Truckstop Name` (minor name string variations across 227 stations) and `Retail Price` (varying across 597 stations).
- **Physical Locations vs OPIS IDs:**
  - Unique `(Address, City, State)`: 6,350 across the dataset (6,243 in the US).
  - 350 physical locations map to multiple OPIS IDs (e.g., co-located commercial truck lanes, dual-branded plazas such as Pilot / Flying J, or separate tenant concessions).

### 2.4 Geographic Distribution
- **Unique City/State Combinations:** 3,893 total (3,808 within the US).
- **Unique Jurisdictions:** 57
  - **48 US States:** Contiguous United States (AK and HI omitted, which matches interstate commercial trucking).
  - **9 Canadian Provinces/Territories:** `AB` (180), `BC` (121), `MB` (42), `NB` (4), `NS` (6), `ON` (217), `QC` (6), `SK` (36), `YT` (8) — total 620 rows across 112 unique Canadian OPIS IDs.
  - **US Stations Count:** 6,626 unique stations / 7,531 records.

### 2.5 Price Distribution
| Metric | Value ($/gallon) |
|---|---|
| **Minimum** | $2.6873 |
| **5th Percentile** | $2.9590 |
| **25th Percentile (Q1)** | $3.2157 |
| **50th Percentile (Median)** | $3.4323 |
| **Mean** | $3.4990 |
| **75th Percentile (Q3)** | $3.6990 |
| **90th Percentile** | $3.9790 |
| **95th Percentile** | $4.4063 |
| **Maximum** | $6.3990 |
| **Standard Deviation** | $0.4182 |

- **Intra-Station Price Differences:**
  - Stations with price variance: 597
  - Minimum price variance: $0.0006
  - Median price variance: $0.0900
  - Mean price variance: $0.1146
  - Maximum price variance: $0.9000

---

## 3. Engineering Implications & Architectural Strategy

### 3.1 Resolving Multiple Price Records per Station
- **Root Cause:** OPIS (Oil Price Information Service) feeds frequently report multiple diesel fuel grades (e.g. ultra-low sulfur diesel #2, B5/B20 biodiesel blends, cash vs credit price, or intraday price updates).
- **Strategy:** 
  The assessment requirement states: *"Fuel-stop optimization should primarily minimize fuel cost based on the provided fuel-price dataset."*
  When importing records for a given `OPIS Truckstop ID`, the application will take the **minimum retail price** (`min(Retail Price)`) as the effective price for that station, ensuring fleet routing achieves the lowest possible legal fuel cost.

### 3.2 Resolving Station Geocoding Without External Rate Limits
- **The Challenge:** The CSV provides no coordinates. Geocoding 6,626 US stations at runtime would require thousands of external requests, taking hours on free providers (e.g., Nominatim's 1 req/sec limit) and triggering immediate IP bans.
- **The Solution (Preprocessing Pipeline):**
  1. Geocode stations once during data preprocessing/import.
  2. Deliver pre-resolved station coordinates stored in a structured JSON/CSV dataset (`data/station_coordinates.json`) packaged with the repo.
  3. The `python manage.py import_fuel_data` management command checks for precomputed coordinates, falling back gracefully to city-level or geocoder caches if needed.
  4. Importing 6,600+ stations into PostgreSQL takes **less than 3 seconds** on any developer's machine without making 8,000 live HTTP calls.

### 3.3 Database Design & Spatial Indexing
- Store stations in a clean `FuelStation` model.
- Key fields: `opis_id` (primary key/unique), `name`, `address`, `city`, `state`, `rack_id`, `retail_price`, `latitude`, `longitude`.
- Indexing: Composite B-tree index on `(latitude, longitude)` and index on `retail_price`.
- Filtering: Bounding-box pre-filtering in SQL (`lat BETWEEN min_lat AND max_lat AND lon BETWEEN min_lon AND max_lon`) drastically narrows down candidates from 6,600+ to ~50–150 stations along the route corridor before applying exact Shapely polyline cross-track distance calculations.

### 3.4 Runtime Request Flow & External Call Budget
To strictly satisfy: *"Minimize calls to external routing/map APIs: One routing API call is ideal; two or three external calls are acceptable"*:
1. **User Request:** `POST /api/v1/route/` with `start` and `finish` location strings.
2. **Geocoding (Max 2 external calls, 0 if cached):** 
   - Check local cache (Redis/Django cache) for `start` and `finish`.
   - Call free geocoder (Nominatim / Photon / US Census) only on cache misses.
   - Validate both locations are inside the USA bounding polygon.
3. **Routing (Exactly 1 external call, 0 if cached):**
   - Call OSRM public route API with `(start_lon, start_lat)` to `(finish_lon, finish_lat)` requesting full GeoJSON geometry.
4. **Local Processing (0 external calls):**
   - Filter stations within `MAX_STATION_DISTANCE_FROM_ROUTE_MILES` (e.g. 5 miles) using local PostgreSQL bounding box + Shapely distance.
   - Project candidate stations onto the route line to determine their sequential distance along the route.
5. **Fuel Optimization (0 external calls):**
   - Execute deterministic fuel optimization algorithm considering 500-mile vehicle range, 10 MPG, 50-gallon tank, starting full.
6. **Total External Calls:** **1 to 3 calls total** on a cold request; **0 calls** on a fully cached request!
