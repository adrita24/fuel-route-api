"""
Dataset Analysis Script for fuel-prices-for-be-assessment.csv
Phase 0 Inspection and Verification
"""

import csv
import collections
import statistics
import os

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'fuel-prices-for-be-assessment.csv')
CANADIAN_PROVINCES = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'}

def run_analysis():
    with open(CSV_PATH, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        headers = next(reader)
        raw_rows = list(reader)

    total_rows = len(raw_rows)
    print("=================================================================")
    print("PHASE 0: DATASET AUDIT REPORT - fuel-prices-for-be-assessment.csv")
    print("=================================================================")
    print(f"Total Rows: {total_rows}")
    print(f"Columns ({len(headers)}): {headers}\n")

    # 1. Missing Values
    empty_counts = {h: 0 for h in headers}
    for r in raw_rows:
        for idx, val in enumerate(r):
            if val is None or val.strip() == '':
                empty_counts[headers[idx]] += 1
    print("1. Missing / Empty Values:")
    for col, count in empty_counts.items():
        print(f"   - {col}: {count}")

    # 2. Exact Duplicates
    counter = collections.Counter(tuple(r) for r in raw_rows)
    exact_dupes = sum(count - 1 for count in counter.values() if count > 1)
    print(f"\n2. Duplicate Records:")
    print(f"   - Redundant exact duplicate rows: {exact_dupes}")

    # 3. Station IDs (OPIS Truckstop ID)
    opis_ids = [r[0].strip() for r in raw_rows]
    opis_counter = collections.Counter(opis_ids)
    unique_opis = len(opis_counter)
    multi_opis = {k: v for k, v in opis_counter.items() if v > 1}
    dist_records = collections.Counter(opis_counter.values())

    print(f"\n3. Station ID Analysis (OPIS Truckstop ID):")
    print(f"   - Total unique OPIS IDs: {unique_opis}")
    print(f"   - Stations with multiple records: {len(multi_opis)} ({len(multi_opis)/unique_opis*100:.1f}%)")
    print(f"   - Record frequency breakdown per station:")
    for num_recs, count in sorted(dist_records.items()):
        print(f"       * {num_recs} record(s): {count} stations")

    # 4. Physical Station Identifiers
    addr_city_state = [(r[2].strip().lower(), r[3].strip().lower(), r[4].strip().upper()) for r in raw_rows]
    unique_addresses = len(set(addr_city_state))
    print(f"\n4. Physical Station Identifiers:")
    print(f"   - Unique physical addresses (Address, City, State): {unique_addresses}")
    print(f"   - Multi-tenant / co-located plazas sharing an address: {unique_opis - unique_addresses}")

    # 5. Geographic Scope & States
    states_counter = collections.Counter(r[4].strip().upper() for r in raw_rows)
    us_rows = [r for r in raw_rows if r[4].strip().upper() not in CANADIAN_PROVINCES]
    ca_rows = [r for r in raw_rows if r[4].strip().upper() in CANADIAN_PROVINCES]
    us_opis = set(r[0].strip() for r in us_rows)
    ca_opis = set(r[0].strip() for r in ca_rows)
    us_cities = set((r[3].strip().title(), r[4].strip().upper()) for r in us_rows)

    print(f"\n5. Geographic Scope:")
    print(f"   - Total distinct state codes: {len(states_counter)}")
    print(f"   - US Records: {len(us_rows)} across 48 contiguous states (Unique US Stations: {len(us_opis)})")
    print(f"   - Canadian Records: {len(ca_rows)} across 9 provinces (Unique CA Stations: {len(ca_opis)})")
    print(f"   - Unique US City/State combinations: {len(us_cities)}")

    # 6. Price Distribution
    prices = [float(r[6].strip()) for r in raw_rows]
    prices.sort()
    n = len(prices)
    print(f"\n6. Price Distribution ($/gallon):")
    print(f"   - Min: ${prices[0]:.4f}")
    print(f"   - 5th Percentile: ${prices[int(0.05 * n)]:.4f}")
    print(f"   - 25th Percentile (Q1): ${prices[int(0.25 * n)]:.4f}")
    print(f"   - Median (50th): ${prices[int(0.50 * n)]:.4f}")
    print(f"   - Mean: ${statistics.mean(prices):.4f}")
    print(f"   - 75th Percentile (Q3): ${prices[int(0.75 * n)]:.4f}")
    print(f"   - 95th Percentile: ${prices[int(0.95 * n)]:.4f}")
    print(f"   - Max: ${prices[-1]:.4f}")
    print(f"   - Std Dev: ${statistics.stdev(prices):.4f}")

    # 7. Intra-Station Price Variance
    opis_to_prices = collections.defaultdict(list)
    for r in raw_rows:
        opis_to_prices[r[0].strip()].append(float(r[6].strip()))
    varying_prices = {k: v for k, v in opis_to_prices.items() if (max(v) - min(v)) > 1e-4}
    price_diffs = [max(v) - min(v) for v in varying_prices.values()]

    print(f"\n7. Multiple Price Records for the Same Station:")
    print(f"   - Stations with multiple records: {len(multi_opis)}")
    print(f"   - Stations where prices differ across records: {len(varying_prices)}")
    print(f"   - Mean difference across records: ${statistics.mean(price_diffs):.4f}")
    print(f"   - Max difference across records: ${max(price_diffs):.4f}")
    print("=================================================================\n")

if __name__ == '__main__':
    run_analysis()
