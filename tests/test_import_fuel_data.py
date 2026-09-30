import csv
import io
import pytest
from decimal import Decimal
from django.core.management import call_command, CommandError
from fuel_route.models import FuelStation

@pytest.fixture
def sample_coords_csv(tmp_path):
    coords_file = tmp_path / "test_coords.csv"
    rows = [
        {"opis_id": "100", "latitude": "35.123456", "longitude": "-90.123456", "geocode_source": "us_census_batch", "precision": "street_interpolated"},
        {"opis_id": "200", "latitude": "40.654321", "longitude": "-74.654321", "geocode_source": "osm_nominatim", "precision": "poi_match"},
        {"opis_id": "300", "latitude": "32.111111", "longitude": "-96.222222", "geocode_source": "us_census_gazetteer", "precision": "approximate_city"},
    ]
    with open(coords_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["opis_id", "latitude", "longitude", "geocode_source", "precision"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return str(coords_file)

@pytest.fixture
def sample_fuel_csv(tmp_path):
    fuel_file = tmp_path / "test_fuel.csv"
    rows = [
        # OPIS 100 has multiple prices (3.59, 3.19, 3.49) -> Minimum should be 3.19
        {"OPIS Truckstop ID": "100", "Truckstop Name": "Station A", "Address": "100 Highway 1", "City": "Memphis", "State": "TN", "Rack ID": "1", "Retail Price": "3.5900"},
        {"OPIS Truckstop ID": "100", "Truckstop Name": "Station A", "Address": "100 Highway 1", "City": "Memphis", "State": "TN", "Rack ID": "2", "Retail Price": "3.1900"},
        {"OPIS Truckstop ID": "100", "Truckstop Name": "Station A", "Address": "100 Highway 1", "City": "Memphis", "State": "TN", "Rack ID": "3", "Retail Price": "3.4900"},
        
        # OPIS 200 has exact duplicate rows
        {"OPIS Truckstop ID": "200", "Truckstop Name": "Station B", "Address": "200 Route 9", "City": "Newark", "State": "NJ", "Rack ID": "10", "Retail Price": "3.2500"},
        {"OPIS Truckstop ID": "200", "Truckstop Name": "Station B", "Address": "200 Route 9", "City": "Newark", "State": "NJ", "Rack ID": "10", "Retail Price": "3.2500"},
        
        # Canadian stations should be excluded
        {"OPIS Truckstop ID": "991", "Truckstop Name": "Canada Stop 1", "Address": "1 Trans Canada Hwy", "City": "Toronto", "State": "ON", "Rack ID": "20", "Retail Price": "4.1000"},
        {"OPIS Truckstop ID": "992", "Truckstop Name": "Canada Stop 2", "Address": "2 Rue Principale", "City": "Montreal", "State": "QC", "Rack ID": "21", "Retail Price": "4.2000"},
        {"OPIS Truckstop ID": "993", "Truckstop Name": "Canada Stop 3", "Address": "3 Calgary Trail", "City": "Calgary", "State": "AB", "Rack ID": "22", "Retail Price": "3.9000"},

        # Station without coordinates in test_coords.csv (should be skipped)
        {"OPIS Truckstop ID": "888", "Truckstop Name": "No Coords Stop", "Address": "999 Remote Rd", "City": "Nowhere", "State": "NV", "Rack ID": "50", "Retail Price": "3.7500"},
    ]
    with open(fuel_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Rack ID", "Retail Price"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return str(fuel_file)

@pytest.mark.django_db
class TestImportFuelDataCommand:
    def test_import_minimum_price_and_canadian_exclusion(self, sample_fuel_csv, sample_coords_csv):
        out = io.StringIO()
        call_command('import_fuel_data', fuel_csv=sample_fuel_csv, coords_csv=sample_coords_csv, stdout=out)
        output = out.getvalue()

        # Check total imported
        assert FuelStation.objects.count() == 2  # Station 100 and Station 200

        # Minimum price selected for Station 100
        station_100 = FuelStation.objects.get(opis_id=100)
        assert station_100.retail_price == Decimal("3.1900")
        assert station_100.latitude == 35.123456
        assert station_100.longitude == -90.123456
        assert station_100.geocode_source == "us_census_batch"
        assert station_100.precision == "street_interpolated"

        # Canadian stations excluded
        assert not FuelStation.objects.filter(state__in=['ON', 'QC', 'AB']).exists()
        assert "Skipped Canadian province records: 3" in output
        assert "Skipped exact duplicate CSV rows: 1" in output
        assert "Skipped missing coordinates: 1" in output

    def test_idempotent_rerun(self, sample_fuel_csv, sample_coords_csv, tmp_path):
        # First import
        out1 = io.StringIO()
        call_command('import_fuel_data', fuel_csv=sample_fuel_csv, coords_csv=sample_coords_csv, stdout=out1)
        assert FuelStation.objects.count() == 2
        assert "Total stations imported (new): 2" in out1.getvalue()
        assert "Total stations updated (existing): 0" in out1.getvalue()

        # Create updated fuel CSV with new lower price for Station 100
        updated_fuel = tmp_path / "updated_fuel.csv"
        rows = [
            {"OPIS Truckstop ID": "100", "Truckstop Name": "Station A Renamed", "Address": "100 Highway 1", "City": "Memphis", "State": "TN", "Rack ID": "1", "Retail Price": "2.9900"},
            {"OPIS Truckstop ID": "200", "Truckstop Name": "Station B", "Address": "200 Route 9", "City": "Newark", "State": "NJ", "Rack ID": "10", "Retail Price": "3.2500"},
        ]
        with open(updated_fuel, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Rack ID", "Retail Price"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        # Second import (rerun)
        out2 = io.StringIO()
        call_command('import_fuel_data', fuel_csv=str(updated_fuel), coords_csv=sample_coords_csv, stdout=out2)
        
        # Verify idempotency
        assert FuelStation.objects.count() == 2  # No duplicate rows created
        assert "Total stations imported (new): 0" in out2.getvalue()
        assert "Total stations updated (existing): 2" in out2.getvalue()

        # Verify field update
        updated_100 = FuelStation.objects.get(opis_id=100)
        assert updated_100.retail_price == Decimal("2.9900")
        assert updated_100.name == "Station A Renamed"

    def test_missing_files_error(self, tmp_path):
        missing_file = str(tmp_path / "nonexistent.csv")
        existing_file = str(tmp_path / "existing.csv")
        with open(existing_file, 'w') as f:
            f.write("header\n")

        with pytest.raises(CommandError, match="Required fuel prices file not found"):
            call_command('import_fuel_data', fuel_csv=missing_file, coords_csv=existing_file)

        with pytest.raises(CommandError, match="Required coordinates file not found"):
            call_command('import_fuel_data', fuel_csv=existing_file, coords_csv=missing_file)
