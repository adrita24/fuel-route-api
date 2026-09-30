"""
Standalone Geolocation Script for Fuel Stations (Phase 0.5)

This script is a standalone preprocessing tool to produce data/station_coordinates.csv
for all US fuel stations in fuel-prices-for-be-assessment.csv.

Multi-Tier Architecture:
  - Deduplicate stations to unique (Address, City, State), excluding Canadian provinces.
  - Tier 1: US Census Geocoder Batch API (cached under data/cache/) with precision "street_interpolated".
  - Plausibility Check: Distance to city centroid <= 30.0 miles.
  - Sanity Check: Dynamic State Bounding Boxes derived from Census Gazetteer (+0.3 deg margin).
  - Tier 2: OpenStreetMap Nominatim for Tier 1 failures with precision "poi_match", 1.05s rate limit,
            custom User-Agent with valid contact email, and resumable on-disk cache.
  - Tier 3: Official US Census Gazetteer Places (primary) and GeoNames US places (fallback)
            with precision "approximate_city".
  - Unresolved: Any station no tier can place is written to data/unresolved_stations.csv.

CLI Options:
  --tier1-tier3-only : Run Step 1 (Census + Gazetteer/GeoNames fallback), write CSVs, and stop.
  --run-nominatim    : Run Step 2 (Nominatim background crawl and upgrade Tier 3 stations).
"""

import csv
import io
import json
import math
import os
import re
import sys
import time
import zipfile
import urllib.request
import urllib.parse
import collections
from typing import Dict, List, Tuple, Optional, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, 'fuel-prices-for-be-assessment.csv')
DATA_DIR = os.path.join(BASE_DIR, 'data')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
GAZETTEER_DIR = os.path.join(DATA_DIR, 'gazetteer')
OUTPUT_CSV_PATH = os.path.join(DATA_DIR, 'station_coordinates.csv')
UNRESOLVED_CSV_PATH = os.path.join(DATA_DIR, 'unresolved_stations.csv')
NOMINATIM_CACHE_PATH = os.path.join(DATA_DIR, 'nominatim_cache.json')

GAZETTEER_YEAR = 2024
GAZETTEER_URL = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{GAZETTEER_YEAR}_Gazetteer/{GAZETTEER_YEAR}_Gaz_place_national.zip"
GAZETTEER_ZIP_PATH = os.path.join(GAZETTEER_DIR, f"{GAZETTEER_YEAR}_Gaz_place_national.zip")
GAZETTEER_TXT_PATH = os.path.join(GAZETTEER_DIR, f"{GAZETTEER_YEAR}_Gaz_place_national.txt")

GEONAMES_URL = "http://download.geonames.org/export/zip/US.zip"
GEONAMES_ZIP_PATH = os.path.join(GAZETTEER_DIR, "geonames_US.zip")
GEONAMES_TXT_PATH = os.path.join(GAZETTEER_DIR, "geonames_US.txt")

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "SpotterFuelRouteOptimizer/1.0 (contact: adrita.g.2005@gmail.com)"

