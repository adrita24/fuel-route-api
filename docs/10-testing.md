# 10: Automated Testing Strategy & Verification

**Component:** Quality Assurance & Testing  
**Status:** 54 Passed Tests (100% Pass Rate)  

---

## 1. Testing Philosophy & Guardrails

The testing architecture adheres to strict engineering constraints designed for reliability, determinism, and safety:

1. **Zero Uncontrolled Network Calls:**
   * All external HTTP requests to OpenStreetMap Nominatim and OSRM are strictly mocked via `unittest.mock.patch` across the entire unit test suite.
   * Tests run completely offline, execute in under 25 seconds, and never hammer public APIs or fail due to network flakiness.
2. **Idempotency & Isolation:**
   * Uses `pytest-django` database fixtures (`@pytest.mark.django_db`) that create and tear down clean test schemas.
   * Model constraints (e.g. `opis_id` uniqueness, bounding box validation) are rigorously tested under concurrent insert scenarios.
3. **Mathematical Invariant Verification:**
   * Verifies that vehicle fuel inventory never goes negative ($F \ge 0$).
   * Verifies that no driving leg between stops exceeds the 500-mile vehicle range.
   * Verifies that total cost reconciles to the exact penny with the sum of individual stop purchases.

---

## 2. Test Suite Organization

The automated suite comprises **54 test cases** distributed across 8 focused test modules:

```
tests/
├── test_settings.py           (4 tests: database strictness, defaults, SQLite test mode)
├── test_models.py             (2 tests: FuelStation creation, opis_id unique constraint)
├── test_import_fuel_data.py   (3 tests: minimum price, Canadian filter, rerun idempotency)
├── test_geocoding_service.py  (12 tests: query norm, CONUS box, cache hit, errors 400/404/422/429/502/504)
├── test_routing_service.py    (8 tests: route key, cache hit, CONUS check, errors 422/502/504)
├── test_stations_service.py   (5 tests: bbox prefilter, STRtree projection, high-lat buffer, sorting)
├── test_optimizer.py          (11 tests: lookahead rules, local min fill, tie-breaks, gap feasibility)
└── test_api_view.py           (9 tests: DRF test client end-to-end, validation, 0 external calls proof)
```

---

## 3. Critical Invariant Tests

### 1. Zero External Calls on Cache Hit (`test_repeated_identical_request_makes_zero_external_calls`)
* Simulates an initial request that populates `GeocodingCache` and `RouteCache`.
* Executes an identical subsequent request using DRF `APIClient`.
* Asserts that `mock_get.call_count` does not increase, proving zero outbound HTTP requests.

### 2. Tie-Breaking Near Identical Mile Markers (`test_two_stations_at_nearly_same_mile_marker_tie_break`)
* Places two stations at mile 300.0 ($3.50) and mile 300.2 ($3.00).
* Asserts that the vehicle stops only at the cheaper station, buying 0 gallons at the expensive station, producing **exactly 1 stop**.

### 3. High-Latitude Longitude Buffering (`test_high_latitude_longitude_buffer`)
* Validates that routes at northern latitudes ($48^\circ\text{N}$) expand the longitudinal search bounding box by $\frac{10}{69.0 \cdot \cos(\text{lat})}$, guaranteeing that stations 8–9 miles off-highway are not clipped by the SQL prefilter.

### 4. Route Infeasibility & Fuel Gaps (`test_route_not_feasible_gap_over_max_range`)
* Simulates an 850-mile route with a 550-mile gap devoid of fuel stations.
* Asserts that `RouteNotFeasibleError` is raised with HTTP 422, clearly communicating the station gap.

---

## 4. How to Run the Tests

From the project root:

```powershell
# Run full suite against PostgreSQL (default)
python -m pytest

# Run full suite with verbose test name output
python -m pytest -v

# Run offline in isolated SQLite mode (without PostgreSQL running)
$env:USE_SQLITE="1"; python -m pytest; Remove-Item env:USE_SQLITE
```
