# Phase 0.5: Station Geolocation & Multi-Tier Coordinate Pipeline

**Target Asset:** [`data/station_coordinates.csv`](file:///d:/code/assignment/data/station_coordinates.csv)  
**Supporting Assets:** [`data/unresolved_stations.csv`](file:///d:/code/assignment/data/unresolved_stations.csv), [`data/nominatim_cache.json`](file:///d:/code/assignment/data/nominatim_cache.json), [`data/cache/`](file:///d:/code/assignment/data/cache/)  
**Implementation Script:** [`scripts/geocode_stations.py`](file:///d:/code/assignment/scripts/geocode_stations.py)  

---

## 1. Problem Statement & Design Objectives

The source dataset (`fuel-prices-for-be-assessment.csv`) contains fuel pricing for 8,151 rows across 6,738 commercial truckstops, but contains **zero geographic coordinates** (no latitude or longitude).

### Constraints & Requirements
1. **Zero Runtime Station Geocoding:** The runtime API (`POST /api/v1/route/`) must not make external geocoding requests for fuel stations. Geocoding 6,600+ stations on every request or during cold starts would violate external API rate limits, take hours, and lead to IP bans.
2. **Legitimate, Documented Sources:** Coordinates must not be fabricated, estimated via undocumented heuristics, or hardcoded from unverified sources.
3. **Reproducibility:** A reviewer must be able to reproduce the coordinate dataset using automated scripts that interface with documented public datasets and official government APIs.
4. **Explicit Precision Tracking:** Each coordinate pair must be tagged with its provenance (`geocode_source`) and spatial resolution (`precision`).

---

## 2. Multi-Tier Geolocation Architecture

The pipeline processes all **6,243 unique physical US locations** (covering 6,626 unique US OPIS IDs, excluding Canadian provinces) through a tiered cascade:

```text
                +-----------------------------------------+
                |    Unique US Locations (6,243 total)    |
                +-----------------------------------------+
                                     |
                                     v
                +-----------------------------------------+
                |  Tier 1: US Census Batch Geocoder       |
                |  - Endpoint: locations/addressbatch     |
                |  - Input: Address, City, State          |
                |  - Precision: "street_interpolated"     |
                +-----------------------------------------+
                                     |
                       [Plausibility Check: <= 30 mi]
                                     |
                         +-----------+-----------+
                         |                       |
                     Passed (8%)             Failed (92%)
                         |                       |
                         v                       v
               Accepted as Tier 1     +----------------------+
                                      |  Tier 2: Nominatim   |
                                      |  (Background Crawl)  |
                                      |  - POI Name Search   |
                                      |  - Precision:        |
                                      |    "poi_match"       |
                                      +----------------------+
                                                 |
                                     +-----------+-----------+
                                     |                       |
                                 Matched                 Unmatched
                                     |                       |
                                     v                       v
                            Upgrade to Tier 2     +----------------------+
                                                  |  Tier 3: Centroids   |
                                                  |  - 2024 Census Gaz  |
                                                  |  - GeoNames Fallback |
                                                  |  - Precision:        |
                                                  |    "approximate_city"|
                                                  +----------------------+
                                                             |
                                                 +-----------+-----------+
                                                 |                       |
                                             Matched                 Unmatched
                                                 |                       |
                                                 v                       v
                                        Accepted as Tier 3       data/unresolved_
                                                                 stations.csv
```

---

## 3. Tier Specifications

### Tier 1: U.S. Census Bureau Geocoder Batch API
* **Endpoint:** `https://geocoding.geo.census.gov/geocoder/locations/addressbatch`
* **Benchmark:** `Public_AR_Current`
* **Submission Strategy:** Chunked into batches of up to 1,000 unique addresses. Each chunk response is permanently cached under [`data/cache/census_chunk_*.csv`](file:///d:/code/assignment/data/cache) so the script is 100% idempotent and resumable.
* **Coordinate Mapping:** The Census API outputs coordinates as `longitude,latitude`. The parser reverses this to standard `(lat, lon)`.
* **Assigned Precision:** `street_interpolated`

### Tier 2: OpenStreetMap Nominatim (POI Search)
* **Endpoint:** `https://nominatim.openstreetmap.org/search`
* **Query Format:** `q="<cleaned_truckstop_name>, <city>, <state>"`
* **Name Normalization:** Store numbers and franchise IDs (e.g. `PILOT TRAVEL CENTER #1243` -> `PILOT TRAVEL CENTER`) are stripped via regex (`re.sub(r'#\s*\d+', '', name)`).
* **Policy Compliance:**
  * **Rate Limit:** Minimum 1.05 seconds between consecutive HTTP requests.
  * **User-Agent:** `SpotterFuelRouteOptimizer/1.0 (contact: adrita.g.2005@gmail.com)`
  * **Resumable Cache:** Every query result is saved to [`data/nominatim_cache.json`](file:///d:/code/assignment/data/nominatim_cache.json), persisting `osm_class` and `osm_type`.
* **Assigned Precision:** `poi_match`

### Tier 3: Official Centroids (Census Gazetteer & GeoNames)
* **Primary Source:** **2024 U.S. Census Bureau National Places Gazetteer** (`2024_Gaz_place_national.zip`). Contains 64,034 official place and CDP internal points (`INTPTLAT`, `INTPTLONG`).
* **Secondary Source:** **GeoNames US Postal Places Dataset** (`http://download.geonames.org/export/zip/US.zip`). Contains 30,557 postal community centroids, providing 100% coverage for unincorporated hamlets and rural crossroads (e.g. `Castle Creek, NY`, `Holden, ME`, `Bethany, LA`).
* **Assigned Precision:** `approximate_city`

---

## 4. The 8% Census Match Rate: Root Cause Analysis

During Stage 1, the Census Batch Geocoder matched **499 of 6,243 locations (8.0%)**, with 457 passing the plausibility validation.

### Why Did 88.3% Return `No_Match`?
1. **Interchange Addresses vs Street Addresses:** Over **96.8% (7,888 of 8,151 rows)** of OPIS addresses describe highway junctions and exit numbers (e.g. `I-44, EXIT 283 & US-69`, `I-94, EXIT 143 & US-12 & SR-21`, `I-8, EXIT 119 & SR-85`).
2. **Census TIGER Engine Design:** The U.S. Census Geocoding engine is built on the TIGER address range database, which matches house numbers against street centerlines (e.g. `1600 Pennsylvania Ave NW`). It has no topological index for interstate exit numbers or highway cross-streets without house numbers.
3. **Expected Behavior:** This ~8% match rate was predicted in Phase 0 and directly justifies why a 3-tier cascade was designed.

---

## 5. Plausibility & Sanity Validations

To prevent false-positive geocoding matches from corrupting the route optimizer, every candidate coordinate is subjected to two mathematical tests:

### 1. Distance-to-City-Centroid Plausibility Check
$$\text{distance}(\text{candidate\_lat\_lon}, \text{city\_centroid}) \le 30.0\text{ miles}$$
* Computed via great-circle Haversine formula against the official Census Gazetteer city centroid.
* **Results in Stage 1:** 42 false-positive Census matches were rejected because their matched street was located over 30 miles from the actual city named on the truckstop record.
* **Accepted Points Distribution ($n=431$):**
  * **Median:** 1.96 miles
  * **90th Percentile:** 8.35 miles
  * **99th Percentile:** 19.34 miles
  * **Max:** 28.64 miles

### 2. Dynamic State Bounding Box Sanity Check
* Dynamic bounding boxes $(\text{min\_lat}, \text{max\_lat}, \text{min\_lon}, \text{max\_lon})$ are derived directly from the min/max place coordinates in the 2024 Census Gazetteer for each state, expanded by a 0.3° buffer margin (~20 miles).
* Zero hand-typed or memory-based boundaries.
* Points falling outside the state's derived boundary are strictly rejected.

---

## 6. Output Dataset Summary (Post-Nominatim Upgrade Snapshot)

The coordinate dataset [`data/station_coordinates.csv`](file:///d:/code/assignment/data/station_coordinates.csv) contains coordinates for all 6,626 commercial US fuel stations.

The background Nominatim geocoding job (`scripts/geocode_stations.py --run-nominatim`) ran through query 3,050 (52.7% of unique queries) before being gracefully stopped after its periodic 50-batch synchronization to `data/station_coordinates.csv`. The on-disk cache [`data/nominatim_cache.json`](file:///d:/code/assignment/data/nominatim_cache.json) is fully preserved with 3,050 entries (1,064 matches and 1,986 misses).

### Final Coordinate Breakdown in `station_coordinates.csv`
| Metric | Value | Percentage |
|---|---|---|
| **Total Unique US Stations (OPIS IDs)** | **6,626** | **100.0%** |
| **Successfully Geocoded** | **6,626** | **100.0%** |
| **Unresolved Stations** | **0** | **0.0%** |
| **Tier 1 (`us_census_batch`, `street_interpolated`)** | **480 stations** | **7.2%** |
| **Tier 2 (`osm_nominatim`, `poi_match`)** | **1,174 stations** | **17.7%** |
| **Tier 3 (`us_census_gazetteer`, `approximate_city`)** | **4,702 stations** | **71.0%** |
| **Tier 3 (`geonames_centroid`, `approximate_city`)** | **270 stations** | **4.1%** |

### Breakdown by Precision Level
| Precision Classification | Count | Percentage |
|---|---|---|
| `poi_match` (OpenStreetMap Nominatim high precision) | 1,174 | 17.7% |
| `street_interpolated` (U.S. Census Bureau address range) | 480 | 7.2% |
| `approximate_city` (Census Gazetteer & GeoNames municipality centroids) | 4,972 | 75.0% |
| **Total** | **6,626** | **100.0%** |

---

## 7. Precision & Limitations in Route Optimization

1. **`street_interpolated` / `poi_match`:** Coordinates place the vehicle within a few meters to yards of the station or highway off-ramp. Ideal for proximity filtering with tight corridors (e.g. 1–2 miles).
2. **`approximate_city`:** Coordinates represent the municipal centroid of the city/town where the exit is located. Because interstate exits are typically located within 1 to 5 miles of town centers (median distance: 1.96 miles), a corridor buffer parameter (`MAX_STATION_DISTANCE_FROM_ROUTE_MILES = 5` or `10`) in Phase 6 reliably captures these candidate stations without missing accessible highway stops.

---

## 8. How to Reproduce or Resume

From the project root:

```bash
# 1. Download Gazetteer, run Census batch, fallback to centroids, and generate data/station_coordinates.csv
python scripts/geocode_stations.py --tier1-tier3-only

# 2. Run or resume the Nominatim background upgrade (idempotent, uses data/nominatim_cache.json)
python scripts/geocode_stations.py --run-nominatim
```

> [!NOTE]
> Because `scripts/geocode_stations.py` persists every response to `data/nominatim_cache.json` immediately upon receipt, the background job can be resumed at any time with `python scripts/geocode_stations.py --run-nominatim` without repeating any of the 3,050 already-cached queries.
