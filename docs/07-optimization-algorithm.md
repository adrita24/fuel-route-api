# Phase 3: Fuel Stop Optimization Algorithm

**Service Component:** `fuel_route.services.optimizer`  
**Status:** Complete  

---

## 1. Problem Formulation & Objective

Given:
* Total route driving distance $D$ in miles.
* Vehicle fuel efficiency $\text{MPG} = 10.0$ miles per gallon.
* Maximum driving range on a full tank $R = 500.0$ miles.
* Derived tank capacity $C = \frac{R}{\text{MPG}} = 50.0$ gallons.
* A set of commercial fuel stations along the route corridor, each defined by odometer distance $d_i$ and retail fuel price $p_i$ ($/gal).

**Objective:**  
Determine the sequence of fuel stops and gallons pumped at each stop to minimize total fuel cost (\$) while ensuring the vehicle never runs out of fuel ($\text{fuel} \ge 0$).

---

## 2. Core Assumptions

1. **Full Starting Tank:** The vehicle departs from origin (mile 0) with a completely full tank ($50.0$ gallons / $500.0$ miles range).
2. **No Minimum Reserve:** Fuel can safely drop to $0.0$ gallons at the exact instant the vehicle arrives at a fuel station or reaches the destination.
3. **Linear Fuel Consumption:** Fuel is consumed at a constant rate of $0.1$ gallons per mile driven ($\frac{1}{\text{MPG}}$).
4. **Exact Decimal Arithmetic:** All fuel volume and monetary calculations use Python's `Decimal` type to avoid floating point precision leaks. Values are rounded to 2 decimal places only at the API response boundary.

---

## 3. Algorithm: Greedy Lookahead with Local Minimum Filling

The problem has a known greedy choice property. At any current station $S_{\text{curr}}$ with fuel remaining $F_{\text{curr}}$:

### 3.1 Decision Logic
1. **Destination Check:** If the remaining distance to the destination is reachable on current fuel ($\text{dist\_to\_dest} \le F_{\text{curr}} \times \text{MPG}$), proceed directly to the destination with 0 additional purchases.
2. **Full-Tank Lookahead Horizon:** Inspect all candidate stations in the window:
   $$(d_{\text{curr}}, d_{\text{curr}} + R]$$
   *(Note: Full-tank range $R$ is used because the vehicle has the option to purchase fuel at $S_{\text{curr}}$).*

3. **Case 1: A Cheaper Station Exists Within Full Range** ($\exists S_j \text{ with } p_j < p_{\text{curr}}$):
   * Select the **NEAREST (first)** cheaper station $S_{\text{next}}$.
   * Buy *only enough fuel* at $S_{\text{curr}}$ to reach $S_{\text{next}}$ with $0.0$ gallons remaining:
     $$\text{fuel\_needed} = \frac{S_{\text{next}}.\text{dist} - d_{\text{curr}}}{\text{MPG}}$$
     $$\text{gallons\_to\_buy} = \max(0.0, \text{fuel\_needed} - F_{\text{curr}})$$
   * If existing fuel $F_{\text{curr}}$ is already sufficient, buy $0.0$ gallons.
   * Advance to $S_{\text{next}}$ with $F_{\text{next}} = \max(0.0, F_{\text{curr}} - \text{fuel\_needed})$.

4. **Case 2: No Cheaper Station Exists Within Full Range** ($S_{\text{curr}}$ is a local price minimum):
   * **Subcase 2a (Destination Reachable):** $\text{dist\_to\_dest} \le R$.
     * Buy just enough fuel to reach the destination with $0.0$ gallons:
       $$\text{gallons\_to\_buy} = \max\left(0.0, \frac{\text{dist\_to\_dest}}{\text{MPG}} - F_{\text{curr}}\right)$$
     * Proceed to destination and finish.
   * **Subcase 2b (Destination Unreachable):** $\text{dist\_to\_dest} > R$.
     * Because $S_{\text{curr}}$ is cheaper than any other station within reach, exploit its price advantage by **filling the tank to capacity** ($C = 50.0$ gal):
       $$\text{gallons\_to\_buy} = C - F_{\text{curr}}$$
     * Advance to the **NEXT immediate station** on the route $S_{i+1}$, consuming $\frac{d_{i+1} - d_{\text{curr}}}{\text{MPG}}$ gallons, and re-evaluate from $S_{i+1}$.

5. **Feasibility Validation:**
   If at any point no station exists within full range and the destination is not reachable, the route is impossible to navigate without running out of fuel. The algorithm raises `RouteNotFeasibleError` (`ROUTE_NOT_FEASIBLE`, HTTP 422).

