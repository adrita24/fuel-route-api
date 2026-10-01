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

## 3. Station Match Cache: Before vs. After Benchmarks

To eliminate the 300–400 ms spatial bottleneck caused by building Shapely STRtrees on repeated identical routes, `StationMatchCache` caches the pre-projected candidate stations along a route corridor keyed by `route_key|corridor_miles`.

Empirical measurements across 5 warm runs each against PostgreSQL:

| Metric | New York, NY $\to$ Chicago, IL | College Station, TX $\to$ Atlanta, GA |
|---|---|---|
| **Matching Alone (Before, STRtree)** | `392.14 ms` | `242.91 ms` |
| **Matching Alone (After, StationMatchCache)** | **`4.47 ms`** (**87.8x speedup**) | **`3.68 ms`** (**66.0x speedup**) |
| **Server E2E Time (Before)** | `473.69 ms` | `296.55 ms` |
| **Server E2E Time (After)** | **`23.59 ms`** (**20.1x speedup**) | **`23.00 ms`** (**12.9x speedup**) |
| **Postman-Style HTTP Time (2nd Call)** | **`61.38 ms`** | **`40.54 ms`** |

### What is Cached vs. What is Evaluated Dynamically
* **Cached (`StationMatchCache`):** The list of candidate fuel stations within the corridor and their along-route mile markers (`distance_from_start_miles`). Prices are stored as strings to prevent floating-point drift and converted back to `Decimal` upon read.
* **Why the Optimizer is NOT Cached:** The optimizer takes only **~1.2 ms**. Keeping the optimizer dynamic allows clients to change vehicle settings (`MPG`, `MAX_RANGE_MILES`, `TANK_CAPACITY_GALLONS`) on the fly and immediately receive the newly tailored fuel stops without requiring cache invalidation.

### Where Does the Remaining Time Go on Repeat Requests?
On repeat requests (e.g. New York to Chicago in ~61 ms HTTP turnaround):
1. **Server-Side Execution (~23.6 ms):**
   * `RouteCache` geometry lookup (fetching 289 KB JSON from PostgreSQL): **12.2 ms**
   * `StationMatchCache` lookup & Decimal deserialization: **4.5 ms**
   * `GeocodingCache` lookups (start + finish): **2.5 ms**
   * Pure Python Greedy Optimizer: **1.2 ms**
   * Route duration formatting & response dict assembly: **0.5 ms**
2. **HTTP Layer & Transport (~37.8 ms):**
   * DRF JSON serialization & rendering of the 25,236-vertex LineString: **16.6 ms**
   * Localhost TCP socket connection, HTTP headers parsing, and payload transfer: **21.2 ms**
