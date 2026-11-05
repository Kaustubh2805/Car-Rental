"""Send one-time pickup and return reminders for reservations in the next day."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.bookings.models import Reservation


class Command(BaseCommand):
    help = "Send pickup and return reminders due in the next 24 hours."

    def handle(self, *args, **options):
        now = timezone.now()
        deadline = now + timedelta(hours=24)
        reservations = Reservation.objects.select_related(
            "customer",
            "vehicle",
            "pickup_location",
            "return_location",
        )
        pickup_count = 0
        return_count = 0

        pickups = reservations.filter(
            status=Reservation.Status.CONFIRMED,
            pickup_datetime__gt=now,
            pickup_datetime__lte=deadline,
            pickup_reminder_sent_at__isnull=True,
        )
        for reservation in pickups.iterator():
            self._send(reservation, "pickup")
            Reservation.objects.filter(
                pk=reservation.pk,
                pickup_reminder_sent_at__isnull=True,
            ).update(pickup_reminder_sent_at=timezone.now())
            pickup_count += 1

        returns = reservations.filter(
            status=Reservation.Status.ACTIVE,
            return_datetime__gt=now,
            return_datetime__lte=deadline,
            return_reminder_sent_at__isnull=True,
        )
        for reservation in returns.iterator():
            self._send(reservation, "return")
            Reservation.objects.filter(
                pk=reservation.pk,
                return_reminder_sent_at__isnull=True,
            ).update(return_reminder_sent_at=timezone.now())
            return_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {pickup_count} pickup and {return_count} return reminders."
            )
        )

    @staticmethod
    def _send(reservation, kind):
        subject_action = "Pickup" if kind == "pickup" else "Return"
        context = {"reservation": reservation, "kind": kind}
        message = EmailMultiAlternatives(
            subject=f"{subject_action} reminder: {reservation.reference}",
            body=render_to_string("emails/rental_reminder.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reservation.customer.email],
        )
        message.attach_alternative(
            render_to_string("emails/rental_reminder.html", context),
            "text/html",
        )
        message.send(fail_silently=False)
