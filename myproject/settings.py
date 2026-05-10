import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / '.env')


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
    parsed_url = urlparse(supabase_url)
    scheme = parsed_url.scheme.lower()

    if scheme not in {'postgres', 'postgresql'}:
        raise RuntimeError('SUPABASE_DATABASE_URL must be the database URI copied from your Supabase project.')

    query_options = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    sslmode = query_options.pop('sslmode', 'require')

    config = {
        # Supabase's Django connection uses the database driver below.
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parsed_url.path.lstrip('/')),
        'USER': unquote(parsed_url.username or ''),
        'PASSWORD': unquote(parsed_url.password or ''),
        'HOST': parsed_url.hostname or '',
        'PORT': str(parsed_url.port or ''),
        'CONN_MAX_AGE': env_int('DJANGO_DB_CONN_MAX_AGE', 60),
    }

    options = {}
    if sslmode:
        options['sslmode'] = sslmode
    options.update(query_options)
    if options:
        config['OPTIONS'] = options

    return config


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = build_allowed_hosts(
    os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost'),
    DEBUG,
    env_bool('DJANGO_ALLOW_LAN_HOSTS', True),
)
CSRF_TRUSTED_ORIGINS = csv_list(os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', ''))


# Application definition
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


# Database
SUPABASE_DATABASE_URL = os.getenv('SUPABASE_DATABASE_URL', '').strip()

if SUPABASE_DATABASE_URL:
    DATABASES = {
        'default': supabase_config_from_url(SUPABASE_DATABASE_URL),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.getenv('DJANGO_SQLITE_NAME', 'db.sqlite3'),
        }
    }


# Password validation
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
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Manila'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = os.getenv('DJANGO_STATIC_URL', '/static/')
STATIC_ROOT = BASE_DIR / 'staticfiles'
BACKUP_DIR = Path(os.getenv('DJANGO_BACKUP_DIR', str(BASE_DIR / 'backups')))
if not BACKUP_DIR.is_absolute():
    BACKUP_DIR = BASE_DIR / BACKUP_DIR

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'campus-equipment-cache',
    }
}

EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('DJANGO_EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('DJANGO_EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.getenv('DJANGO_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('DJANGO_EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('DJANGO_EMAIL_USE_TLS', False)
EMAIL_USE_SSL = env_bool('DJANGO_EMAIL_USE_SSL', False)
DEFAULT_FROM_EMAIL = os.getenv('DJANGO_DEFAULT_FROM_EMAIL', 'noreply@campus-equipment.local')
SERVER_EMAIL = os.getenv('DJANGO_SERVER_EMAIL', DEFAULT_FROM_EMAIL)


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Login / Logout redirects
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
LOGIN_URL = '/login/'
SESSION_IDLE_TIMEOUT = env_int('DJANGO_SESSION_IDLE_TIMEOUT', 1800)
LOGIN_RATE_LIMIT_ATTEMPTS = env_int('DJANGO_LOGIN_RATE_LIMIT_ATTEMPTS', 5)
LOGIN_RATE_LIMIT_WINDOW = env_int('DJANGO_LOGIN_RATE_LIMIT_WINDOW', 300)
SESSION_COOKIE_AGE = SESSION_IDLE_TIMEOUT
SESSION_SAVE_EVERY_REQUEST = True

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
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

if not DEBUG and SECRET_KEY == 'django-insecure-change-this-in-production':
    raise RuntimeError('Set DJANGO_SECRET_KEY in production before starting the server.')

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', True)

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

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
