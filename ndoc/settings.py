"""
Django settings for ndoc project.

"""

import os
from pathlib import Path
from opensearchpy import OpenSearch

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-x(4ykt8#-+1*&6qr0(&err)=^n=948(rx1tipzs#kmj%_ct&nu"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

# Application definition

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "search",
    "docs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ndoc.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ndoc.wsgi.application"

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE     = "UTC"
USE_I18N      = True
USE_TZ        = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "_static"]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


ALLOWED_HOSTS = ['localhost', '127.0.0.1']

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "_templates"],
        'APP_DIRS': True,
    },
]

DOCS_DIR = os.path.join(BASE_DIR, '_data')

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
        "apache_style": {
            "format": "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%d/%b/%Y %H:%M:%S",
        }  
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "apache_style",
            "level": "DEBUG",  # <- wypisuj wszystkie komunikaty
        },
    },

    "root": {
        "handlers": ["console"],
        "level": "DEBUG",  # <- także DEBUG z logger.getLogger(__name__)
    },

    "loggers": {
        # dla konkretnej aplikacji (np. search)
        "search.views": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "docs.views": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    }
}

OPENSEARCH = {
    "HOST": "localhost",
    "PORT": 9200,
    "USER": None,   
    "PASSWORD": None,
    "USE_SSL": False,
    "VERIFY_CERTS": False,
    "DOC_INDEX": "ndoc_documents",
    "SECTION_INDEX": "ndoc_sections",
}
