"""Email notifications for reservation lifecycle events."""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_reservation_email(reservation, event: str) -> None:
    """Send an HTML and text reservation notification."""
    subjects = {
        "created": f"Booking received: {reservation.reference}",
        "modified": f"Booking updated: {reservation.reference}",
        "cancelled": f"Booking cancelled: {reservation.reference}",
    }
    if event not in subjects:
        raise ValueError(f"Unknown reservation email event: {event}")

    context = {
        "reservation": reservation,
        "customer": reservation.customer,
        "vehicle": reservation.vehicle,
    }
    text_body = render_to_string(
        f"emails/reservation_{event}.txt",
        context,
    )
    html_body = render_to_string(
        f"emails/reservation_{event}.html",
        context,
    )
    message = EmailMultiAlternatives(
        subject=subjects[event],
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[reservation.customer.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
