"""
Pricing Calculation Services
============================

Unified pricing calculation via PricingService.

Calculation Flow:
1. Base Rate × Season Index × Room Type Modifier = Seasonal Rate
2. Seasonal Rate × Dynamic Multiplier = Dynamic Rate
3. Dynamic Rate + Date Override = Adjusted Rate
4. Adjusted Rate × PropertyModifier stack = Final Room Rate
5. Final Room Rate + Meal Supplement = Subtotal
6. Subtotal + Service Charge + Tax = Final Guest Rate
7. Final Guest Rate - Commission = Net Revenue
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar
import math

class PricingService:
    """
        New pricing calculation service with stacking modifiers.
        
        Usage:
            from pricing.services import PricingServiceV2
            
            service = PricingServiceV2(hotel)
            
            # Get applicable modifiers for a booking
            context = {
                'season': season,
                'season_id': season.id,
                'room_type': room,
                'room_type_id': room.id,
                'channel': channel,
                'channel_id': channel.id,
                'nights': 7,
                'booking_date': date.today(),
                'arrival_date': date(2026, 3, 15),
            }
            
            modifiers = service.get_applicable_modifiers(context)
            result = service.calculate_rate(
                bar_rate=room.base_rate,
                modifiers=modifiers,
                meal_plan_amount=Decimal('12.00')
            )
            
            print(f"Room Rate: ${result['adjusted_room_rate']}")
            print(f"Final Rate: ${result['final_rate']}")
        """
        
    def __init__(self, hotel, version=None):
        """
        Initialize service with hotel/property and optional version.

        Args:
            hotel: Property instance
            version: PricingMatrixVersion instance (optional, filters modifiers)
        """
        self.hotel = hotel
        self.version = version
        self.service_charge_percent = getattr(hotel, 'service_charge_percent', Decimal('10.00'))
        self.tax_percent = getattr(hotel, 'tax_percent', Decimal('16.00'))
        self.tax_on_service_charge = getattr(hotel, 'tax_on_service_charge', True)
        self.min_rate_warning = getattr(hotel, 'min_rate_warning', None)
        self.max_discount_warning = getattr(hotel, 'max_discount_warning', Decimal('40.00'))

    def get_applicable_modifiers(self, context):
        """
        Get list of modifiers that apply to this booking context.
        
        Args:
            context: dict with keys:
                - season / season_id: Season object or ID
                - room_type / room_type_id: RoomType object or ID
                - channel / channel_id: Channel object or ID
                - nights: int, number of nights
                - booking_date: date, when booking was made
                - arrival_date: date, check-in date
                - guest_type: str, guest type code (e.g., 'genius_1')
                - promos: list of promo codes to apply
        
        Returns:
            list: PropertyModifier objects that pass all rules, ordered by stack_order
        """
        from pricing.models import PropertyModifier
        from django.db.models import Q

        # Get active modifiers: version-specific + global (no version)
        version_q = Q(version__isnull=True)
        if self.version:
            version_q |= Q(version=self.version)

        all_modifiers = PropertyModifier.objects.filter(
            version_q,
            hotel=self.hotel,
            is_active=True,
        ).select_related(
            'season', 'room_type', 'channel'
        ).prefetch_related(
            'rules', 'rules__channels', 'rules__room_types', 
            'rules__seasons', 'rules__other_modifiers'
        ).order_by('stack_order')
        
        applicable = []
        active_modifiers = []  # Track already-approved modifiers for rule checking
        
        for modifier in all_modifiers:
            # Step 1: Check if modifier matches the context
            if not modifier.matches_context(context):
                continue
            
            # Step 2: Check all rules pass
            passes_all_rules = True
            rule_context = context.copy()
            rule_context['active_modifiers'] = active_modifiers
            
            for rule in modifier.rules.filter(is_active=True):
                passes, message = rule.check_rule(rule_context)
                if not passes:
                    passes_all_rules = False
                    break
            
            if passes_all_rules:
                applicable.append(modifier)
                active_modifiers.append(modifier)
        
        return applicable
        

    def calculate_rate(self, bar_rate, modifiers, meal_plan_amount=Decimal('0.00'), pax=2):
        """
        Calculate final rate with stacking modifiers.
        
        Args:
            bar_rate: Decimal, room base rate (BAR)
            modifiers: list of PropertyModifier objects (ordered by stack_order)
            meal_plan_amount: Decimal, meal cost per person
            pax: int, number of guests (default 2)
        
        Returns:
            dict with full breakdown:
                - bar_rate
                - modifiers (list of details)
                - total_adjustment_percent
                - multiplier
                - adjusted_room_rate
                - meal_plan_amount
                - meal_plan_total
                - subtotal
                - service_charge_percent
                - service_charge
                - tax_percent
                - tax_amount
                - final_rate
                - warnings (list of warning messages)
        """
        # =======================================================================
        # STEP 1: Calculate additive adjustment from modifiers
        # =======================================================================
        total_adjustment = Decimal('0.00')
        modifier_details = []
        
        for mod in modifiers:
            adjustment = mod.get_adjustment()
            total_adjustment += adjustment
            
            modifier_details.append({
                'id': mod.id,
                'name': mod.name,
                'code': mod.code,
                'type': mod.modifier_type,
                'applies_to': mod.applies_to,
                'value': mod.value,
                'value_display': mod.get_value_display(),
                'adjustment': adjustment,
                'adjustment_percent': adjustment * Decimal('100.00'),
                'adjustment_display': mod.get_adjustment_display(),
                'stack_order': mod.stack_order,
                'cumulative_adjustment': total_adjustment,
                'cumulative_percent': total_adjustment * Decimal('100.00'),
            })
        
        # =======================================================================
        # STEP 2: Apply total adjustment to BAR
        # =======================================================================
        multiplier = Decimal('1.00') + total_adjustment
        
        # Ensure multiplier doesn't go negative
        if multiplier < Decimal('0.00'):
            multiplier = Decimal('0.00')
        
        adjusted_room_rate = (bar_rate * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # =======================================================================
        # STEP 3: Add meal plan
        # =======================================================================
        meal_plan_total = (meal_plan_amount * pax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal = adjusted_room_rate + meal_plan_total
        
        # =======================================================================
        # STEP 4: Add service charge
        # =======================================================================
        service_charge = (subtotal * self.service_charge_percent / Decimal('100.00')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        after_service = subtotal + service_charge
        
        # =======================================================================
        # STEP 5: Add tax
        # =======================================================================
        if self.tax_on_service_charge:
            tax_base = after_service
        else:
            tax_base = subtotal
        
        tax_amount = (tax_base * self.tax_percent / Decimal('100.00')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        final_rate = after_service + tax_amount
        
        # =======================================================================
        # STEP 6: Check for warnings
        # =======================================================================
        warnings = []
        
        # Calculate total discount percentage (only if adjustment is negative)
        total_discount_percent = Decimal('0.00')
        if total_adjustment < Decimal('0.00'):
            total_discount_percent = abs(total_adjustment) * Decimal('100.00')
        
        # Check min rate warning
        if self.min_rate_warning and adjusted_room_rate < self.min_rate_warning:
            warnings.append({
                'type': 'min_rate',
                'message': f"Room rate ${adjusted_room_rate} is below minimum ${self.min_rate_warning}",
                'severity': 'warning',
            })
        
        # Check max discount warning
        if self.max_discount_warning and total_discount_percent > self.max_discount_warning:
            warnings.append({
                'type': 'max_discount',
                'message': f"Total discount {total_discount_percent:.1f}% exceeds maximum {self.max_discount_warning}%",
                'severity': 'warning',
            })
        
        # Check if rate went to zero or negative
        if adjusted_room_rate <= Decimal('0.00'):
            warnings.append({
                'type': 'zero_rate',
                'message': "Room rate is zero or negative due to excessive discounts",
                'severity': 'error',
            })

        # Check against market position floor/ceiling
        try:
            from pricing.models.competitive import MarketPosition
            mp = MarketPosition.objects.filter(hotel=self.hotel).first()
            if mp:
                if mp.bb_floor and adjusted_room_rate < mp.bb_floor:
                    warnings.append({
                        'type': 'below_floor',
                        'message': f"Rate ${adjusted_room_rate} is below market floor ${mp.bb_floor}",
                        'severity': 'error',
                    })
                if mp.bb_ceiling and adjusted_room_rate > mp.bb_ceiling:
                    warnings.append({
                        'type': 'above_ceiling',
                        'message': f"Rate ${adjusted_room_rate} exceeds market ceiling ${mp.bb_ceiling}",
                        'severity': 'warning',
                    })
        except Exception:
            pass
        
        return {
            # Input
            'bar_rate': bar_rate,
            'pax': pax,
            
            # Modifiers breakdown
            'modifiers': modifier_details,
            'modifier_count': len(modifier_details),
            'total_adjustment': total_adjustment,
            'total_adjustment_percent': total_adjustment * Decimal('100.00'),
            'total_discount_percent': total_discount_percent,
            'multiplier': multiplier,
            
            # Room rate
            'adjusted_room_rate': adjusted_room_rate,
            
            # Meal plan
            'meal_plan_per_person': meal_plan_amount,
            'meal_plan_total': meal_plan_total,
            
            # Subtotal
            'subtotal': subtotal,
            
            # Service charge
            'service_charge_percent': self.service_charge_percent,
            'service_charge': service_charge,
            'after_service': after_service,
            
            # Tax
            'tax_percent': self.tax_percent,
            'tax_on_service_charge': self.tax_on_service_charge,
            'tax_base': tax_base,
            'tax_amount': tax_amount,
            
            # Final
            'final_rate': final_rate,
            
            # Warnings
            'warnings': warnings,
            'has_warnings': len(warnings) > 0,
        }

    def get_matrix_data(self, room_type=None, rate_plan=None):
        """
        Get data for pricing matrix display.
        
        Returns rates for all season × channel combinations.
        
        Args:
            room_type: Optional RoomType to filter (or all)
            rate_plan: Optional RatePlan for meal supplement
        
        Returns:
            dict with matrix data
        """
        from pricing.models import Season, RoomType, Channel, RatePlan
        
        # Get all entities
        seasons = Season.objects.filter(hotel=self.hotel).order_by('start_date')
        channels = Channel.objects.filter(hotel=self.hotel).order_by('sort_order')
        
        if room_type:
            room_types = [room_type]
        else:
            room_types = RoomType.objects.filter(hotel=self.hotel).order_by('sort_order')
        
        if rate_plan:
            meal_amount = rate_plan.meal_supplement
        else:
            meal_amount = Decimal('0.00')
        
        # Build matrix
        matrix = {}
        
        for room in room_types:
            matrix[room.id] = {
                'room': room,
                'bar_rate': room.get_effective_base_rate(),
                'seasons': {}
            }
            
            for season in seasons:
                matrix[room.id]['seasons'][season.id] = {
                    'season': season,
                    'channels': {}
                }
                
                for channel in channels:
                    # Build context
                    context = {
                        'season': season,
                        'season_id': season.id,
                        'room_type': room,
                        'room_type_id': room.id,
                        'channel': channel,
                        'channel_id': channel.id,
                    }
                    
                    # Get applicable modifiers
                    modifiers = self.get_applicable_modifiers(context)
                    
                    # Calculate rate
                    result = self.calculate_rate(
                        bar_rate=room.get_effective_base_rate(),
                        modifiers=modifiers,
                        meal_plan_amount=meal_amount,
                    )
                    
                    matrix[room.id]['seasons'][season.id]['channels'][channel.id] = {
                        'channel': channel,
                        'result': result,
                        'room_rate': result['adjusted_room_rate'],
                        'final_rate': result['final_rate'],
                        'modifiers': result['modifiers'],
                        'warnings': result['warnings'],
                    }
        
        return {
            'room_types': room_types,
            'seasons': seasons,
            'channels': channels,
            'matrix': matrix,
            'service_charge_percent': self.service_charge_percent,
            'tax_percent': self.tax_percent,
        }


    def get_rate_card(self, target_date, pax=2):
        """
        Get complete rate card for a specific date.

        Calculation Flow (unified):
        1. Base Rate × Room Index = Room Base Rate
        2. Room Base Rate × Season Index = Seasonal Rate
        3. Seasonal Rate × Dynamic Multiplier = Dynamic Rate
        4. Dynamic Rate + Date Override = Adjusted Rate
        5. Adjusted Rate × PropertyModifier stack = Final Room Rate
        6. Final Room Rate + Meal Supplement = Subtotal
        7. Subtotal + Service Charge + Tax = Final Guest Rate

        Args:
            target_date: date to calculate rates for
            pax: number of guests (default 2)

        Returns:
            dict with:
                - target_date
                - season: {name, type, index, start_date, end_date}
                - occupancy: {booked, total, pct}
                - dynamic_pricing: {multiplier, occupancy_mult, event_mult, event_name, ...}
                - room_types: [{name, base_rate, channels: [{name, rate_plans: [{name, rate}]}]}]
                - service_charge_percent, tax_percent
        """
        from pricing.models import (
            Season, RoomType, RatePlan, Channel, PricingMatrixVersion, Reservation
        )
        from pricing.models.pricing import apply_override_to_bar
        from pricing.services.version_service import DynamicPricingService

        version = PricingMatrixVersion.get_published(self.hotel)
        version_filter = {'hotel': self.hotel}
        if version:
            version_filter['version'] = version

        seasons = Season.objects.filter(**version_filter)
        room_types = RoomType.objects.filter(**version_filter).order_by('sort_order')
        rate_plans = RatePlan.objects.filter(**version_filter).order_by('sort_order')
        channels = Channel.objects.filter(**version_filter).order_by('sort_order')

        # Find season for this date
        season = seasons.filter(
            start_date__lte=target_date, end_date__gte=target_date
        ).first()

        season_info = None
        if season:
            season_info = {
                'name': season.name,
                'type': season.season_type,
                'index': float(season.season_index),
                'start_date': season.start_date.isoformat(),
                'end_date': season.end_date.isoformat(),
                'date_range_display': season.date_range_display(),
            }

        # Occupancy
        total_rooms = self.hotel.get_total_rooms() if self.hotel else (sum(rt.number_of_rooms for rt in room_types) or 0)
        booked = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__lte=target_date,
            departure_date__gt=target_date,
            status__in=Reservation.FUTURE_STATUSES
        ).count() if total_rooms > 0 else 0
        occ_pct = round(booked / total_rooms * 100, 1) if total_rooms > 0 else 0

        # Dynamic pricing multiplier
        dp_info = {'combined_multiplier': 1.0, 'occupancy_multiplier': 1.0,
                   'event_multiplier': 1.0, 'event_name': None}
        try:
            dp_svc = DynamicPricingService(self.hotel)
            dp_result = dp_svc.get_multiplier(target_date, version)
            dp_info = {
                'combined_multiplier': float(dp_result.get('combined_multiplier', 1)),
                'occupancy_multiplier': float(dp_result.get('occupancy_multiplier', 1)),
                'event_multiplier': float(dp_result.get('event_multiplier', 1)),
                'event_name': dp_result.get('event_name'),
                'band_label': dp_result.get('band_label', ''),
                'window_label': dp_result.get('window_label', ''),
                'days_out': dp_result.get('days_out', 0),
            }
        except Exception:
            pass

        dp_multiplier = Decimal(str(dp_info['combined_multiplier']))

        # Build rate card
        rate_card = []

        for room in room_types:
            room_base = room.get_effective_base_rate()

            # Apply season index + room type season modifier
            if season:
                effective_season_index = room.get_effective_season_index(season)
                seasonal_rate = (room_base * effective_season_index).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                effective_season_index = Decimal('1.00')
                seasonal_rate = room_base

            # Apply dynamic pricing multiplier
            dp_rate = (seasonal_rate * dp_multiplier).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)

            # Apply date override on top of dynamic-adjusted rate
            adjusted_dp_rate, override, has_override = apply_override_to_bar(
                self.hotel, target_date, dp_rate)

            room_channels = []
            for channel in channels:
                channel_rate_plans = []

                for rp in rate_plans:
                    # Build context for modifier lookup
                    context = {
                        'season': season,
                        'season_id': season.id if season else None,
                        'room_type': room,
                        'room_type_id': room.id,
                        'channel': channel,
                        'channel_id': channel.id,
                    }

                    modifiers = self.get_applicable_modifiers(context)

                    result = self.calculate_rate(
                        bar_rate=adjusted_dp_rate,
                        modifiers=modifiers,
                        meal_plan_amount=rp.meal_supplement,
                        pax=pax,
                    )

                    channel_rate_plans.append({
                        'rate_plan_id': rp.id,
                        'rate_plan_name': rp.name,
                        'meal_supplement': float(rp.meal_supplement),
                        'room_rate': float(result['adjusted_room_rate']),
                        'meal_total': float(result['meal_plan_total']),
                        'subtotal': float(result['subtotal']),
                        'service_charge': float(result['service_charge']),
                        'tax': float(result['tax_amount']),
                        'final_rate': float(result['final_rate']),
                        'warnings': result['warnings'],
                    })

                room_channels.append({
                    'channel_id': channel.id,
                    'channel_name': channel.name,
                    'rate_plans': channel_rate_plans,
                })

            rate_card.append({
                'room_type_id': room.id,
                'room_type_name': room.name,
                'number_of_rooms': room.number_of_rooms,
                'base_rate': float(room_base),
                'seasonal_rate': float(seasonal_rate),
                'dp_rate': float(dp_rate),
                'override_rate': float(adjusted_dp_rate) if has_override else None,
                'has_override': has_override,
                'season_index': float(effective_season_index),
                'channels': room_channels,
            })

        return {
            'target_date': target_date.isoformat(),
            'season': season_info,
            'occupancy': {
                'booked': booked,
                'total': total_rooms,
                'pct': occ_pct,
            },
            'dynamic_pricing': dp_info,
            'room_types': rate_card,
            'channels': [{'id': c.id, 'name': c.name} for c in channels],
            'rate_plans': [{'id': rp.id, 'name': rp.name, 'meal_supplement': float(rp.meal_supplement)} for rp in rate_plans],
            'service_charge_percent': float(self.service_charge_percent),
            'tax_percent': float(self.tax_percent),
            'currency': self.hotel.currency_symbol,
        }

    # =============================================================================
    # HELPER FUNCTIONS
    # =============================================================================

    def format_rate_breakdown(result, currency='$'):
        """
        Format calculation result as readable text.
        
        Args:
            result: dict from calculate_rate
            currency: Currency symbol
        
        Returns:
            str: Formatted breakdown
        """
        lines = [
            f"BAR (Room Rate):           {currency}{result['bar_rate']:>10.2f}",
            "",
            "Modifiers Applied:",
        ]
        
        for mod in result.get('modifiers', []):
            adj_str = f"{mod['adjustment_percent']:+.1f}%"
            cum_str = f"({mod.get('cumulative', mod['adjustment_percent']):+.1f}%)"
            lines.append(f"  {mod['name']:<20} {adj_str:>8} {cum_str:>10}")
        
        lines.extend([
            "",
            f"Total Adjustment:          {result['total_adjustment_percent']:+.1f}%",
            f"Multiplier:                ×{result['multiplier']:.2f}",
            f"─" * 45,
            f"Adjusted Room Rate:        {currency}{result['adjusted_room_rate']:>10.2f}",
            f"+ Meal Plan:               {currency}{result.get('meal_plan_total', 0):>10.2f}",
            f"─" * 45,
            f"Subtotal:                  {currency}{result['subtotal']:>10.2f}",
            f"+ Service Charge ({result.get('service_charge_percent', 10)}%):  {currency}{result['service_charge']:>10.2f}",
            f"+ Tax ({result.get('tax_percent', 16)}%):              {currency}{result['tax_amount']:>10.2f}",
            f"═" * 45,
            f"FINAL RATE:                {currency}{result['final_rate']:>10.2f}",
        ])
        
        if result.get('warnings'):
            lines.extend(["", "⚠ WARNINGS:"])
            for w in result['warnings']:
                lines.append(f"  • {w['message']}")
        
        return "\n".join(lines)


"""
Revenue Forecast Service

Calculates projected revenue based on:
- Room inventory (number_of_rooms per RoomType)
- Expected occupancy per season
- Channel distribution mix (from Channel.distribution_share_percent)
- Pricing setup (rates, modifiers, discounts, commissions)
"""



