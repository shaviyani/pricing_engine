"""
Backfill estimated revenue on existing cancelled bookings with $0 total_amount.

Uses average confirmed ADR for the same property + arrival month + room type
as the estimate basis. Marks backfilled records with is_revenue_estimated=True.

Usage:
    python manage.py backfill_cancel_revenue
    python manage.py backfill_cancel_revenue --dry-run
    python manage.py backfill_cancel_revenue --property=biosphere-inn
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Avg


class Command(BaseCommand):
    help = 'Backfill estimated revenue on cancelled bookings with $0 amount'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--property', type=str, default=None,
            help='Limit to a specific property code',
        )

    def handle(self, *args, **options):
        from pricing.models import Reservation, Property

        dry_run = options['dry_run']
        prop_code = options['property']

        qs = Reservation.objects.filter(
            status='cancelled',
            total_amount__lte=Decimal('0.00'),
            nights__gt=0,
        )

        if prop_code:
            prop = Property.objects.filter(code=prop_code).first()
            if not prop:
                self.stderr.write(f'Property "{prop_code}" not found.')
                return
            qs = qs.filter(hotel=prop)
            self.stdout.write(f'Filtering to property: {prop}')

        total = qs.count()
        self.stdout.write(f'Found {total} cancelled bookings with $0 revenue')

        if total == 0:
            self.stdout.write('Nothing to backfill.')
            return

        updated = 0
        skipped = 0

        for res in qs.select_related('hotel', 'room_type').iterator():
            # Find comparable confirmed ADR
            comparable = Reservation.objects.filter(
                hotel=res.hotel,
                arrival_date__month=res.arrival_date.month,
                status__in=Reservation.ACTIVE_STATUSES,
                adr__gt=0,
            )
            if res.room_type:
                comparable = comparable.filter(room_type=res.room_type)

            avg_adr = comparable.aggregate(avg=Avg('adr'))['avg']

            if not avg_adr or avg_adr <= 0:
                skipped += 1
                continue

            est_total = (avg_adr * Decimal(str(res.nights))).quantize(Decimal('0.01'))
            est_adr = avg_adr.quantize(Decimal('0.01'))

            if dry_run:
                self.stdout.write(
                    f'  [DRY] {res.confirmation_no} '
                    f'({res.hotel.code if res.hotel else "?"}) '
                    f'{res.arrival_date.month}/{res.arrival_date.year} '
                    f'{res.nights}n -> ${est_total} (ADR ${est_adr})'
                )
            else:
                res.total_amount = est_total
                res.adr = est_adr
                res.is_revenue_estimated = True
                res.notes = (res.notes or '') + ' [Revenue backfilled from comparable ADR]'
                res.save(update_fields=[
                    'total_amount', 'adr', 'is_revenue_estimated', 'notes'
                ])

            updated += 1

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Updated: {updated}, Skipped (no comparable ADR): {skipped}'
        ))
