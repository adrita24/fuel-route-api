import pytest
from django.conf import settings

class TestPhase1Settings:
    def test_vehicle_and_route_defaults(self):
        assert settings.MPG == 10.0
        assert settings.MAX_RANGE_MILES == 500.0
        assert settings.TANK_CAPACITY_GALLONS == 50.0
        assert settings.ROUTE_CORRIDOR_MILES == 10.0

    def test_installed_apps_and_middleware(self):
        assert 'rest_framework' in settings.INSTALLED_APPS
        assert 'fuel_route' in settings.INSTALLED_APPS

    def test_strict_database_config_raises_without_vars(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured
        monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **kw: None)
        monkeypatch.setenv('USE_SQLITE', '0')
        monkeypatch.delenv('DB_NAME', raising=False)
        monkeypatch.delenv('DB_USER', raising=False)

        import importlib
        import config.settings
        with pytest.raises(ImproperlyConfigured, match="Missing required PostgreSQL environment variable"):
            importlib.reload(config.settings)

    def test_use_sqlite_mode(self, monkeypatch):
        monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **kw: None)
        monkeypatch.setenv('USE_SQLITE', '1')
        monkeypatch.delenv('DB_NAME', raising=False)
        monkeypatch.delenv('DB_USER', raising=False)

        import importlib
        import config.settings
        reloaded = importlib.reload(config.settings)
        assert reloaded.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
