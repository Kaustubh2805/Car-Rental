# Security Review

## Summary

One medium-severity production transport-security finding was identified and
fixed during Phase 8. No remaining findings were reported for CSRF, object-level
permissions, XSS escaping, upload validation, rate limiting, or `DEBUG=False`
error handling.

| # | Severity | File | Lines | Finding | Confidence | Status |
|---|----------|------|-------|---------|------------|--------|
| 1 | MEDIUM | `config/settings/prod.py` | 5-9 | Production did not enforce HTTPS redirects or HSTS. | 8/10 | Fixed |

The production settings now enable `SECURE_SSL_REDIRECT`, one-year HSTS with
subdomains and preload, and secure session and CSRF cookies. The deployment
proxy must correctly set the configured `X-Forwarded-Proto` header.

## Validation

- Full Django suite: 78 tests passed, 1 skipped.
- Services and views coverage: 93% overall; every reported module is at least
  88%.
- Django checks passed with development and production settings.
- Black and Flake8 passed.
- Catalog listing query count is bounded by an automated test; Django Debug
  Toolbar is available in development.
