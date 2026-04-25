"""Django settings for cookbook project.

For more information on this file, see
https://docs.djangoproject.com/en/stable/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/stable/ref/settings/
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / "subdir"
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = "_$=$%eqxk$8ss4n7mtgarw^5$8^d5+c83!vwatr@i_81myb=e4"

DEBUG = True

ALLOWED_HOSTS = []

ROOT_URLCONF = "cookbook.urls"

WSGI_APPLICATION = "cookbook.wsgi.application"

APPEND_SLASH = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Apps & Middleware
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "graphene_django",
    "django_filters",
    "django_graphene_filters",
    # Local
    "cookbook.recipes.apps.RecipesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]


# ---------------------------------------------------------------------------
# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Database mode — mutually exclusive
# ---------------------------------------------------------------------------
# Two modes, toggled by the ``COOKBOOK_SHARDED`` env var:
#
#   unset       — single-DB.  Only ``default`` (→ ``db.sqlite3``) exists.
#                 Django cannot see the shard files at all.
#
#   "1"         — sharded.    Only ``default`` (→ ``db_shard_a.sqlite3``)
#                 and ``shard_b`` (→ ``db_shard_b.sqlite3``) exist.
#                 Django cannot see ``db.sqlite3`` at all.
#
# Django requires a ``default`` entry, so under sharded mode ``default``
# is the primary shard (shard A) and ``shard_b`` is the secondary.  All
# ``Model.objects.create(...)`` calls without ``.using(...)`` land on
# shard A; explicit ``.using("shard_b")`` targets shard B.
#
# The library itself is agnostic to this layout — it simply honours
# whatever alias the caller queryset carries via ``queryset.db``.  See
# ``docs/spec-db_sharding.md`` for the full alias-propagation rule.
#
# Usage:
#     uv run pytest                                                # single-DB
#     COOKBOOK_SHARDED=1 uv run pytest                             # sharded
#     COOKBOOK_SHARDED=1 uv run python manage.py seed_shards       # populate shards
if os.environ.get("COOKBOOK_SHARDED") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_shard_a.sqlite3",
        },
        "shard_b": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_shard_b.sqlite3",
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        },
    }


# ---------------------------------------------------------------------------
# Auth
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_REDIRECT_URL = "/graphql/"
LOGOUT_REDIRECT_URL = "/login/"


# ---------------------------------------------------------------------------
# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# https://docs.djangoproject.com/en/stable/howto/static-files/
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"


# ---------------------------------------------------------------------------
# Third-party: Graphene
# ---------------------------------------------------------------------------

GRAPHENE = {
    "SCHEMA": "cookbook.schema.schema",
    "SCHEMA_INDENT": 2,
    "MIDDLEWARE": ("graphene_django.debug.DjangoDebugMiddleware",),
}


# ---------------------------------------------------------------------------
# Third-party: django-graphene-filters
# ---------------------------------------------------------------------------

DJANGO_GRAPHENE_FILTERS = {
    "HIDE_FLAT_FILTERS": False,
}
