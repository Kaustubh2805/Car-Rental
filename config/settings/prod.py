"""Production settings."""

from decouple import Csv, config

from .base import *  # noqa: F403,F401

DEBUG = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", cast=bool, default=True)
SECURE_HSTS_SECONDS = config(
    "SECURE_HSTS_SECONDS",
    cast=int,
    default=31_536_000,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    cast=bool,
    default=True,
)
SECURE_HSTS_PRELOAD = config(
    "SECURE_HSTS_PRELOAD",
    cast=bool,
    default=True,
)
SESSION_COOKIE_SECURE = config(
    "SESSION_COOKIE_SECURE",
    cast=bool,
    default=True,
)
CSRF_COOKIE_SECURE = config(
    "CSRF_COOKIE_SECURE",
    cast=bool,
    default=True,
)
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if config("TRUST_X_FORWARDED_PROTO", cast=bool, default=True)
    else None
)
SECURE_REFERRER_POLICY = config(
    "SECURE_REFERRER_POLICY",
    default="same-origin",
)
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    cast=Csv(),
    default="",
)
