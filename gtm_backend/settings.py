import os
import sys
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

if sys.version_info >= (3, 14):
    raise RuntimeError(
        "Unsupported Python version for this project. "
        "Use Python 3.12 or 3.13 (your virtualenv was created with Python "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})."
    )


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-9263f+lwv4&+%!o@7zqu&f%+kfzu2dnhy68ef7qq&h(2=gs%6p'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

HAS_JAZZMIN = False
HAS_JAZZMIN = False

# ЖК/дома/подъезды: используется для логина по квартире.
# Формат логина (без дефисов): <complex><building><entrance><apartment>
# Пример: nasip204220 = ЖК nasip, дом 20, подъезд 4, кв 220.
#
# Можно добавлять новые ЖК по аналогии.
DBN_COMPLEXES = {
    "nasip": {
        "title": "Эл Насип",
        "buildings": {
            # Дом 20: 5 подъездов
            "20": {
                "entrance_ranges": [
                    (1, 1, 63),
                    (2, 64, 117),
                    (3, 118, 171),
                    (4, 172, 225),
                    (5, 226, 279),
                ],
            },
            # Дом 18: 2 подъезда
            "18": {
                "entrance_ranges": [
                    (1, 1, 54),
                    (2, 55, 108),
                ],
            },
            # Блок D: 2 подъезда
            "d": {
                "entrance_ranges": [
                    (1, 1, 56),
                    (2, 57, 112),
                ],
            },
            # Блок E: продолжение D (подъезды 3–4)
            "e": {
                "entrance_ranges": [
                    (3, 113, 162),
                    (4, 163, 212),
                ],
            },
        },
    },
}


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'api.apps.ApiConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'api.middleware.SimpleCorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = "gtm_backend.urls"

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'builtins': [
                'api.templatetags.compat_filters',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = "gtm_backend.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "ru-ru"

LANGUAGES = [
    ("ru", "Русский"),
]

TIME_ZONE = 'Asia/Bishkek'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# MQTT
# For quick testing this falls back to the public HiveMQ broker.
# In production replace these with private broker values via environment variables.
MQTT_HOST = os.environ.get("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_TLS = os.environ.get("MQTT_TLS", "0")
MQTT_TRANSPORT = os.environ.get("MQTT_TRANSPORT", "tcp")
MQTT_WS_PATH = os.environ.get("MQTT_WS_PATH", "")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "")
MQTT_KEEPALIVE = int(os.environ.get("MQTT_KEEPALIVE", "30"))
MQTT_QOS = int(os.environ.get("MQTT_QOS", "1"))
MQTT_RETAIN = os.environ.get("MQTT_RETAIN", "0")
MQTT_BRIDGE_URL = os.environ.get("MQTT_BRIDGE_URL", "")
MQTT_BRIDGE_SECRET = os.environ.get("MQTT_BRIDGE_SECRET", "")
MQTT_BRIDGE_TIMEOUT = os.environ.get("MQTT_BRIDGE_TIMEOUT", "10")
