# 01: Project Overview

**Component:** System Overview & Business Context  
**Service:** Fuel Route Optimizer API  
**Status:** Production Ready  

---

## 1. Problem Statement & Motivation

In long-haul commercial freight transportation, diesel fuel represents **30% to 40% of total operating expenses**. Retail diesel prices fluctuate dramatically across the United States—ranging from **$2.68 to $6.40 per gallon** (over a $3.70/gal spread) depending on state excise taxes, highway proximity, and regional refinery logistics.

For a long-haul commercial truck traveling from Los Angeles to New York (~2,800 miles) consuming ~280 gallons of diesel, an unoptimized fueling strategy using random highway exits can easily waste **$400 to $800+ per trip**.

### The Challenge
Given:
* An origin and destination query anywhere in the continental United States.
* A commercial vehicle with a **500-mile driving range**, **10.0 MPG** fuel efficiency, and a derived **50.0-gallon** fuel tank.
* A starting condition where the vehicle departs with a completely **full tank (50.0 gal)** at no charged cost.
* A dataset of **6,626 commercial truck stops** with fluctuating retail prices across the country.

**Objective:** Automatically calculate the driving route, discover viable fuel stations within a highway detour corridor, and compute the cheapest sequence of fuel stops—including exact gallons to pump at each stop—ensuring the vehicle **never runs out of fuel** while strictly minimizing total trip expenditure.

---

## 2. Key Constraints & Requirements

| Parameter | Value | Description |
|---|---|---|
| **Vehicle MPG** | `10.0` | Constant linear fuel consumption ($0.1\text{ gal/mile}$). |
| **Max Tank Range** | `500.0 miles` | Maximum distance vehicle can drive on a full tank. |
| **Tank Capacity** | `50.0 gallons` | Derived as $\text{MAX\_RANGE\_MILES} / \text{MPG}$. |
| **Corridor Radius** | `10.0 miles` | Perpendicular highway cross-track detour corridor. |
| **Starting Fuel** | `50.0 gallons` | Vehicle departs origin with full tank (free starting inventory). |
| **Feasibility Invariant** | $\le 500.0\text{ miles}$ | Every leg between successive stops (and endpoints) must not exceed 500 miles. |
| **Monetary Accuracy** | Exact Decimal | Zero floating point roundoff during optimization; rounded to cents only at API boundary. |

---

## 3. Technology Stack & Design Decisions

* **Language:** Python 3.13 / 3.11+
* **Web Framework:** Django 6.1.1 + Django REST Framework 3.18.1
* **Database:** PostgreSQL 16/18 with `psycopg` 3.3 (strict production config with fallback SQLite mode for offline unit testing)
* **Spatial Processing:** Shapely 2.1 (`STRtree` for segment-local metric projection)
* **External Providers:**
  * OpenStreetMap Nominatim for forward geocoding (with strictly enforced 1.05s rate limiting and User-Agent identification).
  * Open Source Routing Machine (OSRM) for turn-by-turn road network trajectories and distance.
* **Testing:** `pytest` + `pytest-django` (54 automated tests, 100% mocked external HTTP calls).

---

## 4. Summary of Deliverables

1. **Phase 0 & 0.5 (Audit & Preprocessing):** Comprehensive analysis of 8,151 raw OPIS records, Canadian province exclusion, deduplication, 3-tier geocoding cascade, and dynamic Census Gazetteer bounding box derivation.
2. **Phase 1 (Data Layer):** Strict PostgreSQL configuration, `FuelStation` model with composite `(latitude, longitude)` indexing, and idempotent `import_fuel_data` management command.
3. **Phase 2 (External Services):** Robust geocoding and routing services with CONUS bounding box enforcement, persistent on-disk database caching, and custom error taxonomy.
4. **Phase 3 (Spatial Corridor & Optimizer):** $O(M \log N)$ Shapely `STRtree` corridor filter with segment-local projection (< 0.001% distortion) and pure-Python greedy lookahead optimizer with local minimum filling.
5. **Phase 4 (REST API):** Thin DRF view at `POST /api/v1/route/`, comprehensive exception handler (`{"error": {"code", "message"}}`), OpenAPI schema, Postman collection, and live smoke test validation.
