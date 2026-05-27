from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from orders.models import Review


class Command(BaseCommand):
    help = "Cleans up old reviews based on sentiment retention policies"

    def handle(self, *args, **kwargs):
        now = timezone.now()

        # Policy: Keep positive/neutral for 30 days
        standard_cutoff = now - timedelta(days=30)
        standard_deleted, _ = Review.objects.filter(
            sentiment__in=["positive", "neutral"], created_at__lt=standard_cutoff
        ).delete()

        # Policy: Keep negative feedback for 90 days
        negative_cutoff = now - timedelta(days=90)
        negative_deleted, _ = Review.objects.filter(
            sentiment="negative", created_at__lt=negative_cutoff
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {standard_deleted} standard reviews and {negative_deleted} old negative reviews."
            )
        )
