import pytest
from decimal import Decimal
from django.db import IntegrityError
from fuel_route.models import FuelStation

@pytest.mark.django_db
class TestFuelStationModel:
    def test_create_fuel_station(self):
        station = FuelStation.objects.create(
            opis_id=1001,
            name="Test Stop",
            address="123 Highway 66",
            city="Springfield",
            state="MO",
            latitude=37.208957,
            longitude=-93.292299,
            retail_price=Decimal("3.4590"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )
        assert station.pk is not None
        assert station.opis_id == 1001
        assert station.retail_price == Decimal("3.4590")
        assert "Test Stop" in str(station)
        assert "Springfield" in str(station)
        assert "$3.4590" in str(station)

    def test_unique_opis_id_constraint(self):
        FuelStation.objects.create(
            opis_id=2001,
            name="Station One",
            address="456 Main St",
            city="Dallas",
            state="TX",
            latitude=32.7767,
            longitude=-96.7970,
            retail_price=Decimal("3.1990"),
            geocode_source="us_census_batch",
            precision="street_interpolated"
        )

        with pytest.raises(IntegrityError):
            FuelStation.objects.create(
                opis_id=2001,
                name="Duplicate Station",
                address="789 Other St",
                city="Dallas",
                state="TX",
                latitude=32.7767,
                longitude=-96.7970,
                retail_price=Decimal("3.2990"),
                geocode_source="us_census_batch",
                precision="street_interpolated"
            )
