"""
Management command to populate season modifier entries for existing data.
"""

from django.core.management.base import BaseCommand
from pricing.models import Season, RateModifier, SeasonModifierOverride


class Command(BaseCommand):
    help = 'Populate season modifier discount entries for all seasons and modifiers'
    
    def handle(self, *args, **options):
        seasons = Season.objects.all()
        modifiers = RateModifier.objects.all()
        
        self.stdout.write(f"Found {seasons.count()} seasons and {modifiers.count()} modifiers")
        
        created_count = 0
        existing_count = 0
        
        for season in seasons:
            for modifier in modifiers:
                entry, created = SeasonModifierOverride.objects.get_or_create(
                    modifier=modifier,
                    season=season,
                    defaults={'discount_percent': modifier.discount_percent}
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(f"  Created: {season.name} - {modifier.name}")
                else:
                    existing_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Complete!"
            f"\n  Created: {created_count} new entries"
            f"\n  Existing: {existing_count} entries"
            f"\n  Total: {created_count + existing_count} entries"
        ))