MAX_CENTROID_DISTANCE_MILES = 30.0
CANADIAN_PROVINCES = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'}

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2.0)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2.0)**2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def clean_station_name(name: str) -> str:
    cleaned = re.sub(r'#\s*\d+', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -#')
    return cleaned

class GeolocationPipeline:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(GAZETTEER_DIR, exist_ok=True)

        self.gazetteer_places: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.geonames_places: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.state_bounding_boxes: Dict[str, Tuple[float, float, float, float]] = {}
        self.nominatim_cache: Dict[str, Any] = self._load_json(NOMINATIM_CACHE_PATH)

    def _load_json(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_json(self, path: str, data: Dict[str, Any]):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def download_and_parse_gazetteer(self):
        if not os.path.exists(GAZETTEER_TXT_PATH):
            print(f"[Gazetteer] Downloading {GAZETTEER_URL} ...")
            urllib.request.urlretrieve(GAZETTEER_URL, GAZETTEER_ZIP_PATH)
            with zipfile.ZipFile(GAZETTEER_ZIP_PATH, 'r') as zf:
                zf.extractall(GAZETTEER_DIR)

        print(f"[Gazetteer] Indexing Census Gazetteer Places from {GAZETTEER_TXT_PATH} ...")
        state_lat_lons = collections.defaultdict(lambda: {'lats': [], 'lons': []})

        with open(GAZETTEER_TXT_PATH, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f, delimiter='\t')
            headers = [h.strip() for h in next(reader)]
            state_idx = headers.index('USPS')
            name_idx = headers.index('NAME')
            lat_idx = headers.index('INTPTLAT')
            lon_idx = headers.index('INTPTLONG')

            for row in reader:
                if len(row) > max(state_idx, name_idx, lat_idx, lon_idx):
                    state = row[state_idx].strip().upper()
                    raw_name = row[name_idx].strip().lower()
                    try:
                        lat = float(row[lat_idx].strip())
                        lon = float(row[lon_idx].strip())
                    except ValueError:
                        continue

                    state_lat_lons[state]['lats'].append(lat)
                    state_lat_lons[state]['lons'].append(lon)

                    self.gazetteer_places[(state, raw_name)] = (lat, lon)
                    cleaned = raw_name
                    for s in [' city', ' town', ' cdp', ' village', ' borough', ' municipality', ' township', ' urban county', ' charter township']:
                        if cleaned.endswith(s):
                            cleaned = cleaned[:-len(s)].strip()
                            break
                    self.gazetteer_places[(state, cleaned)] = (lat, lon)
                    if 'st. ' in cleaned: self.gazetteer_places[(state, cleaned.replace('st. ', 'saint '))] = (lat, lon)
                    if 'saint ' in cleaned: self.gazetteer_places[(state, cleaned.replace('saint ', 'st. '))] = (lat, lon)
                    if 'ft. ' in cleaned: self.gazetteer_places[(state, cleaned.replace('ft. ', 'fort '))] = (lat, lon)
                    if 'fort ' in cleaned: self.gazetteer_places[(state, cleaned.replace('fort ', 'ft. '))] = (lat, lon)
                    if 'mt. ' in cleaned: self.gazetteer_places[(state, cleaned.replace('mt. ', 'mount '))] = (lat, lon)
                    if 'mount ' in cleaned: self.gazetteer_places[(state, cleaned.replace('mount ', 'mt. '))] = (lat, lon)
                    if '-' in cleaned: self.gazetteer_places[(state, cleaned.split('-')[0].strip())] = (lat, lon)

        # Derive state bounding boxes dynamically
        for state, coords in state_lat_lons.items():
            self.state_bounding_boxes[state] = (
                min(coords['lats']) - 0.3, max(coords['lats']) + 0.3,
                min(coords['lons']) - 0.3, max(coords['lons']) + 0.3
            )

        # Download & parse GeoNames US Places for unincorporated coverage
        if not os.path.exists(GEONAMES_TXT_PATH):
            print(f"[GeoNames] Downloading {GEONAMES_URL} ...")
            req = urllib.request.Request(GEONAMES_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                with open(GEONAMES_ZIP_PATH, 'wb') as out_f:
                    out_f.write(resp.read())
            with zipfile.ZipFile(GEONAMES_ZIP_PATH, 'r') as zf:
                zf.extract('US.txt', GAZETTEER_DIR)
                os.replace(os.path.join(GAZETTEER_DIR, 'US.txt'), GEONAMES_TXT_PATH)

        print(f"[GeoNames] Indexing GeoNames US postal places from {GEONAMES_TXT_PATH} ...")
        with open(GEONAMES_TXT_PATH, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f, delimiter='\t')
            for row in reader:
                if len(row) >= 11:
                    st = row[4].strip().upper()
                    place = row[2].strip().lower()
                    try:
                        lat = float(row[9].strip())
                        lon = float(row[10].strip())
                        if (st, place) not in self.geonames_places:
                            self.geonames_places[(st, place)] = (lat, lon)
                        # Also normalized variants
                        cleaned = place
                        for s in [' city', ' town', ' village']:
                            if cleaned.endswith(s):
                                cleaned = cleaned[:-len(s)].strip()
                                break
                        self.geonames_places[(st, cleaned)] = (lat, lon)
                        if 'saint ' in cleaned: self.geonames_places[(st, cleaned.replace('saint ', 'st. '))] = (lat, lon)
                        if 'st. ' in cleaned: self.geonames_places[(st, cleaned.replace('st. ', 'saint '))] = (lat, lon)
                        if 'fort ' in cleaned: self.geonames_places[(st, cleaned.replace('fort ', 'ft. '))] = (lat, lon)
                        if 'ft. ' in cleaned: self.geonames_places[(st, cleaned.replace('ft. ', 'fort '))] = (lat, lon)
                        if 'mount ' in cleaned: self.geonames_places[(st, cleaned.replace('mount ', 'mt. '))] = (lat, lon)
                        if 'mt. ' in cleaned: self.geonames_places[(st, cleaned.replace('mt. ', 'mount '))] = (lat, lon)
                    except ValueError:
                        continue

        print(f"[Index] Census Gazetteer: {len(self.gazetteer_places)} places | GeoNames: {len(self.geonames_places)} places.")

    def get_city_centroid(self, city: str, state: str) -> Optional[Tuple[float, float, str]]:
        st = state.strip().upper()
        ct = city.strip().lower()

        # Try Gazetteer first
        if (st, ct) in self.gazetteer_places:
            lat, lon = self.gazetteer_places[(st, ct)]
            return lat, lon, "us_census_gazetteer"

        for alt in [ct.replace('saint ', 'st. '), ct.replace('st. ', 'saint '), ct.replace('ft. ', 'fort '), ct.replace('fort ', 'ft. '), ct.replace('mount ', 'mt. '), ct.replace('mt. ', 'mount '), ct.replace(' ', ''), ct.replace('-', ' '), ct.replace(' ', '-')]:
            if (st, alt) in self.gazetteer_places:
                lat, lon = self.gazetteer_places[(st, alt)]
                return lat, lon, "us_census_gazetteer"

        # Try GeoNames fallback
        if (st, ct) in self.geonames_places:
            lat, lon = self.geonames_places[(st, ct)]
            return lat, lon, "geonames_centroid"

        for alt in [ct.replace('saint ', 'st. '), ct.replace('st. ', 'saint '), ct.replace('ft. ', 'fort '), ct.replace('fort ', 'ft. '), ct.replace('mount ', 'mt. '), ct.replace('mt. ', 'mount '), ct.replace(' ', ''), ct.replace('-', ' '), ct.replace(' ', '-')]:
            if (st, alt) in self.geonames_places:
                lat, lon = self.geonames_places[(st, alt)]
                return lat, lon, "geonames_centroid"

        return None

    def validate_point(self, lat: float, lon: float, city: str, state: str) -> Tuple[bool, Optional[float], str]:
        st = state.strip().upper()
        bbox = self.state_bounding_boxes.get(st)
        if bbox:
            min_lat, max_lat, min_lon, max_lon = bbox
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                return False, None, "outside_state_bbox"

        cent_info = self.get_city_centroid(city, state)
        if cent_info:
            cent_lat, cent_lon, _ = cent_info
            dist = haversine_miles(lat, lon, cent_lat, cent_lon)
            if dist > MAX_CENTROID_DISTANCE_MILES:
                return False, dist, "centroid_distance_exceeded"
            return True, dist, ""

        return True, None, ""

    def load_tier1_cache(self) -> Dict[str, Dict[str, Any]]:
        import glob
        tier1_results = {}
        chunk_files = sorted(glob.glob(os.path.join(CACHE_DIR, 'census_chunk_*.csv')))
        for cf in chunk_files:
            with open(cf, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 6:
                        loc_id = row[0].strip().strip('"')
                        status = row[2].strip().strip('"')
                        match_type = row[3].strip().strip('"') if len(row) > 3 else ""
                        if status == "Match":
                            coords_str = row[5].strip().strip('"')
                            if ',' in coords_str:
                                parts = coords_str.split(',')
                                try:
                                    lon = float(parts[0].strip())
                                    lat = float(parts[1].strip())
                                    tier1_results[loc_id] = {
                                        'lat': lat,
                                        'lon': lon,
                                        'match_type': match_type
                                    }
                                except ValueError:
                                    pass
        return tier1_results

    def execute_step1(self):
        print("=================================================================")
        print("PHASE 0.5 - STEP 1: RESOLVING US FUEL STATIONS (TIER 1 + TIER 3)")
        print("=================================================================")

        self.download_and_parse_gazetteer()

        # Load raw CSV and dedupe
        with open(CSV_PATH, 'r', encoding='utf-8', errors='replace') as f:
            raw_rows = list(csv.DictReader(f))

        us_stations = []
        unique_locs: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for r in raw_rows:
            st = r['State'].strip().upper()
            if st in CANADIAN_PROVINCES:
                continue
            opis_id = r['OPIS Truckstop ID'].strip()
            name = r['Truckstop Name'].strip()
            addr = r['Address'].strip()
            city = r['City'].strip()
            us_stations.append({
                'opis_id': opis_id,
                'name': name,
                'address': addr,
                'city': city,
                'state': st
            })
            loc_key = (addr.lower(), city.lower(), st)
            if loc_key not in unique_locs:
                unique_locs[loc_key] = {
                    'loc_id': str(len(unique_locs)),
                    'name': name,
                    'address': addr,
                    'city': city,
                    'state': st
                }

        unique_loc_list = list(unique_locs.values())
        print(f"Total US Station rows: {len(us_stations)}")
        print(f"Unique US Physical Locations: {len(unique_loc_list)}")

        # 1. Evaluate Tier 1 (Census)
        tier1_raw = self.load_tier1_cache()
        location_coords: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        tier1_accepted = 0

        for item in unique_loc_list:
            loc_id = item['loc_id']
            if loc_id in tier1_raw:
                cand = tier1_raw[loc_id]
                is_valid, dist, _ = self.validate_point(cand['lat'], cand['lon'], item['city'], item['state'])
                if is_valid:
                    key = (item['address'].lower(), item['city'].lower(), item['state'])
                    location_coords[key] = {
                        'lat': cand['lat'],
                        'lon': cand['lon'],
                        'geocode_source': 'us_census_batch',
                        'precision': 'street_interpolated'
                    }
                    tier1_accepted += 1

        print(f"Tier 1 (Census) Validated & Accepted: {tier1_accepted} locations.")

        # 2. Evaluate Tier 3 (Gazetteer / GeoNames Centroids)
        tier3_accepted = 0
        unresolved_locs = []

        for item in unique_loc_list:
            key = (item['address'].lower(), item['city'].lower(), item['state'])
            if key in location_coords:
                continue

            cent_info = self.get_city_centroid(item['city'], item['state'])
            if cent_info:
                lat, lon, src = cent_info
                # Validate inside state bbox
                st = item['state']
                bbox = self.state_bounding_boxes.get(st)
                if bbox and (bbox[0] <= lat <= bbox[1] and bbox[2] <= lon <= bbox[3]):
                    location_coords[key] = {
                        'lat': lat,
                        'lon': lon,
                        'geocode_source': src,
                        'precision': 'approximate_city'
                    }
                    tier3_accepted += 1
                else:
                    unresolved_locs.append(item)
            else:
                unresolved_locs.append(item)

        print(f"Tier 3 (Centroids) Validated & Accepted: {tier3_accepted} locations.")
        print(f"Unresolved Locations: {len(unresolved_locs)}")

        # 3. Map back to OPIS IDs (1 row per OPIS ID)
        seen_opis = set()
        final_rows = []
        unresolved_stations = []
        counts_per_tier = collections.defaultdict(int)

        for s in us_stations:
            opis_id = s['opis_id']
            if opis_id in seen_opis:
                continue
            seen_opis.add(opis_id)

            key = (s['address'].lower(), s['city'].lower(), s['state'])
            if key in location_coords:
                c = location_coords[key]
                counts_per_tier[c['geocode_source']] += 1
                final_rows.append({
                    'opis_id': opis_id,
                    'latitude': f"{c['lat']:.6f}",
                    'longitude': f"{c['lon']:.6f}",
                    'geocode_source': c['geocode_source'],
                    'precision': c['precision']
                })
            else:
                unresolved_stations.append({
                    'opis_id': opis_id,
                    'name': s['name'],
                    'address': s['address'],
                    'city': s['city'],
                    'state': s['state'],
                    'reason': 'no_centroid_found_in_gazetteer_or_geonames'
                })

        # Write data/station_coordinates.csv
        with open(OUTPUT_CSV_PATH, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['opis_id', 'latitude', 'longitude', 'geocode_source', 'precision']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in final_rows:
                writer.writerow(r)

        # Write data/unresolved_stations.csv
        with open(UNRESOLVED_CSV_PATH, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['opis_id', 'name', 'address', 'city', 'state', 'reason']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for u in unresolved_stations:
                writer.writerow(u)

        print("\n=================================================================")
        print("STEP 1 COMPLETE: DATA FILES READY FOR PHASE 1")
        print("=================================================================")
        print(f"Total Unique US Stations (OPIS IDs): {len(seen_opis)}")
        print(f"Total Successfully Geocoded: {len(final_rows)} ({len(final_rows)/len(seen_opis)*100:.2f}%)")
        print(f"Total Unresolved Stations: {len(unresolved_stations)} ({len(unresolved_stations)/len(seen_opis)*100:.2f}%)")
        print(f"Output File Created: {OUTPUT_CSV_PATH}")
        print(f"Unresolved File Created: {UNRESOLVED_CSV_PATH}\n")

        print("Counts Per Tier / Geocode Source:")
        for src, count in sorted(counts_per_tier.items()):
            print(f"  - {src}: {count} stations ({count/len(seen_opis)*100:.1f}%)")
        print("=================================================================\n")

    def execute_tier2_background(self):
        """
        Background task to query Nominatim for Tier 3 locations and upgrade them.
        """
        import requests
        print("=================================================================")
        print("PHASE 0.5 - STEP 2: NOMINATIM BACKGROUND UPGRADE")
        print("=================================================================")
        self.download_and_parse_gazetteer()

        # Load existing station_coordinates.csv
        if not os.path.exists(OUTPUT_CSV_PATH):
            print("Error: station_coordinates.csv does not exist. Run step 1 first.")
            return

        with open(OUTPUT_CSV_PATH, 'r', encoding='utf-8') as f:
            current_coords = {r['opis_id']: r for r in csv.DictReader(f)}

        # Load stations mapping
        with open(CSV_PATH, 'r', encoding='utf-8', errors='replace') as f:
            raw_rows = list(csv.DictReader(f))

        us_stations = {}
        for r in raw_rows:
            st = r['State'].strip().upper()
            if st in CANADIAN_PROVINCES: continue
            opis_id = r['OPIS Truckstop ID'].strip()
            if opis_id not in us_stations:
                us_stations[opis_id] = {
                    'name': r['Truckstop Name'].strip(),
                    'address': r['Address'].strip(),
                    'city': r['City'].strip(),
                    'state': st
                }

        # Filter stations currently at Tier 3 ("approximate_city")
        tier3_opis_ids = [
            opis_id for opis_id, r in current_coords.items()
            if r['precision'] == 'approximate_city'
        ]
        print(f"Total Tier 3 stations candidate for Nominatim upgrade: {len(tier3_opis_ids)}")

        # Dedupe by (cleaned_name, city, state)
        unique_queries = {}
        for opis_id in tier3_opis_ids:
            s = us_stations[opis_id]
            cleaned_name = clean_station_name(s['name'])
            q_key = (cleaned_name.lower(), s['city'].lower(), s['state'].upper())
            if q_key not in unique_queries:
                unique_queries[q_key] = {
                    'name': cleaned_name,
                    'city': s['city'],
                    'state': s['state'],
                    'opis_ids': []
                }
            unique_queries[q_key]['opis_ids'].append(opis_id)

        print(f"Unique Nominatim queries to perform: {len(unique_queries)}")

        upgraded_count = 0
        headers = {'User-Agent': NOMINATIM_USER_AGENT}

        for idx, (q_key, q_item) in enumerate(unique_queries.items()):
            cache_key = f"{q_key[0]}|{q_key[1]}|{q_key[2]}"
            res = self.nominatim_cache.get(cache_key)

            if res is None and cache_key not in self.nominatim_cache:
                query = f"{q_item['name']}, {q_item['city']}, {q_item['state']}"
                params = {'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'us'}
                try:
                    time.sleep(1.05)
                    resp = requests.get(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and len(data) > 0:
                            lat = float(data[0]['lat'])
                            lon = float(data[0]['lon'])
                            osm_class = data[0].get('class', '')
                            osm_type = data[0].get('type', '')
                            res = {
                                'lat': lat,
                                'lon': lon,
                                'osm_class': osm_class,
                                'osm_type': osm_type
                            }
                            self.nominatim_cache[cache_key] = res
                        else:
                            self.nominatim_cache[cache_key] = False
                    else:
                        self.nominatim_cache[cache_key] = False
                except Exception:
                    self.nominatim_cache[cache_key] = False

                self._save_json(NOMINATIM_CACHE_PATH, self.nominatim_cache)

            # If match found, apply plausibility checks
            if res and isinstance(res, dict):
                lat = res['lat']
                lon = res['lon']
                is_valid, dist, _ = self.validate_point(lat, lon, q_item['city'], q_item['state'])
                if is_valid:
                    # Upgrade the stations!
                    for o_id in q_item['opis_ids']:
                        if current_coords[o_id]['precision'] != 'poi_match':
                            current_coords[o_id] = {
                                'opis_id': o_id,
                                'latitude': f"{lat:.6f}",
                                'longitude': f"{lon:.6f}",
                                'geocode_source': 'osm_nominatim',
                                'precision': 'poi_match'
                            }
                            upgraded_count += 1

            if (idx + 1) % 50 == 0 or (idx + 1) == len(unique_queries):
                print(f"Processed {idx + 1}/{len(unique_queries)} queries (Upgraded stations: {upgraded_count})")
                # Periodically sync to station_coordinates.csv
                with open(OUTPUT_CSV_PATH, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['opis_id', 'latitude', 'longitude', 'geocode_source', 'precision'])
                    writer.writeheader()
                    for r in current_coords.values():
                        writer.writerow(r)

        # Final write
        with open(OUTPUT_CSV_PATH, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['opis_id', 'latitude', 'longitude', 'geocode_source', 'precision'])
            writer.writeheader()
            for r in current_coords.values():
                writer.writerow(r)

        # Print final counts
        final_counts = collections.defaultdict(int)
        for r in current_coords.values():
            final_counts[r['geocode_source']] += 1

        print("\n=================================================================")
        print("NOMINATIM UPGRADE COMPLETE!")
        print("=================================================================")
        print(f"Total Stations in Dataset: {len(current_coords)}")
        print("Final Counts Per Tier / Geocode Source:")
        for src, count in sorted(final_counts.items()):
            print(f"  - {src}: {count} stations ({count/len(current_coords)*100:.1f}%)")
        print("=================================================================\n")

if __name__ == '__main__':
    pipeline = GeolocationPipeline()
    if '--run-nominatim' in sys.argv:
        pipeline.execute_tier2_background()
    else:
        pipeline.execute_step1()
