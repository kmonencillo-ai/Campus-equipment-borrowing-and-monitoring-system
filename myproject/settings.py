import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# ─── .env loader ──────────────────────────────────────────────────────────────
def load_env_file(path):
    if not path.exists():
        print(f'[settings] WARNING: .env file not found at {path}')
        return

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        # Strip surrounding quotes (single or double) and whitespace
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / '.env')


# ─── Helpers ──────────────────────────────────────────────────────────────────
def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def csv_list(value):
    return [entry.strip() for entry in value.split(',') if entry.strip()]


def build_allowed_hosts(raw_hosts, debug=False, allow_lan_hosts=True):
    hosts = csv_list(raw_hosts)
    if debug and allow_lan_hosts and '*' not in hosts:
        hosts.append('*')
    return hosts


def supabase_config_from_url(supabase_url):
    # Strip any accidental surrounding quotes (safety net)
    supabase_url = supabase_url.strip().strip('"').strip("'")

    parsed_url = urlparse(supabase_url)
    scheme = parsed_url.scheme.lower()

    if scheme not in {'postgres', 'postgresql'}:
        raise RuntimeError(
            f'SUPABASE_DATABASE_URL has an invalid scheme "{scheme}". '
            'It must start with postgresql:// — copy the URI from '
            'Supabase → Settings → Database → Connection string (URI tab).'
        )

    if not parsed_url.hostname:
        raise RuntimeError(
            'SUPABASE_DATABASE_URL is missing a hostname. '
            'Make sure the URL looks like: '
            'postgresql://postgres:PASSWORD@db.xxxx.supabase.co:5432/postgres'
        )

    query_options = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    sslmode = query_options.pop('sslmode', 'require')

    config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parsed_url.path.lstrip('/')),
        'USER': unquote(parsed_url.username or ''),
        'PASSWORD': unquote(parsed_url.password or ''),
        'HOST': parsed_url.hostname or '',
        'PORT': str(parsed_url.port or '5432'),
        'CONN_MAX_AGE': env_int('DJANGO_DB_CONN_MAX_AGE', 60),
    }

    options = {'sslmode': sslmode}
    options.update(query_options)
    config['OPTIONS'] = options

    return config


# ─── Core settings ────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = build_allowed_hosts(
    os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost'),
    DEBUG,
    env_bool('DJANGO_ALLOW_LAN_HOSTS', True),
)

CSRF_TRUSTED_ORIGINS = csv_list(os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', ''))


# ─── Installed apps ───────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'core.middleware.SecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.SessionTimeoutMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'myproject.urls'

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
                'core.context_processors.system_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'myproject.wsgi.application'


# ─── Database ─────────────────────────────────────────────────────────────────
SUPABASE_DATABASE_URL = (os.getenv('SUPABASE_DATABASE_URL') or os.getenv('DATABASE_URL', '')).strip()

if SUPABASE_DATABASE_URL:
    DATABASES = {
        'default': supabase_config_from_url(SUPABASE_DATABASE_URL),
    }
    print(f'[settings] Database: Supabase PostgreSQL ({urlparse(SUPABASE_DATABASE_URL).hostname})')
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.getenv('DJANGO_SQLITE_NAME', 'db.sqlite3'),
        }
    }
    print('[settings] Database: SQLite (local fallback — SUPABASE_DATABASE_URL not set)')


# ─── Password validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ─── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True


# ─── Static files ─────────────────────────────────────────────────────────────
STATIC_URL = os.getenv('DJANGO_STATIC_URL', '/static/')
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
BACKUP_DIR = Path(os.getenv('DJANGO_BACKUP_DIR', str(BASE_DIR / 'backups')))
if not BACKUP_DIR.is_absolute():
    BACKUP_DIR = BASE_DIR / BACKUP_DIR


# ─── Cache ────────────────────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'campus-equipment-cache',
    }
}


# ─── Email ────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('DJANGO_EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('DJANGO_EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.getenv('DJANGO_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('DJANGO_EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('DJANGO_EMAIL_USE_TLS', False)
EMAIL_USE_SSL = env_bool('DJANGO_EMAIL_USE_SSL', False)
DEFAULT_FROM_EMAIL = os.getenv('DJANGO_DEFAULT_FROM_EMAIL', 'noreply@campus-equipment.local')
SERVER_EMAIL = os.getenv('DJANGO_SERVER_EMAIL', DEFAULT_FROM_EMAIL)


# ─── Primary key ──────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ─── Auth redirects ───────────────────────────────────────────────────────────
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
LOGIN_URL = '/login/'


# ─── Session ──────────────────────────────────────────────────────────────────
SESSION_IDLE_TIMEOUT = env_int('DJANGO_SESSION_IDLE_TIMEOUT', 1800)
SESSION_COOKIE_AGE = SESSION_IDLE_TIMEOUT
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'


# ─── Rate limiting ────────────────────────────────────────────────────────────
LOGIN_RATE_LIMIT_ATTEMPTS = env_int('DJANGO_LOGIN_RATE_LIMIT_ATTEMPTS', 5)
LOGIN_RATE_LIMIT_WINDOW = env_int('DJANGO_LOGIN_RATE_LIMIT_WINDOW', 300)


# ─── Security headers ─────────────────────────────────────────────────────────
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURITY_CONTENT_SECURITY_POLICY = os.getenv(
    'DJANGO_CONTENT_SECURITY_POLICY',
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https:; "
    "script-src 'self' 'unsafe-inline' https:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https:;"
)

SECURITY_PERMISSIONS_POLICY = os.getenv(
    'DJANGO_PERMISSIONS_POLICY',
    'camera=(), microphone=(), geolocation=()',
)


# ─── Production safety checks ─────────────────────────────────────────────────
if not DEBUG and SECRET_KEY == 'django-insecure-change-this-in-production':
    raise RuntimeError(
        'DJANGO_SECRET_KEY must be set to a real secret key in production. '
        'Generate one with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
    )

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', True)


# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')


# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
    },
}
