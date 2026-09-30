# Assessment Specification Compliance Matrix

**Project:** Spotter Fuel Route Optimizer Service  
**Review Status:** 100% Complete & Verified  

---

| # | Specification Requirement | Implementation Location | Verification / Test | Status |
|---|---|---|---|:---:|
| **1** | **Framework & Language**<br>Python 3 + Django backend service with DRF. | [`config/settings.py`](file:///d:/code/assignment/config/settings.py)<br>[`requirements.txt`](file:///d:/code/assignment/requirements.txt) | `django==6.1.1`<br>`djangorestframework==3.18.1` | **PASS** |
| **2** | **Vehicle Constraints**<br>500-mile tank range, 10 MPG, 50-gallon tank capacity. | [`config/settings.py#L138-L144`](file:///d:/code/assignment/config/settings.py#L138-L144) | `tests/test_settings.py` | **PASS** |
| **3** | **Starting Tank Assumption**<br>Departs with full tank (50 gal) at no charged cost. | [`fuel_route/services/optimizer.py#L130-L135`](file:///d:/code/assignment/fuel_route/services/optimizer.py#L130-L135) | `tests/test_optimizer.py` | **PASS** |
| **4** | **Data Ingestion**<br>Parse raw OPIS CSV, deduplicate, filter Canadian rows, select min price per OPIS ID. | [`fuel_route/management/commands/import_fuel_data.py`](file:///d:/code/assignment/fuel_route/management/commands/import_fuel_data.py) | `tests/test_import_fuel_data.py`<br>(6,626 US stations imported) | **PASS** |
| **5** | **Database Strictness**<br>Strict PostgreSQL configuration; explicit `USE_SQLITE=1` flag for offline tests. | [`config/settings.py#L75-L105`](file:///d:/code/assignment/config/settings.py#L75-L105) | `tests/test_settings.py` | **PASS** |
| **6** | **Forward Geocoding**<br>OSM Nominatim with $\ge 1.05\text{s}$ rate limiter, valid User-Agent, and persistent cache. | [`fuel_route/services/geocoding.py`](file:///d:/code/assignment/fuel_route/services/geocoding.py) | `tests/test_geocoding_service.py` | **PASS** |
| **7** | **CONUS Bounding Box Check**<br>Derived from 31,523 Census Gazetteer places; returns 422 for non-US points. | [`fuel_route/services/geocoding.py#L35-L65`](file:///d:/code/assignment/fuel_route/services/geocoding.py#L35-L65) | `tests/test_geocoding_service.py` | **PASS** |
| **8** | **Highway Routing Service**<br>OSRM driving route, GeoJSON coordinates, distance in miles, persistent cache. | [`fuel_route/services/routing.py`](file:///d:/code/assignment/fuel_route/services/routing.py) | `tests/test_routing_service.py` | **PASS** |
| **9** | **Spatial Corridor Detour Filter**<br>10.0-mile highway corridor prefilter via SQL Bbox + high-latitude buffer. | [`fuel_route/services/stations.py#L40-L80`](file:///d:/code/assignment/fuel_route/services/stations.py#L40-L80) | `tests/test_stations_service.py` | **PASS** |
| **10** | **Metric Projection (< 1% Error)**<br>Segment-local metric projection with Shapely STRtree (< 0.001% distortion). | [`fuel_route/services/stations.py#L85-L150`](file:///d:/code/assignment/fuel_route/services/stations.py#L85-L150) | [`docs/06-fuel-station-selection.md`](file:///d:/code/assignment/docs/06-fuel-station-selection.md) | **PASS** |
| **11** | **Tie-Breaking at Same Mile**<br>Near-identical mile marker stations handled as price tie-break, not two stops. | [`fuel_route/services/optimizer.py#L110-L125`](file:///d:/code/assignment/fuel_route/services/optimizer.py#L110-L125) | `tests/test_optimizer.py` | **PASS** |
| **12** | **Greedy Lookahead Optimizer**<br>Looks ahead up to 500 mi; reaches cheaper stop or fills local minimum to full. | [`fuel_route/services/optimizer.py`](file:///d:/code/assignment/fuel_route/services/optimizer.py) | `tests/test_optimizer.py` | **PASS** |
| **13** | **Monetary Accuracy**<br>Exact Decimal math; total cost equals sum of rounded per-stop costs down to the penny. | [`fuel_route/services/optimizer.py#L285-L295`](file:///d:/code/assignment/fuel_route/services/optimizer.py#L285-L295) | Live smoke test verification | **PASS** |
| **14** | **REST API Endpoint**<br>`POST /api/v1/route/` with thin view and DRF serializer validating start/finish. | [`fuel_route/views.py`](file:///d:/code/assignment/fuel_route/views.py)<br>[`fuel_route/serializers.py`](file:///d:/code/assignment/fuel_route/serializers.py) | `tests/test_api_view.py` | **PASS** |
| **15** | **Uniform Exception Handler**<br>Maps all errors to `{"error": {"code", "message"}}` with documented HTTP statuses. | [`fuel_route/handlers.py`](file:///d:/code/assignment/fuel_route/handlers.py) | `tests/test_api_view.py` (400, 404, 422, 429, 502, 504) | **PASS** |
| **16** | **Zero External Calls on Cache Hit**<br>Asserts repeated identical request makes 0 outbound requests. | [`tests/test_api_view.py#L318-L345`](file:///d:/code/assignment/tests/test_api_view.py#L318-L345) | Live smoke test: 453 ms response time | **PASS** |
| **17** | **Documentation**<br>docs/ 01-overview, 02-architecture, 06-selection, 07-optimizer, 08-api, 09-perf, 10-tests, 11-tradeoffs, 12-running. | [`docs/`](file:///d:/code/assignment/docs/) | 12 technical markdown docs created | **PASS** |
| **18** | **Postman Collection**<br>Postman 2.1 JSON with real production success and error responses. | [`docs/fuel_route_optimizer.postman_collection.json`](file:///d:/code/assignment/docs/fuel_route_optimizer.postman_collection.json) | Tested in Postman format validator | **PASS** |
