import os
import environ
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_file):
    environ.Env.read_env(env_file)

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-*xjv6%^$t&n-o=r$gbqlkl9=5_6r66&qkz#(h=p0b%68$el#9i",
)

DEBUG = env.bool("DEBUG", default=True)

# ALLOWED_HOSTS - explicitly set for production
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=[
        "api.ankivn.com",
        "ankivn.com",
        "www.ankivn.com",
        "localhost",
        "127.0.0.1",
    ],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "lms",
    "rest_framework",
    "corsheaders",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

# JWT Token Settings
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=24),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CORS
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "https://lms.ankivn.com",
        "https://www.ankivn.com",
        "https://ankivn.com",
        "http://localhost:3000",
    ],
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

AUTH_USER_MODEL = "accounts.User"

if os.environ.get("DATABASE_URL"):
    # production / Heroku dùng DATABASE_URL (Postgres)
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.config(
            default=os.environ["DATABASE_URL"],
            conn_max_age=600,
        )
    }
else:
    # development local: dùng SQLite cho dễ migrate
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

ROOT_URLCONF = "core.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files (User uploaded content)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ============================================
# APPWRITE CONFIGURATION (for .apkg file storage)
# ============================================
APPWRITE_ENDPOINT = env("APPWRITE_ENDPOINT", default="https://sgp.cloud.appwrite.io/v1")
APPWRITE_PROJECT_ID = env("APPWRITE_PROJECT_ID", default="695fd05f00280bd0cce6")
APPWRITE_API_KEY = env("APPWRITE_API_KEY", default="standard_64a3a0274b69dea5189d40cd7e303053293374ea28938e3e02b93c9cc1e974539d7a2d8ae0e0f58b29ae2f1389e2d0e0ef3ed9a2ea6679f2ea771ef7245811488bf1a3dd93dce41bb5b997001097e9932a3544e5f2e78103f2d9f61d7fca59101039d7180727d867437d226be3cab84a9738e13bd62f420cb009a27319836f88")
APPWRITE_BUCKET_ID = env("APPWRITE_BUCKET_ID", default="695fd372002412b4c017")

# ============================================
# ANKI ADDON SSO (Token Exchange Secret)
# ============================================
ANKI_ADDON_SECRET = env("ANKI_ADDON_SECRET", default="f1d76aa60054747a400f8a7018579d1dbfde10980c44c8b71b3a891f9e0f8ac2")
