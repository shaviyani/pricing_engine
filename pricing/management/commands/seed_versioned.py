"""
Seed Biosphere Inn data with versioning and dynamic pricing.
Creates org, property, v1 published version, all pricing components, 
and dynamic pricing rules from spreadsheet model.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from datetime import date
from django.utils import timezone


class Command(BaseCommand):
    help = 'Seed Biosphere Inn with versioned pricing + dynamic pricing rules'

    def handle(self, *args, **options):
        from pricing.models import (
            Organization, Property, PricingMatrixVersion,
            Season, RoomType, RatePlan, Channel, RateModifier,
            SeasonModifierOverride, RoomTypeSeasonModifier,
        )
        from pricing.services.version_service import DynamicPricingService
        
        with transaction.atomic():
            # Organization
            org, _ = Organization.objects.get_or_create(
                code='biosphere',
                defaults={'name': 'Biosphere Hotels', 'currency_symbol': '$'}
            )
            
            # Property
            prop, _ = Property.objects.get_or_create(
                organization=org, code='thundi',
                defaults={
                    'name': 'Biosphere Inn - Thundi',
                    'reference_base_rate': Decimal('100.00'),
                    'currency_symbol': '$',
                    'location': 'Maldives, Kaafu Atoll',
                    'total_rooms': 6,
                    'service_charge_percent': Decimal('10.00'),
                    'tax_percent': Decimal('16.00'),
                    'tax_on_service_charge': True,
                    'min_rate_warning': Decimal('50.00'),
                    'max_discount_warning': Decimal('40.00'),
                }
            )
            
            # Version 1
            version, v_created = PricingMatrixVersion.objects.get_or_create(
                hotel=prop, version_number=1,
                defaults={
                    'name': 'Initial Rates',
                    'status': 'published',
                    'created_by': 'seed',
                    'published_at': timezone.now(),
                }
            )
            
            if not v_created:
                self.stdout.write(self.style.WARNING('Version 1 already exists. Skipping seed.'))
                return
            
            # === SEASONS ===
            seasons_data = [
                ('Peak Season (Dec-Apr)', 'peak', date(2025, 12, 1), date(2026, 4, 30), Decimal('1.37'), Decimal('85.00')),
                ('Shoulder Season (May, Oct-Nov)', 'shoulder', date(2026, 5, 1), date(2026, 5, 31), Decimal('0.92'), Decimal('70.00')),
                ('Low Season (Jun-Sep)', 'low', date(2026, 6, 1), date(2026, 9, 30), Decimal('0.68'), Decimal('55.00')),
                ('Shoulder Season (Oct-Nov)', 'shoulder', date(2026, 10, 1), date(2026, 11, 30), Decimal('0.92'), Decimal('70.00')),
            ]
            
            seasons = {}
            for name, stype, start, end, idx, occ in seasons_data:
                s = Season.objects.create(
                    hotel=prop, version=version, name=name,
                    season_type=stype, start_date=start, end_date=end,
                    season_index=idx, expected_occupancy=occ,
                )
                seasons[stype] = s
                # Store with name key too for RT modifier mapping
                seasons[name] = s
            
            # === ROOM TYPES ===
            rooms_data = [
                ('Standard Garden', Decimal('100.00'), Decimal('1.00'), 3, 0, Decimal('74.00'), 'Garden view, standard amenities'),
                ('Deluxe Ocean View', Decimal('100.00'), Decimal('1.35'), 2, 1, Decimal('77.00'), 'Ocean view, balcony, premium amenities'),
                ('Honeymoon Suite', Decimal('100.00'), Decimal('1.80'), 1, 2, Decimal('80.00'), 'King bed, living area, jacuzzi'),
            ]
            
            rooms = []
            for name, base, index, count, order, target, desc in rooms_data:
                r = RoomType.objects.create(
                    hotel=prop, version=version, name=name,
                    base_rate=base, room_index=index, pricing_method='index',
                    sort_order=order, number_of_rooms=count,
                    target_occupancy=target, description=desc,
                )
                rooms.append(r)
            
            # === RATE PLANS ===
            bb = RatePlan.objects.create(
                hotel=prop, version=version, name='Bed & Breakfast',
                meal_supplement=Decimal('12.00'), sort_order=0
            )
            RatePlan.objects.create(
                hotel=prop, version=version, name='Room Only',
                meal_supplement=Decimal('0.00'), sort_order=1
            )
            RatePlan.objects.create(
                hotel=prop, version=version, name='Half Board',
                meal_supplement=Decimal('25.00'), sort_order=2
            )
            
            # === CHANNELS ===
            ota = Channel.objects.create(
                hotel=prop, version=version, name='OTA (Booking.com)',
                base_discount_percent=Decimal('0.00'), commission_percent=Decimal('15.00'),
                distribution_share_percent=Decimal('60.00'), sort_order=0,
            )
            agent = Channel.objects.create(
                hotel=prop, version=version, name='Travel Agent',
                base_discount_percent=Decimal('22.00'), commission_percent=Decimal('10.00'),
                distribution_share_percent=Decimal('15.00'), sort_order=1,
            )
            direct = Channel.objects.create(
                hotel=prop, version=version, name='Direct',
                base_discount_percent=Decimal('24.00'), commission_percent=Decimal('0.00'),
                distribution_share_percent=Decimal('25.00'), sort_order=2,
            )
            
            # === RATE MODIFIERS ===
            # OTA modifiers
            genius1 = RateModifier.objects.create(
                channel=ota, version=version, name='Genius Level 1',
                discount_percent=Decimal('10.00'), modifier_type='member', sort_order=0
            )
            genius2m = RateModifier.objects.create(
                channel=ota, version=version, name='Genius L2 + Mobile',
                discount_percent=Decimal('22.00'), modifier_type='member', sort_order=1
            )
            
            # Agent modifiers  
            RateModifier.objects.create(
                channel=agent, version=version, name='Standard Net',
                discount_percent=Decimal('0.00'), modifier_type='standard', sort_order=0
            )
            
            # Direct modifiers
            RateModifier.objects.create(
                channel=direct, version=version, name='Website Direct',
                discount_percent=Decimal('0.00'), modifier_type='standard', sort_order=0
            )
            
            # === ROOM TYPE SEASON MODIFIERS ===
            # Modifier values by room type index and season type
            modifier_by_type = {
                0: {'peak': Decimal('1.00'), 'shoulder': Decimal('1.00'), 'low': Decimal('1.00')},
                1: {'peak': Decimal('1.35'), 'shoulder': Decimal('1.30'), 'low': Decimal('1.25')},
                2: {'peak': Decimal('1.80'), 'shoulder': Decimal('1.65'), 'low': Decimal('1.50')},
            }
            
            all_seasons = Season.objects.filter(hotel=prop, version=version)
            for room_idx, type_mods in modifier_by_type.items():
                for s in all_seasons:
                    mod_val = type_mods.get(s.season_type, Decimal('1.00'))
                    RoomTypeSeasonModifier.objects.get_or_create(
                        room_type=rooms[room_idx], season=s,
                        defaults={'modifier': mod_val}
                    )
            
            # === DYNAMIC PRICING RULES ===
            dp_service = DynamicPricingService(prop)
            dp_service.seed_default_rules(version)
            
            self.stdout.write(self.style.SUCCESS(
                f'Seeded Biosphere Inn with v1 published:\n'
                f'  Seasons: {Season.objects.filter(version=version).count()}\n'
                f'  Room Types: {RoomType.objects.filter(version=version).count()}\n'
                f'  Rate Plans: {RatePlan.objects.filter(version=version).count()}\n'
                f'  Channels: {Channel.objects.filter(version=version).count()}\n'
                f'  Rate Modifiers: {RateModifier.objects.filter(version=version).count()}\n'
                f'  RT Season Modifiers: {RoomTypeSeasonModifier.objects.filter(room_type__version=version).count()}\n'
                f'  Dynamic Pricing Rules: {len(list(prop.dynamic_pricing_rules.filter(version=version)))}'
            ))