---

## 4. Complexity & Performance

* **Time Complexity:**
  * Deduplication & sorting: $O(K \log K)$ where $K$ is the number of corridor stations ($\sim 20$–$80$).
  * Lookahead traversal: $O(K)$ linear scan.
  * Total runtime: **$< 1.0\text{ ms}$**.
* **Space Complexity:**
  * Pure in-memory traversal: **$O(K)$** auxiliary space.

---

## 5. Worked Examples

### Example 1: Brief A/B/Destination Case (Skip More Expensive Station)
* Route = 700 miles. Start at 0 mi (50 gal).
* Station A at 300 mi ($3.50). Station B at 450 mi ($3.00). Destination at 700 mi.
1. At mile 0, destination (700 mi) is not reachable on 50 gal (500 mi). Vehicle reaches Station A (300 mi) with 20 gal.
2. At Station A ($3.50): Station B (450 mi, $3.00) is within full range ($300 + 500 = 800$) and cheaper.
   - Distance to B = 150 mi $\implies$ 15 gal needed.
   - Current fuel = 20 gal.
   - Gallons to buy at A = $\max(0, 15 - 20) = \mathbf{0.0\text{ gal}}$ (A is skipped!).
3. At Station B (450 mi, 5 gal fuel left): Destination (700 mi) is within full range ($250 \le 500$).
   - Fuel needed for destination = $250 / 10 = 25$ gal.
   - Gallons to buy at B = $25 - 5 = \mathbf{20.0\text{ gal}}$ at $\$3.00 = \mathbf{\$60.00}$.
* **Result:** 1 stop (Station B), 20.0 gallons, **Total Cost: $60.00**.

### Example 2: Cheaper Station Beyond Current Fuel but Within Full Range
* Route = 800 miles.
* Station 1 at 300 mi ($3.50). Station 2 at 600 mi ($3.00). Destination at 800 mi.
1. Vehicle arrives at Station 1 (300 mi) with $50 - 30 = 20$ gal.
   - Current fuel only reaches mile $300 + 200 = 500$.
   - Station 2 (600 mi) is **beyond current fuel**, but **within full range** ($300 + 500 = 800$).
2. Because Station 2 is cheaper ($3.00 < 3.50$), buy just enough to reach Station 2:
   - Distance = 300 mi $\implies$ 30 gal needed.
   - Gallons to buy at Station 1 = $30 - 20 = \mathbf{10.0\text{ gal}}$ at $\$3.50 = \mathbf{\$35.00}$.
3. Arrives at Station 2 with 0.0 gal. Destination is 200 mi away ($\le 500$ mi).
   - Gallons to buy at Station 2 = $200 / 10 = \mathbf{20.0\text{ gal}}$ at $\$3.00 = \mathbf{\$60.00}$.
* **Result:** 2 stops (Station 1: 10 gal, Station 2: 20 gal), **Total Cost: $95.00**.

### Example 3: Local Minimum Fill-Up (Cheaper Station Beyond Full Range)
* Route = 1,000 miles.
* Station 1 at 300 mi ($3.50). Station 2 at 450 mi ($3.80). Station 3 at 850 mi ($2.50).
1. At Station 1 (300 mi, 20 gal left): Full range is 800 mi. Station 3 is at 850 mi (beyond full range).
   - Only Station 2 is within full range, and it is more expensive ($3.80 > 3.50$).
   - Station 1 is a local minimum. Destination is not reachable ($1000 - 300 > 500$).
   - **Action:** Fill to full! Buy $50 - 20 = \mathbf{30.0\text{ gal}}$ at $\$3.50 = \mathbf{\$105.00}$.
   - Advance to next station: Station 2 at 450 mi. Arrive with $50 - 15 = 35$ gal.
2. At Station 2 (450 mi, 35 gal left): Station 3 (850 mi, $2.50) is now within full range ($450 + 500 = 950$)!
   - Distance to Station 3 = 400 mi $\implies$ 40 gal needed.
   - Buy at Station 2: $40 - 35 = \mathbf{5.0\text{ gal}}$ at $\$3.80 = \mathbf{\$19.00}$.
3. At Station 3 (850 mi, 0 gal left): Destination is 150 mi away.
   - Buy at Station 3: $150 / 10 = \mathbf{15.0\text{ gal}}$ at $\$2.50 = \mathbf{\$37.50}$.
* **Result:** 3 stops, **Total Cost: $161.50**.
