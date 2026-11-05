"""Helpers for recording administrative changes."""

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.accounts.models import User
from apps.core.models import AuditLog


def record_audit(
    *,
    actor: User,
    action: str,
    obj: models.Model,
    changes: dict[str, Any],
) -> AuditLog:
    """Persist an audit event for a model instance."""
    content_type = ContentType.objects.get_for_model(obj)
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        content_type=content_type,
        object_id=str(obj.pk),
        object_repr=str(obj)[:255],
        changes=changes,
    )
