"""Signals for account-related model lifecycle events."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import CustomerProfile, User


@receiver(post_save, sender=User)
def create_customer_profile(
    sender: type[User],
    instance: User,
    created: bool,
    **kwargs: object,
) -> None:
    """Create a profile when a customer account is first created."""
    if created and instance.role == User.Role.CUSTOMER:
        CustomerProfile.objects.get_or_create(user=instance)
