# 09: Performance Benchmarks & Latency Analysis

**Component:** Performance Engineering  
**Status:** Validated  

---

## 1. Executive Summary

Empirical benchmarking on live highway routes between major US metropolitan areas demonstrates a **>12x speedup** between cold and cached requests:

| Request State | Total Response Time | Outbound External HTTP Calls | Dominant Cost |
|---|---|---|---|
| **Cold Request** (New York $\to$ Chicago) | **`5,574.0 ms`** (~5.6 s) | **3** (2 Nominatim + 1 OSRM) | Outbound network latency & Nominatim 1.05s rate limiter |
| **Cached Request** (New York $\to$ Chicago) | **`453.2 ms`** (~0.45 s) | **0 (Zero external calls)** | Shapely STRtree spatial projection over 25,000 vertices |
| **Transcontinental Cold** (Los Angeles $\to$ New York) | **`4,155.7 ms`** (~4.2 s) | **2** (1 Nominatim [LA cached] + 1 OSRM) | OSRM polyline download & nationwide STRtree traversal |

---

## 2. Micro-Profiling Breakdown: The 453 ms Cached Call

To determine precisely where CPU cycles and latency are spent when zero external network calls are made, the 790.6-mile New York to Chicago route was instrumented with high-resolution timers (`time.perf_counter`) across 5 warm runs against PostgreSQL:

```
[Total Client Turnaround: 453.2 ms]
  ├── Server-Side Execution Time: 373.8 ms (~374 ms)
  │     ├── 1. Geocoding Cache Lookups (start + finish):     2.75 ms  ( 0.7%)
  │     ├── 2. Routing Cache Lookup (geometry fetch):       12.22 ms  ( 3.3%)
  │     ├── 3. SQL Bbox Prefilter Query (PostgreSQL):        4.20 ms  ( 1.1%)
  │     ├── 4. Shapely STRtree Corridor Projection:        336.78 ms  (90.1%)  ◄── [DOMINANT: ~90% OF SERVER TIME]
  │     ├── 5. Fuel Stop Optimizer (Pure Python):            1.23 ms  ( 0.3%)
  │     └── 6. DRF JSON Serialization & Rendering:          16.59 ms  ( 4.4%)
  │
  └── Loopback & Client Transport Overhead:                 ~79.4 ms  (~80 ms)
        (TCP socket connection, HTTP handshake, header parsing, payload transfer)
```

### Key Observation: Shapely STRtree Construction Dominates Cached Requests
Shapely `STRtree` spatial indexing and corridor projection dominates the cached request, accounting for **~90% of total server-side processing time (336.8 ms of 373.8 ms)**.

* The OSRM driving route for New York to Chicago contains **25,236 polyline coordinate vertices**.
* The service builds a 2D spatial R-Tree (`STRtree`) over all 25,235 line segments and evaluates candidate truck stops against candidate segments using segment-local metric Cartesian projection.
* In contrast, the database lookups and SQL bounding box prefilter take only **19.2 ms combined (5.1%)**, the pure Python optimizer takes **1.23 ms (0.3%)**, and DRF JSON serialization takes **16.59 ms (4.4%)**.
* The remaining ~80 ms is loopback network overhead (TCP socket negotiation, HTTP wire serialization, and client transport).

---

## 3. Possible Latency Improvements (Documented, Not Implemented)

If sub-100ms response times are required for cached routes in high-throughput enterprise environments, the following architectural optimizations can be introduced without altering optimization math:

1. **Geometry Simplification (Ramer-Douglas-Peucker):**
   * Simplify the high-resolution 25,000-point highway line string using Shapely's `simplify(tolerance=0.0005)` (~50 meters) specifically for station matching.
   * This reduces the vertex count from 25,000 to ~2,000 segments (a 12x reduction), dropping STRtree construction and query time from **336 ms down to < 25 ms**, while keeping the full 25,000-point line string intact for the final JSON response.
2. **Cache Matched Stations Per Route:**
   * Because highway fuel station candidate lists along a fixed route key are static, the matched stations list (with projected distances from start) can be stored alongside the route in `RouteCache` or an associated table. Subsequent requests would completely bypass STRtree construction, dropping server processing to under 25 ms.
3. **Dedicated In-Memory Cache (Redis):**
   * Storing hot route keys and pre-projected candidate stations in Redis rather than PostgreSQL reduces cache query overhead from 12 ms to < 1 ms.
