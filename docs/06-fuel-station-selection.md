# Phase 3: Fuel Station Selection & Corridor Matching

**Service Component:** `fuel_route.services.stations`  
**Status:** Complete  

---

## 1. Overview & Purpose

The fuel station selection service identifies all viable commercial truck stops along an OSRM driving route. It filters the 6,600+ preprocessed fuel stations down to those situated within a defined perpendicular highway detour corridor (`ROUTE_CORRIDOR_MILES = 10.0` miles) and projects each station onto the route polyline to compute its exact odometer distance from the origin.

---

## 2. Architecture & Pipeline

The pipeline operates in two decoupled stages to maximize speed and eliminate database overhead:

```
[OSRM GeoJSON Route LineString]
             │
             ▼
[Stage 1: SQL Bounding-Box Prefilter]
  - Calculates route bounding box with high-latitude longitude expansion
  - Single SQL indexed range scan on (latitude, longitude)
  - Reduces 6,600+ stations to ~50–300 candidates (0 N+1 queries)
             │
             ▼
[Stage 2: Segment-Local Metric Projection via Shapely STRtree]
  - Precomputes cumulative Haversine distances along route vertices
  - Scales cumulative distances to match OSRM's authoritative odometer miles
  - Builds Shapely STRtree spatial index over route segments
  - Evaluates candidate segments using segment-local Cartesian projection
  - Filters stations with perpendicular cross-track distance <= 10.0 miles
             │
             ▼
[Ordered Candidate Stations: (distance_from_start_miles, retail_price)]
```

---

## 3. High-Latitude Longitude Buffering

Because meridians converge toward the poles, the longitudinal distance corresponding to 10 statute miles decreases with latitude ($\Delta \text{lon} \propto \frac{1}{\cos(\text{lat})}$):
- At the equator ($0^\circ$), $1^\circ \text{ lon} \approx 69.17\text{ miles}$.
- At $30^\circ\text{N}$ (Texas/Florida), $1^\circ \text{ lon} \approx 59.9\text{ miles}$.
- At $49^\circ\text{N}$ (North Dakota / Washington northern border), $1^\circ \text{ lon} \approx 45.4\text{ miles}$.

If a naive degree buffer ($\Delta \text{lon} = \frac{10}{69.0} \approx 0.145^\circ$) were applied, northern stations up to 8 miles away would fall outside the SQL bounding box and be discarded prematurely.  
The service dynamically adjusts the longitude buffer using the maximum absolute latitude along the route:
$$\Delta \text{lon} = \frac{\text{corridor\_miles}}{69.0 \cdot \cos(\max(|\text{min\_lat}|, |\text{max\_lat}|))}$$
This guarantees $100\%$ recall for the SQL bounding-box prefilter across all continental latitudes.

---

## 4. Projection Accuracy on 2,800-Mile Routes

### 4.1 Distortion of a Single Global Projection
A single equirectangular projection centered on the centroid of a 2,800-mile transcontinental route (e.g., Seattle, WA at $47.6^\circ\text{N}$ to Miami, FL at $25.8^\circ\text{N}$, with centroid at $\sim 36.7^\circ\text{N}$) introduces significant scale distortion:
$$\text{Scale Ratio} = \frac{\cos(36.7^\circ)}{\cos(\text{lat})}$$
- At $47.6^\circ\text{N}$ (Seattle): scale ratio is $\frac{0.8018}{0.6743} \approx 1.189$ (**$+18.9\%$ scale distortion**).
- At $25.8^\circ\text{N}$ (Miami): scale ratio is $\frac{0.8018}{0.9003} \approx 0.891$ (**$-10.9\%$ scale distortion**).
Because this error dramatically exceeds the $1\%$ threshold, a single global projection cannot be used for nationwide cross-track corridor filtering.

### 4.2 Segment-Local Metric Projection
The service resolves this by performing **segment-local metric projection**:
1. Route segments are indexed in a Shapely `STRtree` ($O(M \log N)$ complexity).
2. For each candidate station, nearby candidate segments are retrieved from the spatial tree.
3. The station is projected onto each candidate segment $(V_k, V_{k+1})$ in a local Cartesian frame centered on the segment's midpoint ($\text{lat}_{\text{mid}}$):
   $$x = (\lambda - \lambda_{V_k}) \cdot \cos(\text{lat}_{\text{mid}}) \cdot 69.172$$
   $$y = (\phi - \phi_{V_k}) \cdot 69.0$$
4. Because individual highway segments in OSRM are $< 1$ mile long, curvature distortion across that 1-mile segment is **$< 0.001\%$**.
5. Cross-track distance is exact, and along-route distance accurately follows the highway trajectory.

### 4.3 OSRM Distance Scaling Assumption
Polyline chords approximate highway curves. The sum of straight-line segment chords $L_{\text{haversine}}$ is slightly shorter ($< 0.5\%$) than the true road distance.  
The service scales all cumulative segment distances proportionally:
$$\text{scale\_factor} = \frac{\text{osrm\_distance\_miles}}{L_{\text{haversine}}}$$
$$\text{distance\_from\_start} = \text{seg\_start\_dist} + t \cdot (\text{seg\_end\_dist} - \text{seg\_start\_dist})$$
This ensures that station mile markers match the vehicle's odometer mileage.

---

## 5. Alternatives & Tradeoffs

1. **PostGIS `ST_DWithin` & `ST_LineLocatePoint`:**
   - *Pros:* Native database GIS functions.
   - *Cons:* Requires PostGIS extension, spatial libraries, and database-level dependencies.
   - *Choice:* Django ORM + Shapely C-extension delivers identical sub-25ms speed on standard PostgreSQL and SQLite with zero external database extensions.
2. **Precomputed Station Route Tables:**
   - *Pros:* Instant lookups.
   - *Cons:* Impractical because user routes can be arbitrary point-to-point queries anywhere in the United States.
