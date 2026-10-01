import csv
import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from fuel_route.models import FuelStation, StationMatchCache

CANADIAN_PROVINCES = {
    'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'
}

class Command(BaseCommand):
    help = "Import US fuel station prices and preprocessed coordinates into PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            '--fuel-csv',
            type=str,
            default=str(settings.BASE_DIR / 'fuel-prices-for-be-assessment.csv'),
            help="Path to the raw fuel prices CSV file."
        )
        parser.add_argument(
            '--coords-csv',
            type=str,
            default=str(settings.BASE_DIR / 'data' / 'station_coordinates.csv'),
            help="Path to the precomputed station coordinates CSV file."
        )

    def handle(self, *args, **options):
        fuel_csv_path = options['fuel_csv']
        coords_csv_path = options['coords_csv']

        # 1. Fail early with clear message if required files do not exist
        if not os.path.exists(fuel_csv_path):
            raise CommandError(f"Required fuel prices file not found: {fuel_csv_path}")

        if not os.path.exists(coords_csv_path):
            raise CommandError(f"Required coordinates file not found: {coords_csv_path}")

        self.stdout.write(f"Reading coordinates from: {coords_csv_path}")
        self.stdout.write(f"Reading fuel prices from: {fuel_csv_path}")

        # 2. Load coordinates by opis_id
        coords_by_opis: Dict[int, Dict[str, Any]] = {}
        with open(coords_csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    opis_id = int(row['opis_id'].strip())
                    lat = float(row['latitude'].strip())
                    lon = float(row['longitude'].strip())
                    coords_by_opis[opis_id] = {
                        'latitude': lat,
                        'longitude': lon,
                        'geocode_source': row.get('geocode_source', '').strip(),
                        'precision': row.get('precision', '').strip(),
                    }
                except (ValueError, KeyError):
                    continue

        self.stdout.write(f"Loaded {len(coords_by_opis)} coordinate records.")

        # 3. Read fuel prices CSV, dedupe, filter Canadian provinces, and select minimum price per station
        seen_exact_rows = set()
        stations_by_opis: Dict[int, Dict[str, Any]] = {}
        skipped_canadian = 0
        skipped_duplicate_rows = 0

        with open(fuel_csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Handle possible varying column headers gracefully
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k}
                opis_id_raw = clean_row.get('OPIS Truckstop ID') or clean_row.get('opis_id')
                name = clean_row.get('Truckstop Name') or clean_row.get('name', '')
                addr = clean_row.get('Address') or clean_row.get('address', '')
                city = clean_row.get('City') or clean_row.get('city', '')
                state = (clean_row.get('State') or clean_row.get('state', '')).upper()
                rack_id = clean_row.get('Rack ID') or clean_row.get('rack_id', '')
                price_raw = clean_row.get('Retail Price') or clean_row.get('retail_price', '')

                if not opis_id_raw or not price_raw:
                    continue

                # Exclude Canadian rows
                if state in CANADIAN_PROVINCES:
                    skipped_canadian += 1
                    continue

                # Dedupe exact duplicate rows
                row_tuple = (opis_id_raw, name, addr, city, state, rack_id, price_raw)
                if row_tuple in seen_exact_rows:
                    skipped_duplicate_rows += 1
                    continue
                seen_exact_rows.add(row_tuple)

                try:
                    opis_id = int(opis_id_raw)
                    price = Decimal(str(price_raw))
                except (ValueError, ArithmeticError):
                    continue

                if opis_id not in stations_by_opis:
                    stations_by_opis[opis_id] = {
                        'opis_id': opis_id,
                        'name': name,
                        'address': addr,
                        'city': city,
                        'state': state,
                        'min_price': price,
                    }
                else:
                    if price < stations_by_opis[opis_id]['min_price']:
                        stations_by_opis[opis_id]['min_price'] = price

        # 4. Join station records with coordinates
        skipped_missing_coords = 0
        station_objects = []

        for opis_id, sdata in stations_by_opis.items():
            if opis_id not in coords_by_opis:
                skipped_missing_coords += 1
                continue

            c = coords_by_opis[opis_id]
            station_objects.append(FuelStation(
                opis_id=opis_id,
                name=sdata['name'],
                address=sdata['address'],
                city=sdata['city'],
                state=sdata['state'],
                latitude=c['latitude'],
                longitude=c['longitude'],
                retail_price=sdata['min_price'],
                geocode_source=c['geocode_source'],
                precision=c['precision']
            ))

        # 5. Idempotent upsert via bulk_create with update_conflicts
        target_ids = [s.opis_id for s in station_objects]
        existing_ids = set(FuelStation.objects.filter(opis_id__in=target_ids).values_list('opis_id', flat=True))
        imported_count = len(station_objects) - len(existing_ids)
        updated_count = len(existing_ids)

        # 5. Atomic transaction: upsert station objects and invalidate StationMatchCache
        with transaction.atomic():
            if station_objects:
                FuelStation.objects.bulk_create(
                    station_objects,
                    update_conflicts=True,
                    unique_fields=['opis_id'],
                    update_fields=[
                        'name', 'address', 'city', 'state', 'latitude', 'longitude',
                        'retail_price', 'geocode_source', 'precision'
                    ],
                    batch_size=1000
                )

            # 6. Invalidate StationMatchCache (station prices/locations may have updated)
            cleared_count, _ = StationMatchCache.objects.all().delete()

        # 7. Print structured summary
        self.stdout.write(self.style.SUCCESS("\nFuel data import complete."))
        self.stdout.write(f"  - Total stations imported (new): {imported_count}")
        self.stdout.write(f"  - Total stations updated (existing): {updated_count}")
        self.stdout.write(f"  - Total stations stored in DB: {len(station_objects)}")
        self.stdout.write(f"  - Skipped Canadian province records: {skipped_canadian}")
        self.stdout.write(f"  - Skipped exact duplicate CSV rows: {skipped_duplicate_rows}")
        self.stdout.write(f"  - Skipped missing coordinates: {skipped_missing_coords}")
        self.stdout.write(f"  - StationMatchCache rows cleared: {cleared_count}\n")
