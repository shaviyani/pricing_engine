"""
Management command to migrate RateModifier + SeasonModifierOverride data
into PropertyModifier records (System B).

Run: python manage.py migrate_rate_modifiers
     python manage.py migrate_rate_modifiers --dry-run
     python manage.py migrate_rate_modifiers --verify
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Migrate RateModifier/SeasonModifierOverride records to PropertyModifier system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without saving',
        )
        parser.add_argument(
            '--verify',
            action='store_true',
            help='Verify existing PropertyModifier records match RateModifier data',
        )
        parser.add_argument(
            '--property-id',
            type=int,
            help='Migrate only for a specific property ID',
        )

    def handle(self, *args, **options):
        from pricing.models import (
            Property, PricingMatrixVersion, Channel,
            RateModifier, SeasonModifierOverride,
        )
        from pricing.models.core import PropertyModifier, ModifierRule

        dry_run = options['dry_run']
        verify = options['verify']
        prop_filter = {}
        if options['property_id']:
            prop_filter['id'] = options['property_id']

        properties = Property.objects.filter(**prop_filter)

        if verify:
            self._verify(properties)
            return

        created_count = 0
        skipped_count = 0

        for prop in properties:
            self.stdout.write(f'\n=== {prop.name} (id={prop.id}) ===')

            version = PricingMatrixVersion.get_published(prop)
            if not version:
                self.stdout.write(self.style.WARNING(f'  No published version, skipping'))
                continue

            channels = Channel.objects.filter(hotel=prop)
            if not channels.exists():
                self.stdout.write(self.style.WARNING(f'  No channels, skipping'))
                continue

            for channel in channels:
                self.stdout.write(f'\n  Channel: {channel.name} (id={channel.id})')
                self.stdout.write(
                    f'    base_discount={channel.base_discount_percent}%, '
                    f'commission={channel.commission_percent}%'
                )

                # 1. Create base channel discount modifier
                base_code = f'ch-{channel.id}-base'
                if channel.base_discount_percent > 0:
                    exists = PropertyModifier.objects.filter(
                        hotel=prop, version=version, code=base_code
                    ).exists()

                    if exists:
                        self.stdout.write(f'    [SKIP] Base modifier already exists: {base_code}')
                        skipped_count += 1
                    else:
                        self.stdout.write(
                            f'    [CREATE] {channel.name} Base Rate: '
                            f'discount {channel.base_discount_percent}%'
                        )
                        if not dry_run:
                            PropertyModifier.objects.create(
                                hotel=prop,
                                version=version,
                                name=f'{channel.name} Base Rate',
                                code=base_code,
                                description='Migrated from Channel.base_discount_percent',
                                modifier_type='discount',
                                applies_to='channel',
                                value=channel.base_discount_percent,
                                stack_order=100,
                                is_active=True,
                                channel=channel,
                            )
                        created_count += 1
                else:
                    self.stdout.write(f'    [SKIP] No base discount for {channel.name}')

                # 2. Create modifier for each RateModifier
                rate_modifiers = RateModifier.objects.filter(
                    channel=channel, active=True
                ).order_by('sort_order')

                for rm in rate_modifiers:
                    rm_code = f'ch-{channel.id}-rm-{rm.id}'

                    # Check for season-specific customizations
                    overrides = SeasonModifierOverride.objects.filter(
                        modifier=rm, is_customized=True
                    )
                    has_custom_seasons = overrides.exists()

                    if rm.discount_percent == 0 and not has_custom_seasons:
                        self.stdout.write(
                            f'    [SKIP] {rm.name}: 0% discount, no custom seasons'
                        )
                        skipped_count += 1
                        continue

                    exists = PropertyModifier.objects.filter(
                        hotel=prop, version=version, code=rm_code
                    ).exists()

                    if exists:
                        self.stdout.write(f'    [SKIP] Modifier already exists: {rm_code}')
                        skipped_count += 1
                        continue

                    # Calculate equivalent additive discount
                    # compound: (1 - ch_disc) x (1 - mod_disc)
                    # additive: (1 - equiv_disc)
                    # equiv = ch + mod - ch x mod
                    ch_d = channel.base_discount_percent / Decimal('100')
                    mod_d = rm.discount_percent / Decimal('100')
                    equiv = (ch_d + mod_d - ch_d * mod_d) * Decimal('100')
                    equiv = equiv.quantize(Decimal('0.01'))

                    # If channel base modifier was already created, this modifier's
                    # value should be: equiv - base_discount
                    if channel.base_discount_percent > 0:
                        modifier_value = equiv - channel.base_discount_percent
                    else:
                        modifier_value = rm.discount_percent

                    self.stdout.write(
                        f'    [CREATE] {rm.name}: discount {modifier_value}% '
                        f'(legacy: ch={channel.base_discount_percent}% + '
                        f'mod={rm.discount_percent}% -> equiv={equiv}%)'
                    )

                    if not dry_run:
                        pm = PropertyModifier.objects.create(
                            hotel=prop,
                            version=version,
                            name=rm.name,
                            code=rm_code,
                            description=(
                                f'Migrated from RateModifier id={rm.id}. '
                                f'Legacy: {rm.modifier_type}, '
                                f'discount={rm.discount_percent}%, '
                                f'stackable={rm.stackable}'
                            ),
                            modifier_type='discount',
                            applies_to='channel',
                            value=modifier_value,
                            stack_order=200 + rm.sort_order,
                            is_active=True,
                            channel=channel,
                        )

                        # If there are season-specific customizations, create ModifierRules
                        if has_custom_seasons:
                            seasons_with_custom = [o.season for o in overrides]
                            rule = ModifierRule.objects.create(
                                modifier=pm,
                                rule_type='season_only',
                                is_active=True,
                                error_message='Custom season discount from legacy migration',
                            )
                            rule.seasons.set(seasons_with_custom)
                            self.stdout.write(
                                f'      + ModifierRule: season_only for '
                                f'{len(seasons_with_custom)} seasons'
                            )

                    created_count += 1

        action = 'Would create' if dry_run else 'Created'
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{action} {created_count} PropertyModifier records. '
                f'Skipped {skipped_count}.'
            )
        )

    def _verify(self, properties):
        """Verify PropertyModifier rates match RateModifier rates."""
        from decimal import ROUND_HALF_UP
        from pricing.models import (
            PricingMatrixVersion, Season, RoomType, RatePlan, Channel,
            RateModifier,
        )
        from decimal import ROUND_HALF_UP as RHU
        from pricing.services import PricingService

        mismatches = 0

        for prop in properties:
            self.stdout.write(f'\n=== Verifying {prop.name} ===')

            version = PricingMatrixVersion.get_published(prop)
            if not version:
                continue

            service = PricingService(prop, version)
            version_filter = {'hotel': prop, 'version': version}

            seasons = Season.objects.filter(**version_filter)
            rooms = RoomType.objects.filter(**version_filter)
            channels = Channel.objects.filter(**version_filter)
            rate_plans = RatePlan.objects.filter(**version_filter)

            for room in rooms:
                for channel in channels:
                    rate_modifiers = RateModifier.objects.filter(
                        channel=channel, active=True
                    )

                    # Get the standard (0%) modifier for legacy calculation
                    std_mod = rate_modifiers.filter(discount_percent=0).first()
                    if not std_mod:
                        std_mod = rate_modifiers.first()

                    for season in seasons:
                        for rp in rate_plans:
                            # Legacy calculation (inlined, was calculate_final_rate)
                            mod_discount = (
                                std_mod.get_discount_for_season(season)
                                if std_mod else Decimal('0')
                            )
                            rt_mod = room.get_season_modifier(season)
                            base = Decimal(str(room.get_effective_base_rate()))
                            si = Decimal(str(season.season_index))
                            eff_idx = si * Decimal(str(rt_mod))
                            seasonal = base * eff_idx
                            meal_total = Decimal(str(rp.meal_supplement)) * 2
                            bar = seasonal + meal_total
                            ch_disc = bar * (Decimal(str(channel.base_discount_percent)) / Decimal('100'))
                            ch_rate = bar - ch_disc
                            mod_disc = ch_rate * (Decimal(str(mod_discount)) / Decimal('100'))
                            legacy_rate = (ch_rate - mod_disc).quantize(Decimal('0.01'), rounding=RHU)

                            # New system calculation
                            effective_index = season.season_index * rt_mod
                            seasonal_rate = (
                                room.get_effective_base_rate() * effective_index
                            ).quantize(Decimal('0.01'))

                            context = {
                                'season': season, 'season_id': season.id,
                                'room_type': room, 'room_type_id': room.id,
                                'channel': channel, 'channel_id': channel.id,
                            }
                            modifiers = service.get_applicable_modifiers(context)
                            new_result = service.calculate_rate(
                                bar_rate=seasonal_rate,
                                modifiers=modifiers,
                                meal_plan_amount=rp.meal_supplement,
                                pax=2,
                            )

                            # Compare room rate (before service charge/tax)
                            new_rate = (
                                new_result['adjusted_room_rate']
                                + new_result['meal_plan_total']
                            )
                            diff = abs(float(legacy_rate) - float(new_rate))

                            if diff > 0.50:
                                self.stdout.write(self.style.ERROR(
                                    f'  MISMATCH: {room.name} x {season.name} '
                                    f'x {channel.name} x {rp.name}: '
                                    f'legacy=${legacy_rate} vs new=${new_rate} '
                                    f'(diff=${diff:.2f})'
                                ))
                                mismatches += 1
                            else:
                                self.stdout.write(
                                    f'  OK: {room.name} x {season.name} '
                                    f'x {channel.name}: '
                                    f'${legacy_rate} ~ ${new_rate}'
                                )

        if mismatches == 0:
            self.stdout.write(self.style.SUCCESS('\nAll rates match!'))
        else:
            self.stdout.write(self.style.ERROR(f'\n{mismatches} mismatches found!'))
