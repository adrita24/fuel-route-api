"""
Django settings for the Fuel Route Optimization project.
Built with Django 6.1.1 and Django REST Framework.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / '.env')

# Security settings
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-spotter-fuel-route-opt-phase1-dev-key')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'fuel_route',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ==============================================================================
# Database Configuration
# ==============================================================================
# Strict database setup: PostgreSQL is required by default.
# Only falls back to SQLite if USE_SQLITE=1 is explicitly set (for tests only).
USE_SQLITE = os.getenv('USE_SQLITE', '0').lower() in ('1', 'true', 'yes')

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    from django.core.exceptions import ImproperlyConfigured

    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')

    missing_vars = []
    if not DB_NAME:
        missing_vars.append('DB_NAME')
    if not DB_USER:
        missing_vars.append('DB_USER')

    if missing_vars:
        raise ImproperlyConfigured(
            f"Database configuration error: Missing required PostgreSQL environment variable(s): "
            f"{', '.join(missing_vars)}. Configure them in your .env file, or set USE_SQLITE=1 "
            f"for offline test execution."
        )

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': DB_NAME,
            'USER': DB_USER,
            'PASSWORD': DB_PASSWORD or '',
            'HOST': DB_HOST,
            'PORT': DB_PORT,
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'EXCEPTION_HANDLER': 'fuel_route.handlers.custom_exception_handler',
}

# ==============================================================================
# Vehicle & Route Optimization Configuration (Phase 1 Settings)
# ==============================================================================
MPG = float(os.getenv('MPG', '10'))
MAX_RANGE_MILES = float(os.getenv('MAX_RANGE_MILES', '500'))
# Derived: MAX_RANGE_MILES / MPG unless explicitly specified
_default_tank = (MAX_RANGE_MILES / MPG) if MPG > 0 else 50.0
TANK_CAPACITY_GALLONS = float(os.getenv('TANK_CAPACITY_GALLONS', str(_default_tank)))
ROUTE_CORRIDOR_MILES = float(os.getenv('ROUTE_CORRIDOR_MILES', '10'))

# ==============================================================================
# Logging Configuration
# ==============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
    },
    'loggers': {
        'fuel_route': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
