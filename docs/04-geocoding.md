# Phase 2: Forward Geocoding Service Architecture

**Service Component:** `fuel_route.services.geocoding`  
**Provider:** OpenStreetMap Nominatim Search API  
**Status:** Complete  

---

## 1. Overview & Purpose

The forward geocoding service converts freeform user queries (e.g. `"Austin, TX"` or `"Chicago, Illinois"`) into geographic WGS84 coordinates `(latitude, longitude)` and official display names. These coordinates serve as the start and finish anchors for subsequent routing and commercial fuel stop optimization along interstate corridors.

---

## 2. Key Architecture & Features

### 2.1 Cache-First Strategy (`geocoding_cache` Table)
Before any network transmission occurs, queries are checked against the persistent PostgreSQL database table `geocoding_cache`.
- **Key Normalization:** Queries are stripped of leading/trailing whitespace, collapsed from multi-space sequences, and converted to lowercase:
  `normalized_query = re.sub(r'\s+', ' ', query.strip()).lower()`
  *(e.g., `"  Austin,   TX  "` and `"AUSTIN, TX"` resolve to the identical cache record `"austin, tx"`)*.
- **Permanent TTL:** Because physical settlements and coordinates do not change on human timescales, cache entries are permanent, eliminating redundant requests to public infrastructure.
- **Race Condition Safety:** Cache writes utilize `get_or_create` with an explicit `IntegrityError` catch block, preventing unhandled exceptions under concurrent identical requests.
- **No Negative Caching:** Failed requests, non-existent locations, network timeouts, and HTTP errors are **never cached**, ensuring transient faults can be resolved immediately upon recovery.

### 2.2 Contiguous United States (CONUS) Bounding Box Validation
All geocoded locations are validated to ensure they reside within the contiguous 48 US states + District of Columbia.
- **Derivation Source:** Directly calculated from all **31,523 Contiguous US places** in the **2024 US Census Bureau Gazetteer** (`data/gazetteer/2024_Gaz_place_national.txt`, excluding non-contiguous jurisdictions AK, HI, PR, VI, GU, AS, MP out of 32,333 total rows):
  - **Raw Min Latitude:** `24.563990°` (Key West city, FL)
  - **Raw Max Latitude:** `49.347409°` (Angle Inlet CDP, MN / Northwest Angle)
  - **Raw Min Longitude:** `-124.611559°` (Cape Alava / Neah Bay area, WA)
  - **Raw Max Longitude:** `-66.989856°` (Lubec town, ME / West Quoddy Head)
- **Applied Padding:** A calibrated margin of ~0.39° to 0.65° (~25 to 40 miles) is padded around the raw extremes:
  - Latitude: padded south by `0.564°` to `24.0°`, padded north by `0.653°` to `50.0°`
  - Longitude: padded west by `0.388°` to `-125.0°`, padded east by `0.490°` to `-66.5°`
  - **Active Constants:**
    - `CONUS_MIN_LAT = 24.0`
    - `CONUS_MAX_LAT = 50.0`
    - `CONUS_MIN_LON = -125.0`
- This padding accommodates coastal highway bypasses, outer barrier islands, port terminals, and border facilities.

> [!IMPORTANT]
> **Resolution Behavior: Overseas vs. Non-Contiguous US Locations**
> * **Overseas Locations (e.g. `"Paris, France"`):** Because queries to Nominatim strictly enforce `countrycodes=us`, Nominatim returns zero results for places outside the United States, raising `LocationNotFoundError` (HTTP `404 LOCATION_NOT_FOUND`).
> * **Non-Contiguous US Locations (e.g. `"Anchorage, AK"`, `"Honolulu, HI"`):** Nominatim successfully resolves these places within the US (`country_code="us"`), but their coordinates fall outside the CONUS bounding box, raising `NonUSLocationError` (HTTP `422 LOCATION_NOT_US`).

### 2.3 Nominatim AUP Compliance & Rate Limiting
- **Custom User-Agent:** In accordance with OSM's Acceptable Use Policy, every outbound request includes a customized header identifying the application and referencing a real contact email from the environment:
  `SpotterFuelRouteOptimizer/1.0 (contact: {GEOCODER_CONTACT_EMAIL})`
  The service refuses to make outbound calls if `GEOCODER_CONTACT_EMAIL` is missing.
- **Rate Limiting:** Enforces a minimum `1.05`-second delay between successive external HTTP calls using an in-process thread-safe lock.
- **No Retries:** Fails immediately upon receiving HTTP 429 or server errors to prevent hammering public infrastructure.

---

## 3. Error Taxonomy & HTTP Status Code Mapping

| Error Code | Exception Class | HTTP Status | Trigger Condition |
|---|---|---|---|
| `MISSING_INPUT` | `InvalidInputError` | `400 Bad Request` | Query string is null, empty, or whitespace-only. |
| `LOCATION_NOT_FOUND` | `LocationNotFoundError` | `404 Not Found` | Nominatim returns 0 results for the query. |
| `LOCATION_NOT_US` | `NonUSLocationError` | `422 Unprocessable Entity` | Address country is not US, or coordinates fall outside CONUS bounding box. |
| `GEOCODER_RATE_LIMITED`| `GeocoderRateLimitError`| `429 Too Many Requests` | Upstream Nominatim returns HTTP 429. |
| `GEOCODER_ERROR` | `GeocoderServiceError` | `502 Bad Gateway` | Upstream Nominatim returns HTTP 5xx, invalid payload, or network connection fails. |
| `GEOCODER_TIMEOUT` | `GeocoderTimeoutError` | `504 Gateway Timeout` | Outbound HTTP socket times out (> 5.0 seconds). |

---

## 4. Alternatives Considered

1. **Google Maps Geocoding API:**
   - *Pros:* High coverage and tolerance for malformed input.
   - *Cons:* Proprietary, expensive at scale ($5 per 1,000 requests), strict licensing forbidding caching beyond 30 days and restricting display to Google Maps.
2. **US Census Bureau Geocoder API (Batch & Single):**
   - *Pros:* Free, authoritative US government data.
   - *Cons:* Street-address parser fails on 96.8% of commercial trucking locations (interstate exits like `I-44, EXIT 283 & US-69`); single-query endpoint has higher latency and frequent downtime.
3. **Mapbox / HERE Geocoding:**
   - *Pros:* Turnkey SaaS with SLAs.
   - *Cons:* Commercial tier API keys required; unnecessary for a localized assessment where Nominatim + persistent database caching delivers identical accuracy with 0 ongoing cost.

---

## 5. Tradeoffs & Known Limitations

1. **Per-Process Rate Limiter Limitation:**
   - The thread-safe rate limiter (`MIN_REQUEST_INTERVAL_SECONDS = 1.05`) operates **in-memory within a single Python process**.
   - If the application is deployed behind a multi-process WSGI server (such as multiple Gunicorn or uWSGI worker processes), separate processes could theoretically fire outbound requests concurrently and exceed the 1 req/sec threshold on cache misses.
   - *Production Remediation:* In multi-worker production deployments, rate limiting must be synchronized across workers via a distributed Redis token-bucket filter or routed through a centralized outbound proxy.
2. **Public Community Service:**
   - The public Nominatim instance is hosted by volunteer donations and carries no formal SLA. Production commercial deployments should point to a self-hosted Nominatim container or a dedicated enterprise provider.
