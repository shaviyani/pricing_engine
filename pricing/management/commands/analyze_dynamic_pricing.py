"""
Analyze reservation data and generate dynamic pricing suggestions.

Usage:
    python manage.py analyze_dynamic_pricing --hotel=thundi
    python manage.py analyze_dynamic_pricing --hotel=thundi --dry-run
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Analyze booking data and generate dynamic pricing multiplier suggestions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hotel', type=str, required=True,
            help='Property code (e.g., thundi)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show suggestions without saving to database'
        )

    def handle(self, *args, **options):
        from pricing.models import Property
        from pricing.services.version_service import DynamicPricingOptimizer

        prop_code = options['hotel']
        dry_run = options['dry_run']

        try:
            hotel = Property.objects.get(code=prop_code, is_active=True)
        except Property.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Property "{prop_code}" not found.'))
            return

        self.stdout.write(f'Analyzing dynamic pricing for {hotel.name}...')
        self.stdout.write('')

        optimizer = DynamicPricingOptimizer(hotel)

        if dry_run:
            suggestions = optimizer.analyze()
            if not suggestions:
                self.stdout.write(self.style.WARNING('No suggestions generated. Need more booking data.'))
                return

            self.stdout.write(self.style.SUCCESS(f'{len(suggestions)} suggestions:'))
            self.stdout.write('')

            for s in suggestions:
                arrow = '+' if s['direction'] == 'increase' else '-'
                conf = s['confidence'].upper()
                self.stdout.write(
                    f"  [{conf}] {s['season_type'].title()} | {s['occupancy_band_label']} | "
                    f"{s['window_band_label']}: "
                    f"x{s['current_multiplier']} -> x{s['suggested_multiplier']} "
                    f"({arrow}{abs(s['suggested_multiplier'] - s['current_multiplier']):.2f}) "
                    f"| {s['sample_size']} bookings | "
                    f"RevPAR impact: {s['revpar_improvement_pct']:+.1f}%"
                )
            self.stdout.write('')
            self.stdout.write('(dry run — not saved. Remove --dry-run to save.)')
        else:
            suggestions = optimizer.generate_suggestions()
            if not suggestions:
                self.stdout.write(self.style.WARNING('No suggestions generated. Need more booking data.'))
                return

            self.stdout.write(self.style.SUCCESS(f'{len(suggestions)} suggestions saved:'))
            self.stdout.write('')

            for s in suggestions:
                arrow = '+' if s.direction == 'increase' else '-'
                self.stdout.write(
                    f"  [{s.confidence.upper()}] {s.season_type.title()} | "
                    f"{s.occupancy_band_label} | {s.window_band_label}: "
                    f"x{s.current_multiplier} -> x{s.suggested_multiplier} "
                    f"| {s.sample_size} bookings"
                )
            self.stdout.write('')
            self.stdout.write('Review and accept/reject in the Pricing > Dynamic Pricing tab.')
