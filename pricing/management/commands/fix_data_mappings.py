"""
One-time data fix: Map existing reservations to Channels and Room Types.

Run after fixing the import pipeline:
    python manage.py fix_data_mappings --dry-run
    python manage.py fix_data_mappings
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from pricing.models import (
    Reservation, Channel, BookingSource, RoomType, Property,
)
from pricing.models.analytics import RoomTypeMapping


class Command(BaseCommand):
    help = 'Fix channel and room type mappings on existing reservations'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without saving')
        parser.add_argument('--property', type=str,
                            help='Fix only this property code')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        prop_code = options.get('property')

        properties = Property.objects.filter(is_active=True)
        if prop_code:
            properties = properties.filter(code=prop_code)

        for prop in properties:
            self.stdout.write(f'\n=== {prop.name} ===')
            self._ensure_channels(prop, dry_run)
            self._fix_booking_source_channels(prop, dry_run)
            self._fix_reservation_channels(prop, dry_run)
            self._fix_reservation_room_types(prop, dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN — no changes saved'))

    def _ensure_channels(self, prop, dry_run):
        """Create default channels if property has none."""
        existing = Channel.objects.filter(hotel=prop).count()
        if existing > 0:
            self.stdout.write(f'  Channels: {existing} exist')
            return

        self.stdout.write(self.style.WARNING(f'  Channels: 0 — creating defaults'))
        if not dry_run:
            Channel.objects.create(hotel=prop, name='OTA (Booking.com)',
                                   base_discount_percent=0, commission_percent=15, sort_order=1)
            Channel.objects.create(hotel=prop, name='Travel Agent',
                                   base_discount_percent=22, commission_percent=10, sort_order=2)
            Channel.objects.create(hotel=prop, name='Direct',
                                   base_discount_percent=24, commission_percent=0, sort_order=3)

    def _fix_booking_source_channels(self, prop, dry_run):
        """Map BookingSource records to Channels."""
        ota_keywords = ['booking.com', 'agoda', 'expedia', 'trip.com', 'hostelworld',
                        'bookmybooking', 'internet booking']
        direct_keywords = ['walk-in', 'walk in', 'direct', 'fit', 'web booking',
                           'unknown', 'house use', 'complimentary', 'owner',
                           'fam trip', 'pms']
        agent_keywords = ['travel', 'agent', 'tours', 'tribe', 'island story',
                          'malvi', 'awesome', 'operator']

        channels = {
            'ota': (Channel.objects.filter(hotel=prop, name__icontains='ota').first()
                    or Channel.objects.filter(hotel=prop, name__icontains='booking').first()),
            'direct': Channel.objects.filter(hotel=prop, name__icontains='direct').first(),
            'agent': (Channel.objects.filter(hotel=prop, name__icontains='agent').first()
                      or Channel.objects.filter(hotel=prop, name__icontains='travel').first()),
        }

        # Get all booking sources that have reservations for this property
        source_ids = Reservation.objects.filter(
            hotel=prop, booking_source__isnull=False
        ).values_list('booking_source_id', flat=True).distinct()

        sources = BookingSource.objects.filter(id__in=source_ids)
        fixed = 0

        for bs in sources:
            if bs.channel_id:
                continue

            name_lower = bs.name.lower()
            target_channel = None

            if any(kw in name_lower for kw in ota_keywords):
                target_channel = channels.get('ota')
            elif any(kw in name_lower for kw in agent_keywords):
                target_channel = channels.get('agent')
            elif any(kw in name_lower for kw in direct_keywords):
                target_channel = channels.get('direct')
            else:
                # Default unmapped sources to Direct
                target_channel = channels.get('direct')

            if target_channel:
                self.stdout.write(f'  BookingSource "{bs.name}" → {target_channel.name}')
                if not dry_run:
                    bs.channel = target_channel
                    bs.save(update_fields=['channel'])
                fixed += 1

        self.stdout.write(f'  BookingSources fixed: {fixed}')

    def _fix_reservation_channels(self, prop, dry_run):
        """Set reservation.channel from booking_source.channel."""
        unmapped = Reservation.objects.filter(
            hotel=prop, channel__isnull=True, booking_source__isnull=False
        ).select_related('booking_source', 'booking_source__channel')

        fixed = 0
        for res in unmapped:
            if res.booking_source and res.booking_source.channel:
                if not dry_run:
                    res.channel = res.booking_source.channel
                    res.save(update_fields=['channel'])
                fixed += 1

        total = Reservation.objects.filter(hotel=prop).count()
        still_unmapped = Reservation.objects.filter(hotel=prop, channel__isnull=True).count()
        self.stdout.write(
            f'  Reservations channel fixed: {fixed}/{total} '
            f'(still unmapped: {still_unmapped})'
        )

    def _fix_reservation_room_types(self, prop, dry_run):
        """Map room_type_name to RoomType objects using fuzzy matching."""
        room_types = {rt.name.lower(): rt for rt in RoomType.objects.filter(hotel=prop)}

        if not room_types:
            self.stdout.write(self.style.WARNING(
                f'  No room types defined — skipping room type mapping'
            ))
            return

        unmapped = Reservation.objects.filter(
            hotel=prop, room_type__isnull=True
        ).exclude(room_type_name='').exclude(room_type_name__isnull=True)

        name_counts = unmapped.values('room_type_name').annotate(c=Count('id')).order_by('-c')

        fixed_total = 0
        for row in name_counts:
            name = row['room_type_name']
            name_lower = name.lower()
            matched_rt = None

            # Check persistent RoomTypeMapping first
            mapping = RoomTypeMapping.objects.filter(
                hotel=prop, import_name__iexact=name,
            ).select_related('room_type').first()
            if mapping:
                matched_rt = mapping.room_type
            else:
                # Exact match
                if name_lower in room_types:
                    matched_rt = room_types[name_lower]
                else:
                    # Substring match
                    for rt_name, rt_obj in room_types.items():
                        if rt_name in name_lower or name_lower in rt_name:
                            matched_rt = rt_obj
                            break

                    # Keyword match
                    if not matched_rt:
                        if any(kw in name_lower for kw in ['standard', 'twin', 'double']):
                            matched_rt = (room_types.get('standard garden')
                                          or room_types.get('standard room'))
                        elif any(kw in name_lower for kw in ['deluxe', 'premium', 'superior']):
                            matched_rt = (room_types.get('deluxe ocean view')
                                          or room_types.get('deluxe room')
                                          or room_types.get('deluxe'))
                        elif any(kw in name_lower for kw in ['suite', 'honeymoon', 'penthouse', 'villa']):
                            matched_rt = (room_types.get('honeymoon suite')
                                          or room_types.get('suite'))

            if matched_rt:
                count = row['c']
                self.stdout.write(f'  "{name}" ({count}) → {matched_rt.name}')
                if not dry_run:
                    Reservation.objects.filter(
                        hotel=prop, room_type__isnull=True, room_type_name=name
                    ).update(room_type=matched_rt)
                fixed_total += count

        total_unmapped = unmapped.count()
        self.stdout.write(f'  Room types fixed: {fixed_total}/{total_unmapped}')
