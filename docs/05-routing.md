# Phase 2: Driving Route Service Architecture

**Service Component:** `fuel_route.services.routing`  
**Provider:** Open Source Routing Machine (OSRM) Driving API  
**Status:** Complete  

---

## 1. Overview & Purpose

The driving route service calculates the navigable highway path, total driving distance (miles), driving duration (seconds), and complete polyline geometry (GeoJSON LineString) between origin and destination coordinates. This provides the exact driving trajectory needed by Phase 3 station filtering and Phase 4 fuel stop optimization.

---

## 2. Key Architecture & Features

### 2.1 Cache-First Strategy (`route_cache` Table)
Because commercial truck routes between metropolitan areas are frequently repeated (e.g., Dallas $\rightarrow$ Atlanta, Chicago $\rightarrow$ Memphis), all computed routes are stored in the `route_cache` PostgreSQL database table.
- **Coordinate Rounding & Key Canonicalization:** Coordinates are rounded to 4 decimal places, which corresponds to approximately $\sim 11$ meters on the Earth's surface:
  `route_key = f"{start_lat:.4f},{start_lon:.4f}->{end_lat:.4f},{end_lon:.4f}"`
  *(e.g., micro-variations such as `30.26719` and `30.26721` resolve to the identical cached highway route)*.
- **Permanent TTL:** Interstate highways do not change routes on short notice; permanent caching ensures zero repeated external network calls for identical origin-destination corridors.
- **Race Condition Safety:** Cache writes utilize `get_or_create` with an explicit `IntegrityError` catch block, eliminating race conditions under concurrent worker threads.
- **No Negative Caching:** Route lookup failures (e.g., unreachable points, 5xx server errors, or timeouts) are **never cached**, ensuring temporary upstream issues do not poison the cache.

### 2.2 Endpoint Swappability & Configuration
- **Swappable Engine URL:** The OSRM endpoint is decoupled via the `OSRM_BASE_URL` environment variable:
  ```ini
  # In .env:
  OSRM_BASE_URL=https://router.project-osrm.org
  # In production / self-hosted environments:
  # OSRM_BASE_URL=http://localhost:5000
  ```
- **Single Efficient Request:**
  `{OSRM_BASE_URL}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson&steps=false`
  - Coordinates are strictly ordered as `longitude,latitude` per OSRM specifications.
  - Setting `steps=false` avoids transferring hundreds of turn-by-turn instruction objects, keeping payload size small and parsing overhead minimal.
- **Unit Conversion:**
  OSRM returns distance in meters. The service converts meters to US statute miles:
  `distance_miles = round(distance_meters * 0.000621371, 2)`

---

## 3. Error Taxonomy & HTTP Status Code Mapping

| Error Code | Exception Class | HTTP Status | Trigger Condition |
|---|---|---|---|
| `MISSING_INPUT` | `InvalidInputError` | `400 Bad Request` | Coordinates are null, non-numeric, or malformed. |
| `LOCATION_NOT_US` | `NonUSLocationError` | `422 Unprocessable Entity` | Start or destination coordinates fall outside the contiguous US. |
| `NO_ROUTE_FOUND` | `NoRouteFoundError` | `422 Unprocessable Entity` | OSRM returns code `'NoRoute'` (impossible route or disjoint road networks). |
| `ROUTING_ERROR` | `RoutingServiceError` | `502 Bad Gateway` | Upstream OSRM server returns HTTP 5xx, invalid payload, or connection fails. |
| `ROUTING_TIMEOUT` | `RoutingTimeoutError` | `504 Gateway Timeout` | Outbound HTTP socket times out (> 10.0 seconds). |

---

## 4. Alternatives Considered

1. **Straight-Line / Haversine Distance:**
   - *Pros:* Instant calculation without external network calls.
   - *Cons:* Completely invalid for interstate commercial trucking; ignores terrain, mountain passes, rivers, tollways, and actual highway exit configurations.
2. **Google Maps Directions API:**
   - *Pros:* Comprehensive traffic and turn-by-turn routing.
   - *Cons:* High cost ($5 per 1,000 requests), strict licensing forbidding persistent caching of route geometry.
3. **GraphHopper / OpenRouteService (ORS):**
   - *Pros:* Quality routing engines.
   - *Cons:* Free tier rate limits (e.g. 40 req/min) and requires managing private API keys.

---

## 5. Tradeoffs & Known Limitations

1. **Public Demo Server Lack of an SLA:**
   - The default endpoint (`https://router.project-osrm.org`) is a public community demonstration server maintained by the OSRM project.
   - It has no formal uptime SLA, imposes unannounced request throttling, and is not suitable for high-throughput production traffic.
2. **Production Mitigation:**
   - Because the service is built around a swappable `OSRM_BASE_URL`, pointing the application to a dedicated or self-hosted OSRM routing instance can be integrated by setting `OSRM_BASE_URL=http://localhost:5000` in `.env` with zero code modifications.
