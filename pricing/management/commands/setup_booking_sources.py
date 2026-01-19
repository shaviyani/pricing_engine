"""
Management command to set up default booking sources.

Usage:
    python manage.py setup_booking_sources
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Set up default booking sources for import mapping'
    
    def handle(self, *args, **options):
        from pricing.models import BookingSource, Channel
        
        # Get channels
        ota_channel = Channel.objects.filter(name__icontains='OTA').first()
        direct_channel = Channel.objects.filter(name__icontains='DIRECT').first()
        
        # Default booking sources
        default_sources = [
            {
                'name': 'Booking.com',
                'import_values': ['Booking.com', 'booking.com', 'Booking', 'BDC'],
                'channel': ota_channel,
                'is_direct': False,
                'sort_order': 1,
            },
            {
                'name': 'Expedia',
                'import_values': ['Expedia', 'expedia', 'Expedia.com'],
                'channel': ota_channel,
                'is_direct': False,
                'sort_order': 2,
            },
            {
                'name': 'Agoda',
                'import_values': ['Agoda', 'agoda', 'Agoda.com'],
                'channel': ota_channel,
                'is_direct': False,
                'sort_order': 3,
            },
            {
                'name': 'Direct - Walk-in',
                'import_values': ['Walk-in', 'Walk in', 'Walkin', 'walk-in'],
                'channel': direct_channel,
                'is_direct': True,
                'sort_order': 10,
            },
            {
                'name': 'Direct - Phone',
                'import_values': ['Phone', 'Telephone', 'Call'],
                'channel': direct_channel,
                'is_direct': True,
                'sort_order': 11,
            },
            {
                'name': 'Direct - Email',
                'import_values': ['Email', 'E-mail', 'email'],
                'channel': direct_channel,
                'is_direct': True,
                'sort_order': 12,
            },
            {
                'name': 'Direct - Website',
                'import_values': ['Website', 'Web', 'Direct', 'Online'],
                'channel': direct_channel,
                'is_direct': True,
                'sort_order': 13,
            },
            {
                'name': 'Direct - Staff',
                'import_values': [],  # Matched via user_mappings
                'user_mappings': ['Reekko', 'Maais'],  # Your staff names
                'channel': direct_channel,
                'is_direct': True,
                'sort_order': 14,
            },
            {
                'name': 'Unknown',
                'import_values': [],
                'channel': None,
                'is_direct': False,
                'sort_order': 999,
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for source_data in default_sources:
            source, created = BookingSource.objects.update_or_create(
                name=source_data['name'],
                defaults={
                    'import_values': source_data.get('import_values', []),
                    'user_mappings': source_data.get('user_mappings', []),
                    'channel': source_data.get('channel'),
                    'is_direct': source_data.get('is_direct', False),
                    'sort_order': source_data.get('sort_order', 0),
                    'active': True,
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created: {source.name}'))
            else:
                updated_count += 1
                self.stdout.write(f'Updated: {source.name}')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done! Created: {created_count}, Updated: {updated_count}'))
        
        if not ota_channel:
            self.stdout.write(self.style.WARNING('Warning: No OTA channel found. Please create channels first.'))
        if not direct_channel:
            self.stdout.write(self.style.WARNING('Warning: No DIRECT channel found. Please create channels first.'))