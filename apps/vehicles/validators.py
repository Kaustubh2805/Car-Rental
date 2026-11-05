"""Validators for uploaded vehicle images."""

from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "WEBP": {".webp"},
}


def validate_vehicle_image(image) -> None:
    """Allow JPEG, PNG, or WebP images no larger than five MiB."""
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError("Images must be 5 MB or smaller.")

    extension = Path(image.name).suffix.lower()
    try:
        image.seek(0)
        with Image.open(image) as uploaded_image:
            image_format = uploaded_image.format
            uploaded_image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValidationError("Upload a valid JPEG, PNG, or WebP image.") from error
    finally:
        image.seek(0)

    if extension not in ALLOWED_IMAGE_FORMATS.get(image_format, set()):
        raise ValidationError(
            "Image file extension must match its JPEG, PNG, or WebP content."
        )
