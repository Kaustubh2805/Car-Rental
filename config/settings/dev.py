"""Development settings."""

from importlib.util import find_spec

from .base import *  # noqa: F403

DEBUG = config("DEBUG", cast=bool, default=True)  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

if DEBUG and find_spec("debug_toolbar"):
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE.insert(  # noqa: F405
        MIDDLEWARE.index("django.middleware.common.CommonMiddleware") + 1,  # noqa: F405
        "debug_toolbar.middleware.DebugToolbarMiddleware",
    )
    INTERNAL_IPS = ["127.0.0.1"]
