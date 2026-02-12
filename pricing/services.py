

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar


"""
Pricing Calculation Services
============================

Complete pricing calculation module with date override support.

Calculation Flow:
1. Base Rate × Season Index = Seasonal Rate
2. Seasonal Rate + (Meal Supplement × Occupancy) = Base BAR
3. Base BAR + Date Override = Adjusted BAR  ← NEW
4. Adjusted BAR - Channel Base Discount = Channel Base Rate
5. Channel Base Rate - Modifier Discount = Final Guest Rate
6. Final Guest Rate - Commission = Net Revenue
7. (Optional) Apply ceiling to round up rates
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
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
        
    def __init__(self, hotel):
        """
        Initialize service with hotel/property.
        
        Args:
            hotel: Property instance
        """
        self.hotel = hotel
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
        
        # Get all active modifiers for this hotel
        all_modifiers = PropertyModifier.objects.filter(
            hotel=self.hotel,
            is_active=True
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

    def calculate_rate_simple(self, bar_rate, season_index=Decimal('1.00'), 
                                channel_discount=Decimal('0.00'),
                                additional_discounts=None,
                                meal_plan_amount=Decimal('0.00'), pax=2):
        """
        Simplified calculation without PropertyModifier objects.
        
        Useful for quick calculations or testing.
        
        Args:
            bar_rate: Room base rate
            season_index: Season multiplier (e.g., 1.20 for +20%)
            channel_discount: Channel discount percentage (e.g., 15 for 15%)
            additional_discounts: List of additional discount percentages
            meal_plan_amount: Meal cost per person
            pax: Number of guests
        
        Returns:
            dict with breakdown
        """
        additional_discounts = additional_discounts or []
        
        # Calculate total adjustment
        total_adjustment = Decimal('0.00')
        
        # Season index (1.20 means +20%)
        total_adjustment += (season_index - Decimal('1.00'))
        
        # Channel discount (15 means -15%)
        total_adjustment -= (channel_discount / Decimal('100.00'))
        
        # Additional discounts
        for discount in additional_discounts:
            total_adjustment -= (Decimal(str(discount)) / Decimal('100.00'))
        
        # Apply to BAR
        multiplier = Decimal('1.00') + total_adjustment
        if multiplier < Decimal('0.00'):
            multiplier = Decimal('0.00')
        
        adjusted_room_rate = (bar_rate * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Meal plan
        meal_plan_total = (meal_plan_amount * pax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal = adjusted_room_rate + meal_plan_total
        
        # Service charge
        service_charge = (subtotal * self.service_charge_percent / Decimal('100.00')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        after_service = subtotal + service_charge
        
        # Tax
        if self.tax_on_service_charge:
            tax_base = after_service
        else:
            tax_base = subtotal
        
        tax_amount = (tax_base * self.tax_percent / Decimal('100.00')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        final_rate = after_service + tax_amount
        
        return {
            'bar_rate': bar_rate,
            'season_index': season_index,
            'channel_discount': channel_discount,
            'additional_discounts': additional_discounts,
            'total_adjustment_percent': total_adjustment * Decimal('100.00'),
            'multiplier': multiplier,
            'adjusted_room_rate': adjusted_room_rate,
            'meal_plan_total': meal_plan_total,
            'subtotal': subtotal,
            'service_charge': service_charge,
            'tax_amount': tax_amount,
            'final_rate': final_rate,
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
        channels = Channel.objects.all().order_by('sort_order')
        
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


    # =============================================================================
    # HELPER FUNCTIONS
    # =============================================================================

    def calculate_rate_standalone(bar_rate, modifiers_data, meal_plan_amount=Decimal('0.00'),
                        pax=2, service_charge=Decimal('10.00'), tax=Decimal('16.00'),
                        tax_on_service=True):
        """
        Standalone function for rate calculation without hotel context.
        
        Args:
            bar_rate: Room base rate (BAR)
            modifiers_data: List of dicts with 'type' and 'value' keys:
                - type: 'index', 'discount', or 'surcharge'
                - value: Decimal value (1.20 for index, 10.00 for discount/surcharge)
                - name: Optional name for display
            meal_plan_amount: Meal cost per person
            pax: Number of guests
            service_charge: Service charge percentage
            tax: Tax percentage
            tax_on_service: Whether tax applies to service charge
        
        Returns:
            dict with full breakdown
        """
        # Calculate additive adjustment
        total_adjustment = Decimal('0.00')
        modifier_details = []
        
        for mod in modifiers_data:
            mod_type = mod.get('type', 'discount')
            value = Decimal(str(mod.get('value', 0)))
            
            if mod_type == 'index':
                adjustment = value - Decimal('1.00')
            elif mod_type == 'discount':
                adjustment = -value / Decimal('100.00')
            else:  # surcharge
                adjustment = value / Decimal('100.00')
            
            total_adjustment += adjustment
            
            modifier_details.append({
                'name': mod.get('name', ''),
                'type': mod_type,
                'value': value,
                'adjustment': adjustment,
                'adjustment_percent': adjustment * Decimal('100.00'),
                'cumulative': total_adjustment * Decimal('100.00'),
            })
        
        # Apply to BAR
        multiplier = max(Decimal('0.00'), Decimal('1.00') + total_adjustment)
        adjusted_room_rate = (bar_rate * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Meal plan
        meal_total = (meal_plan_amount * pax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal = adjusted_room_rate + meal_total
        
        # Service charge
        svc = (subtotal * service_charge / Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        after_svc = subtotal + svc
        
        # Tax
        tax_base = after_svc if tax_on_service else subtotal
        tax_amt = (tax_base * tax / Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        final = after_svc + tax_amt
        
        return {
            'bar_rate': bar_rate,
            'modifiers': modifier_details,
            'total_adjustment_percent': total_adjustment * Decimal('100.00'),
            'multiplier': multiplier,
            'adjusted_room_rate': adjusted_room_rate,
            'meal_plan_total': meal_total,
            'subtotal': subtotal,
            'service_charge': svc,
            'tax_amount': tax_amt,
            'final_rate': final,
        }


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

class RevenueForecastService:
    """
    Service for calculating revenue forecasts with channel distribution.
    
    Now supports multi-property filtering via 'hotel' parameter.
    """
    
    def __init__(self, hotel=None):
        """
        Initialize forecast service.
        
        Args:
            hotel: Property instance to filter by (None for all properties)
        """
        self.hotel = hotel
    
    def _get_seasons(self):
        """Get seasons queryset, filtered by hotel if set."""
        from pricing.models import Season
        qs = Season.objects.all()
        if self.hotel:
            qs = qs.filter(hotel=self.hotel)
        return qs.order_by('start_date')
    
    def _get_room_types(self):
        """Get room types queryset, filtered by hotel if set."""
        from pricing.models import RoomType
        qs = RoomType.objects.all()
        if self.hotel:
            qs = qs.filter(hotel=self.hotel)
        return qs
    
    def _get_total_rooms(self):
        """Get total room count, filtered by hotel if set."""
        return sum(room.number_of_rooms for room in self._get_room_types())
    
    def calculate_seasonal_forecast(self):
        """
        Calculate revenue forecast by season with channel breakdown.
        
        Returns:
            list of dicts with season data
        """
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if total_rooms == 0:
            return []
        
        seasonal_data = []
        
        for season in seasons:
            season_forecast = self._calculate_season_revenue(season, total_rooms)
            seasonal_data.append(season_forecast)
        
        return seasonal_data
    
    def calculate_monthly_forecast(self, year=None):
        """
        Calculate revenue forecast by month.
        
        Args:
            year: Optional year (defaults to current calendar year if most seasons are in it)
        
        Returns:
            list of dicts with monthly data
        """
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if not seasons.exists() or total_rooms == 0:
            return []
        
        # Determine the main year based on where most season days fall
        if year is None:
            year_days = defaultdict(int)
            for season in seasons:
                current_date = season.start_date
                while current_date <= season.end_date:
                    year_days[current_date.year] += 1
                    current_date += timedelta(days=1)
            
            year = max(year_days.items(), key=lambda x: x[1])[0] if year_days else seasons.first().start_date.year
        
        monthly_data = []
        
        for month_num in range(1, 13):
            month_start = date(year, month_num, 1)
            last_day = calendar.monthrange(year, month_num)[1]
            month_end = date(year, month_num, last_day)
            
            month_forecast = self._calculate_month_revenue(
                month_start, month_end, seasons, total_rooms
            )
            
            monthly_data.append(month_forecast)
        
        return monthly_data
    
    def _calculate_season_revenue(self, season, total_rooms):
        """Calculate revenue for a specific season."""
        from pricing.models import Channel
        
        days = (season.end_date - season.start_date).days + 1
        available_room_nights = total_rooms * days
        occupancy_rate = season.expected_occupancy / Decimal('100.00')
        occupied_room_nights = int(available_room_nights * occupancy_rate)
        
        # Channels are shared (no hotel filter)
        channels = Channel.objects.all()
        channel_breakdown = []
        
        total_gross_revenue = Decimal('0.00')
        total_net_revenue = Decimal('0.00')
        total_commission = Decimal('0.00')
        total_weighted_room_nights = 0
        
        for channel in channels:
            if channel.distribution_share_percent == 0:
                continue
            
            channel_share = channel.distribution_share_percent / Decimal('100.00')
            channel_room_nights = int(occupied_room_nights * channel_share)
            
            if channel_room_nights == 0:
                continue
            
            channel_adr = self._calculate_channel_adr(channel, season)
            
            channel_gross = channel_adr * channel_room_nights
            channel_commission = channel_gross * (channel.commission_percent / Decimal('100.00'))
            channel_net = channel_gross - channel_commission
            
            channel_breakdown.append({
                'channel': channel,
                'share_percent': channel.distribution_share_percent,
                'room_nights': channel_room_nights,
                'adr': channel_adr,
                'gross_revenue': channel_gross,
                'commission_amount': channel_commission,
                'net_revenue': channel_net,
            })
            
            total_gross_revenue += channel_gross
            total_net_revenue += channel_net
            total_commission += channel_commission
            total_weighted_room_nights += channel_room_nights
        
        weighted_adr = (total_gross_revenue / total_weighted_room_nights 
                       if total_weighted_room_nights > 0 else Decimal('0.00'))
        
        return {
            'season': season,
            'days': days,
            'available_room_nights': available_room_nights,
            'occupied_room_nights': total_weighted_room_nights,
            'occupancy_percent': season.expected_occupancy,
            'weighted_adr': weighted_adr,
            'gross_revenue': total_gross_revenue,
            'commission_amount': total_commission,
            'net_revenue': total_net_revenue,
            'channel_breakdown': channel_breakdown,
        }
    
    def _calculate_channel_adr(self, channel, season):
        """Calculate weighted average ADR for a channel in a season."""
        from pricing.models import RatePlan, RateModifier
        from pricing.services import calculate_final_rate_with_modifier
        
        room_types = self._get_room_types()
        rate_plans = RatePlan.objects.all()  # Shared
        
        if not room_types.exists() or not rate_plans.exists():
            return Decimal('0.00')
        
        total_rate = Decimal('0.00')
        count = 0
        
        # Get modifiers for this channel (shared)
        modifiers = RateModifier.objects.filter(channel=channel, active=True)
        
        for room in room_types:
            for rate_plan in rate_plans:
                if modifiers.exists():
                    for modifier in modifiers:
                        season_discount = modifier.get_discount_for_season(season)
                        
                        final_rate, _ = calculate_final_rate_with_modifier(
                            room_base_rate=room.get_effective_base_rate(),
                            season_index=season.season_index,
                            meal_supplement=rate_plan.meal_supplement,
                            channel_base_discount=channel.base_discount_percent,
                            modifier_discount=season_discount,
                            commission_percent=Decimal('0.00'),
                            occupancy=2
                        )
                        total_rate += final_rate
                        count += 1
                else:
                    final_rate, _ = calculate_final_rate_with_modifier(
                        room_base_rate=room.get_effective_base_rate(),
                        season_index=season.season_index,
                        meal_supplement=rate_plan.meal_supplement,
                        channel_base_discount=channel.base_discount_percent,
                        modifier_discount=Decimal('0.00'),
                        commission_percent=Decimal('0.00'),
                        occupancy=2
                    )
                    total_rate += final_rate
                    count += 1
        
        if count > 0:
            return (total_rate / count).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def _calculate_month_revenue(self, month_start, month_end, seasons, total_rooms):
        """Calculate revenue for a specific month."""
        from pricing.models import Channel
        
        days_in_month = (month_end - month_start).days + 1
        
        month_gross = Decimal('0.00')
        month_commission = Decimal('0.00')
        month_revenue = Decimal('0.00')
        month_room_nights = 0
        channel_contributions = defaultdict(lambda: {
            'room_nights': 0,
            'gross_revenue': Decimal('0.00'),
            'commission': Decimal('0.00'),
            'net_revenue': Decimal('0.00'),
        })
        
        for season in seasons:
            overlap_start = max(month_start, season.start_date)
            overlap_end = min(month_end, season.end_date)
            
            if overlap_start <= overlap_end:
                overlap_days = (overlap_end - overlap_start).days + 1
                season_data = self._calculate_season_revenue(season, total_rooms)
                proportion = Decimal(str(overlap_days)) / Decimal(str(season_data['days']))
                
                month_gross += season_data['gross_revenue'] * proportion
                month_commission += season_data['commission_amount'] * proportion
                month_revenue += season_data['net_revenue'] * proportion
                month_room_nights += int(season_data['occupied_room_nights'] * proportion)
                
                for channel_data in season_data['channel_breakdown']:
                    channel_id = channel_data['channel'].id
                    channel_contributions[channel_id]['room_nights'] += int(
                        channel_data['room_nights'] * proportion
                    )
                    channel_contributions[channel_id]['gross_revenue'] += (
                        channel_data['gross_revenue'] * proportion
                    )
                    channel_contributions[channel_id]['commission'] += (
                        channel_data['commission_amount'] * proportion
                    )
                    channel_contributions[channel_id]['net_revenue'] += (
                        channel_data['net_revenue'] * proportion
                    )
        
        channels = Channel.objects.all()
        channel_breakdown = []
        for channel in channels:
            if channel.id in channel_contributions:
                contrib = channel_contributions[channel.id]
                channel_breakdown.append({
                    'channel': channel,
                    'room_nights': contrib['room_nights'],
                    'gross_revenue': contrib['gross_revenue'],
                    'commission_amount': contrib['commission'],
                    'net_revenue': contrib['net_revenue'],
                })
        
        available_room_nights = total_rooms * days_in_month
        occupancy_percent = (
            Decimal(str(month_room_nights)) / Decimal(str(available_room_nights)) * Decimal('100.00')
            if available_room_nights > 0 else Decimal('0.00')
        )
        
        return {
            'month': month_start.month,
            'month_name': month_start.strftime('%B'),
            'days': days_in_month,
            'available_room_nights': available_room_nights,
            'occupied_room_nights': month_room_nights,
            'occupancy_percent': occupancy_percent.quantize(Decimal('0.1')),
            'gross_revenue': month_gross.quantize(Decimal('0.01')),
            'commission_amount': month_commission.quantize(Decimal('0.01')),
            'net_revenue': month_revenue.quantize(Decimal('0.01')),
            'channel_breakdown': channel_breakdown,
        }
    
    def calculate_occupancy_forecast(self, year=None):
        """Calculate monthly occupancy forecast."""
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if not seasons.exists() or total_rooms == 0:
            return None
        
        monthly_forecast = self.calculate_monthly_forecast(year)
        
        if not monthly_forecast:
            return None
        
        monthly_data = []
        total_available_nights = 0
        total_occupied_nights = 0
        occupancy_days_80_plus = 0
        
        for month in monthly_forecast:
            monthly_data.append({
                'month': month['month'],
                'month_name': month['month_name'][:3],
                'occupancy_percent': float(month['occupancy_percent']),
                'available_room_nights': month['available_room_nights'],
                'occupied_room_nights': month['occupied_room_nights'],
                'days': month['days'],
            })
            
            total_available_nights += month['available_room_nights']
            total_occupied_nights += month['occupied_room_nights']
            
            if month['occupancy_percent'] >= Decimal('80.00'):
                occupancy_days_80_plus += month['days']
        
        annual_occupancy = (
            Decimal(str(total_occupied_nights)) / Decimal(str(total_available_nights)) * Decimal('100.00')
            if total_available_nights > 0 else Decimal('0.00')
        )
        
        peak_month = max(monthly_data, key=lambda x: x['occupancy_percent'])
        low_month = min(monthly_data, key=lambda x: x['occupancy_percent'])
        
        seasonal_data = []
        for season in seasons:
            days = (season.end_date - season.start_date).days + 1
            available_nights = total_rooms * days
            occupancy_rate = season.expected_occupancy / Decimal('100.00')
            occupied_nights = int(available_nights * occupancy_rate)
            
            seasonal_data.append({
                'season_name': season.name,
                'occupancy_percent': float(season.expected_occupancy),
                'days': days,
                'available_room_nights': available_nights,
                'occupied_room_nights': occupied_nights,
                'start_date': season.start_date.strftime('%b %d'),
                'end_date': season.end_date.strftime('%b %d'),
            })
        
        return {
            'monthly_data': monthly_data,
            'annual_metrics': {
                'annual_occupancy': float(annual_occupancy),
                'peak_month': peak_month['month_name'],
                'peak_occupancy': peak_month['occupancy_percent'],
                'low_month': low_month['month_name'],
                'low_occupancy': low_month['occupancy_percent'],
                'days_80_plus': occupancy_days_80_plus,
                'total_available_nights': total_available_nights,
                'total_occupied_nights': total_occupied_nights,
            },
            'seasonal_data': seasonal_data,
        }
    
    def validate_channel_distribution(self):
        """Validate that channel distribution shares equal 100%."""
        from pricing.models import Channel
        
        total = Channel.objects.aggregate(
            total=Sum('distribution_share_percent')
        )['total'] or Decimal('0.00')
        
        is_valid = abs(total - Decimal('100.00')) < Decimal('0.01')
        
        if is_valid:
            message = f"✓ Total distribution: {total}%"
        elif total == Decimal('0.00'):
            message = "⚠ No distribution shares set"
        elif total < Decimal('100.00'):
            message = f"⚠ Total distribution: {total}% (missing {Decimal('100.00') - total}%)"
        else:
            message = f"⚠ Total distribution: {total}% (exceeds by {total - Decimal('100.00')}%)"
        
        return is_valid, total, message
    
    
    
"""
Pickup Analysis Service - Works directly with Reservation data.

This version calculates OTB (On The Books) metrics directly from Reservation
data, eliminating the need for separate MonthlyPickupSnapshot records.

Usage:
    from pricing.services import PickupAnalysisService
    
    service = PickupAnalysisService(property=prop)
    forecast = service.get_forecast_summary(months_ahead=6)
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
import calendar


class PickupAnalysisService:
    """
    Service for pickup analysis, curve building, and forecasting.
    
    Supports multi-property filtering via the property parameter.
    Calculates OTB directly from Reservation data.
    
    Forecast Methodology:
    - 50% weight: Historical pickup curve for season type
    - 30% weight: STLY (Same Time Last Year) comparison
    - 20% weight: Recent booking velocity trend
    """
    
    def __init__(self, property=None):
        """
        Initialize service with optional property filter.
        
        Args:
            property: Optional Property instance to filter all queries.
                     If None, analyzes all properties (legacy behavior).
        """
        self.property = property
    
    # =========================================================================
    # HELPER METHODS FOR PROPERTY FILTERING
    # =========================================================================
    
    def _get_reservations_queryset(self):
        """Get Reservation queryset, filtered by property if set."""
        from pricing.models import Reservation
        qs = Reservation.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_room_types(self):
        """Get RoomType queryset, filtered by property if set."""
        from pricing.models import RoomType
        qs = RoomType.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_total_rooms(self):
        """Get total room count, filtered by property if set."""
        return sum(room.number_of_rooms for room in self._get_room_types()) or 20
    
    def _get_seasons_queryset(self):
        """Get Season queryset, filtered by property if set."""
        from pricing.models import Season
        qs = Season.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_season_for_date(self, target_date):
        """Get the season that contains the target date."""
        return self._get_seasons_queryset().filter(
            start_date__lte=target_date,
            end_date__gte=target_date
        ).first()
    
    def _get_season_type(self, target_date):
        """Determine season type for a date (peak, high, shoulder, low)."""
        season = self._get_season_for_date(target_date)
        if season:
            idx = float(season.season_index)
            if idx >= 1.3:
                return 'peak'
            elif idx >= 1.1:
                return 'high'
            elif idx >= 0.9:
                return 'shoulder'
            else:
                return 'low'
        
        # Default based on month for Maldives seasonality
        month = target_date.month
        if month in [12, 1, 2, 3, 4]:
            if month in [12, 1, 2]:
                return 'peak'
            return 'high'
        elif month in [5, 6, 7, 8, 9]:
            return 'low'
        else:
            return 'shoulder'
    
    # =========================================================================
    # OTB CALCULATION (Direct from Reservations)
    # =========================================================================
    
    def get_otb_for_month(self, target_month):
        """
        Calculate OTB (On The Books) for a specific month from Reservation data.
        
        Args:
            target_month: First day of target month (date)
        
        Returns:
            Dict with OTB metrics
        """
        from django.db.models import Sum, Count
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get confirmed reservations for this month
        reservations = self._get_reservations_queryset().filter(
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        stats = reservations.aggregate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        )
        
        otb_room_nights = stats['room_nights'] or 0
        otb_revenue = stats['revenue'] or Decimal('0.00')
        otb_reservations = stats['count'] or 0
        
        # Calculate occupancy
        total_rooms = self._get_total_rooms()
        total_available = total_rooms * last_day
        
        otb_occupancy = Decimal('0.00')
        if total_available > 0:
            otb_occupancy = (
                Decimal(str(otb_room_nights)) / Decimal(str(total_available)) * 100
            ).quantize(Decimal('0.1'))
        
        # Calculate days out
        today = date.today()
        days_out = (month_start - today).days
        if days_out < 0:
            days_out = 0
        
        return {
            'target_month': target_month,
            'month_name': target_month.strftime('%B %Y'),
            'days_out': days_out,
            'otb_room_nights': otb_room_nights,
            'otb_revenue': otb_revenue,
            'otb_reservations': otb_reservations,
            'otb_occupancy': float(otb_occupancy),
            'total_available': total_available,
            'total_rooms': total_rooms,
        }
    
    # =========================================================================
    # VELOCITY & PACE ANALYSIS
    # =========================================================================
    
    def calculate_booking_velocity(self, target_month, lookback_days=14):
        """
        Calculate booking velocity (bookings per day) for a target month.
        
        Args:
            target_month: First day of target month
            lookback_days: Number of days to look back for trend
        
        Returns:
            Dict with velocity metrics
        """
        from django.db.models import Sum, Count
        
        today = date.today()
        lookback_start = today - timedelta(days=lookback_days)
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get bookings created in lookback period for target month
        recent_bookings = self._get_reservations_queryset().filter(
            booking_date__gte=lookback_start,
            booking_date__lte=today,
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        stats = recent_bookings.aggregate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        )
        
        room_nights = stats['room_nights'] or 0
        revenue = stats['revenue'] or Decimal('0.00')
        bookings = stats['count'] or 0
        
        # Calculate daily averages
        days = lookback_days or 1
        
        return {
            'target_month': target_month,
            'lookback_days': lookback_days,
            'total_bookings': bookings,
            'total_room_nights': room_nights,
            'total_revenue': float(revenue),
            'bookings_per_day': round(bookings / days, 2),
            'room_nights_per_day': round(room_nights / days, 2),
            'revenue_per_day': float((revenue / days).quantize(Decimal('0.01'))),
        }
    
    def get_stly_otb(self, target_month):
        """
        Get STLY (Same Time Last Year) OTB for comparison.
        
        Args:
            target_month: First day of target month
        
        Returns:
            Dict with STLY OTB data
        """
        from dateutil.relativedelta import relativedelta
        
        # STLY month
        stly_month = target_month - relativedelta(years=1)
        
        # Get STLY OTB
        return self.get_otb_for_month(stly_month)
    
    # =========================================================================
    # LEAD TIME ANALYSIS
    # =========================================================================
    
    def analyze_lead_time_distribution(self, start_date=None, end_date=None):
        """
        Analyze booking lead time distribution.
        
        Args:
            start_date: Start of analysis period (default: 90 days ago)
            end_date: End of analysis period (default: today)
        
        Returns:
            Dict with lead time buckets and statistics
        """
        from django.db.models import Avg, Min, Max, Count
        
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=90)
        
        # Get bookings in period with lead time
        bookings = self._get_reservations_queryset().filter(
            booking_date__gte=start_date,
            booking_date__lte=end_date,
            status__in=['confirmed', 'checked_in', 'checked_out']
        ).exclude(
            lead_time_days__isnull=True
        )
        
        # Overall stats
        stats = bookings.aggregate(
            avg_lead_time=Avg('lead_time_days'),
            min_lead_time=Min('lead_time_days'),
            max_lead_time=Max('lead_time_days'),
            total_bookings=Count('id'),
        )
        
        # Bucket distribution
        buckets = [
            {'label': '0-7 days', 'min': 0, 'max': 7},
            {'label': '8-14 days', 'min': 8, 'max': 14},
            {'label': '15-30 days', 'min': 15, 'max': 30},
            {'label': '31-60 days', 'min': 31, 'max': 60},
            {'label': '61-90 days', 'min': 61, 'max': 90},
            {'label': '90+ days', 'min': 91, 'max': 9999},
        ]
        
        total_bookings = stats['total_bookings'] or 1
        bucket_data = []
        
        for bucket in buckets:
            count = bookings.filter(
                lead_time_days__gte=bucket['min'],
                lead_time_days__lte=bucket['max']
            ).count()
            
            percent = round(count / total_bookings * 100, 1)
            
            bucket_data.append({
                'label': bucket['label'],
                'count': count,
                'percent': percent,
            })
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'avg_lead_time': round(stats['avg_lead_time'] or 0, 1),
            'min_lead_time': stats['min_lead_time'] or 0,
            'max_lead_time': stats['max_lead_time'] or 0,
            'total_bookings': stats['total_bookings'] or 0,
            'buckets': bucket_data,
        }
    
    # =========================================================================
    # FORECAST GENERATION
    # =========================================================================
    
    def get_forecast_summary(self, months_ahead=6):
        """
        Get forecast summary for next N months.
        
        Args:
            months_ahead: Number of months to forecast
        
        Returns:
            List of dicts with forecast data for each month
        """
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        forecasts = []
        
        for i in range(months_ahead):
            target = (today + relativedelta(months=i)).replace(day=1)
            forecast_data = self.generate_forecast(target)
            
            if forecast_data:
                forecasts.append(forecast_data)
        
        return forecasts
    
    def generate_forecast(self, target_month):
        """
        Generate forecast for a specific month.
        
        Returns dict with field names matching template expectations:
        - otb_nights, forecast_nights, vs_stly, confidence, confidence_label, etc.
        """
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        
        # Get current OTB
        otb_data = self.get_otb_for_month(target_month)
        
        otb_room_nights = otb_data['otb_room_nights']
        otb_occupancy = otb_data['otb_occupancy']
        days_out = otb_data['days_out']
        total_available = otb_data['total_available']
        
        # Get season info
        season = self._get_season_for_date(target_month)
        season_type = self._get_season_type(target_month)
        
        # Season name for display
        if season:
            season_name = season.name
        else:
            season_name = season_type.capitalize()
        
        # Get pickup curve for this season
        pickup_curves = self.get_default_pickup_curves()
        curve_data = pickup_curves.get(season_type, pickup_curves['shoulder'])
        
        # Find expected pickup percent at current days_out
        expected_percent = 100.0
        for days, percent in curve_data:
            if days_out >= days:
                expected_percent = percent
                break
        
        # Calculate curve-based forecast
        if expected_percent < 100 and expected_percent > 0:
            curve_forecast = int(otb_room_nights / (expected_percent / 100))
        else:
            curve_forecast = otb_room_nights
        
        # Get STLY data
        stly_data = self.get_stly_otb(target_month)
        stly_room_nights = stly_data['otb_room_nights'] or curve_forecast
        
        # Get velocity trend
        velocity = self.calculate_booking_velocity(target_month)
        velocity_forecast = otb_room_nights
        if days_out > 0 and velocity['room_nights_per_day'] > 0:
            velocity_forecast = otb_room_nights + int(velocity['room_nights_per_day'] * days_out)
        
        # Weighted forecast: 50% curve, 30% STLY, 20% velocity
        forecast_room_nights = int(
            curve_forecast * 0.5 +
            stly_room_nights * 0.3 +
            velocity_forecast * 0.2
        )
        
        # Cap at available
        forecast_room_nights = min(forecast_room_nights, total_available)
        
        # Calculate forecast occupancy
        forecast_occupancy = 0.0
        if total_available > 0:
            forecast_occupancy = round(forecast_room_nights / total_available * 100, 1)
        
        # Calculate pace vs STLY
        pace_variance = otb_room_nights - stly_room_nights
        vs_stly = None
        if stly_room_nights > 0:
            vs_stly = round(pace_variance / stly_room_nights * 100, 1)
        
        # Get scenario occupancy from Season expected_occupancy or OccupancyForecast
        scenario_occupancy = forecast_occupancy  # Default to forecast
        if season and hasattr(season, 'expected_occupancy') and season.expected_occupancy:
            scenario_occupancy = float(season.expected_occupancy)
        else:
            # Try OccupancyForecast
            try:
                from pricing.models import OccupancyForecast
                occ_qs = OccupancyForecast.objects.filter(target_month=target_month)
                if self.property:
                    occ_qs = occ_qs.filter(hotel=self.property)
                occ_forecast = occ_qs.first()
                if occ_forecast and occ_forecast.scenario_occupancy:
                    scenario_occupancy = float(occ_forecast.scenario_occupancy)
            except:
                pass
        
        # Determine confidence level (as percentage and label)
        if days_out <= 14:
            confidence = 85
            confidence_label = 'High'
        elif days_out <= 30:
            confidence = 70
            confidence_label = 'Good'
        elif days_out <= 60:
            confidence = 50
            confidence_label = 'Medium'
        elif days_out <= 90:
            confidence = 35
            confidence_label = 'Low'
        else:
            confidence = 25
            confidence_label = 'Very Low'
        
        return {
            # Month info - 'month' for onclick handler
            'month': target_month,
            'target_month': target_month,
            'month_name': target_month.strftime('%B %Y'),
            'month_short': target_month.strftime('%b'),
            'days_out': days_out,
            
            # Season
            'season_type': season_type,
            'season_name': season_name,
            
            # OTB - FIXED: 'otb_nights' for template
            'otb_nights': otb_room_nights,
            'otb_room_nights': otb_room_nights,
            'otb_occupancy': otb_occupancy,
            'otb_revenue': float(otb_data['otb_revenue']),
            'otb_reservations': otb_data['otb_reservations'],
            'total_available': total_available,
            
            # Forecast - FIXED: 'forecast_nights' for template
            'forecast_nights': forecast_room_nights,
            'forecast_room_nights': forecast_room_nights,
            'forecast_occupancy': forecast_occupancy,
            
            # Scenario - FIXED: added scenario_occupancy
            'scenario_occupancy': scenario_occupancy,
            
            # STLY - FIXED: 'vs_stly' for template (can be None)
            'stly_room_nights': stly_room_nights,
            'vs_stly': vs_stly,
            'vs_stly_pace': vs_stly,
            'pace_variance': pace_variance,
            
            # Confidence - FIXED: number + label
            'confidence': confidence,
            'confidence_label': confidence_label,
            
            # Curve info
            'curve_percent': expected_percent,
            'curve_forecast': curve_forecast,
            
            # Velocity
            'velocity': velocity,
        }
    
    def get_default_pickup_curves(self):
        """
        Get default pickup curves by season type.
        
        Returns:
            Dict with curves for each season type.
            Each curve is a list of (days_out, cumulative_percent) tuples.
        """
        return {
            'peak': [
                (180, 15), (150, 25), (120, 40), (90, 55),
                (60, 70), (45, 80), (30, 88), (14, 95), (7, 98), (0, 100)
            ],
            'high': [
                (180, 10), (150, 18), (120, 30), (90, 45),
                (60, 60), (45, 72), (30, 82), (14, 92), (7, 97), (0, 100)
            ],
            'shoulder': [
                (180, 5), (150, 12), (120, 22), (90, 35),
                (60, 50), (45, 62), (30, 75), (14, 88), (7, 95), (0, 100)
            ],
            'low': [
                (180, 3), (150, 8), (120, 15), (90, 25),
                (60, 40), (45, 52), (30, 65), (14, 82), (7, 92), (0, 100)
            ],
        }
    
    # =========================================================================
    # CHANNEL ANALYSIS
    # =========================================================================
    
    def get_channel_breakdown(self, target_month):
        """
        Get OTB breakdown by channel for a specific month.
        
        Args:
            target_month: First day of target month
        
        Returns:
            List of dicts with channel metrics
        """
        from django.db.models import Sum, Count
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get reservations grouped by channel
        reservations = self._get_reservations_queryset().filter(
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        channel_stats = reservations.values('channel__name').annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        ).order_by('-room_nights')
        
        total_nights = sum(s['room_nights'] or 0 for s in channel_stats)
        
        result = []
        for stat in channel_stats:
            name = stat['channel__name'] or 'Unknown'
            room_nights = stat['room_nights'] or 0
            percent = round(room_nights / total_nights * 100, 1) if total_nights > 0 else 0
            
            result.append({
                'name': name,
                'room_nights': room_nights,
                'revenue': float(stat['revenue'] or 0),
                'bookings': stat['count'] or 0,
                'percent': percent,
            })
        
        return result
    
"""
Reservation Import Service - Updated for multiple PMS formats and Multi-Property Support.

Supports:
- ABS PMS (Reservation Activity Report, Arrival List)
- Thundi/Biosphere PMS (BookingList export)
- Generic CSV/Excel formats
- Multi-property imports (hotel parameter)
"""

import re
import hashlib
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Tuple, Any

from django.db import transaction
from django.utils import timezone


"""
Updated ReservationImportService - Complete Version
====================================================

Replace the existing ReservationImportService class in pricing_services.py with this.

Key fixes:
1. SynXis Activity Report header detection (skips 3 rows)
2. Type column maps to status: New/Amend -> confirmed, Cancel -> cancelled
3. Multi-room sequence tracking per (confirmation_no + arrival_date)
4. Unique lookup includes arrival_date: (hotel, confirmation_no, arrival_date, room_sequence)
5. Room type code mapping for SynXis short codes
6. Channel mapping from CompanyName/TravelAgent
7. Date parsing for SynXis format: '2025-06-06 2:30 PM'

IMPORTANT: Also update your Reservation model Meta class:
    unique_together = ['hotel', 'confirmation_no', 'arrival_date', 'room_sequence']
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
from collections import defaultdict
import pandas as pd
import hashlib
import re

from django.db import transaction
from django.utils import timezone


class ReservationImportService:
    """
    Service for importing reservation data from Excel/CSV files.
    
    Supports multiple PMS formats including:
    - ABS PMS: "Res#", "Arr", "Dept", "Revenue($)"
    - Thundi/Biosphere: "Res #", "Arrival", "Dept", "Total"
    - SynXis Activity Report: "FXRes#", "ArrivalDate/Time", "Type"
    
    Column Mapping handles various naming conventions automatically.
    """
    
    # =========================================================================
    # SYNXIS ACTIVITY REPORT ROOM TYPE MAPPING
    # =========================================================================
    SYNXIS_ROOM_TYPE_MAPPING = {
        'STS': 'Standard Room + Family Room',
        'SUB': 'Standard Room + Family Room',
        'SUS': 'Standard Room + Family Room',
        'SBC': 'Standard Room + Family Room',
        'DEF': 'Deluxe (Balcony / Veranda)',
        'GDB': 'Deluxe (Balcony / Veranda)',
        'GIS': 'Premium Deluxe Islandview with Balcony',
        'PDS': 'Premium Deluxe Seaview with Balcony',
        'PM': 'Premium Deluxe Seaview with Balcony',
    }
    
    # =========================================================================
    # CHANNEL MAPPING (CompanyName/TravelAgent -> Channel)
    # =========================================================================
    CHANNEL_MAPPING = {
        'booking.com': 'Booking.com',
        'agoda.com': 'Agoda',
        'agoda': 'Agoda',
        'expedia': 'Expedia',
        'trip.com': 'Trip.com',
        'fit - free individual traveler': 'Direct',
        'fit- free individual traveler': 'Direct',
        'web bookings dir': 'Direct',
        'house use': 'Direct',
        'complimentary': 'Direct',
        'owners package': 'Direct',
        'owners fnf package': 'Direct',
        'fam trip': 'Direct',
    }
    
    DEFAULT_COLUMN_MAPPING = {
        # =========================================================================
        # CONFIRMATION NUMBER
        # =========================================================================
        'confirmation_no': [
            # SynXis Activity Report
            'FXRes#', 'TPRes#', 'BookingSr.No',
            # Standard PMS formats
            'Res #', 'Res#', 'Res. No', 'Res No', 'Res.No',
            'Conf. No', 'Conf No', 'Confirmation', 'Confirmation No', 'ConfNo',
            'Reservation', 'Reservation No', 'Booking No', 'BookingNo',
        ],
        
        # =========================================================================
        # DATES
        # =========================================================================
        'booking_date': [
            # SynXis Activity Report
            'BookedDate',
            # Standard formats
            'Booking Date', 'Res. Date', 'Res Date', 'Booked On', 
            'Created', 'Book Date', 'Created Date',
        ],
        
        'booking_time': [
            'Booking Time', 'Time', 'Created Time',
        ],
        
        'arrival_date': [
            # SynXis Activity Report
            'ArrivalDate/Time',
            # Standard formats
            'Arrival', 'Arr', 'Check In', 'CheckIn', 'Arrival Date', 'Check-In',
        ],
        
        'departure_date': [
            # SynXis Activity Report
            'DepartureDate/Time',
            # Standard formats
            'Dept', 'Departure', 'Check Out', 'CheckOut', 'Departure Date', 'Check-Out',
        ],
        
        'cancellation_date': [
            'Cancellation Date', 'Cancelled Date', 'Cancel Date',
        ],
        
        # =========================================================================
        # NIGHTS / PAX
        # =========================================================================
        'nights': [
            # SynXis Activity Report
            'Room Nights',
            # Standard formats
            'No Of Nights', 'Nights', 'Night', 'LOS', 'Length of Stay',
            'NoOfNights', 'Number of Nights',
        ],
        
        'pax': ['Pax', 'Guests', 'Occupancy'],
        'adults': [
            # SynXis Activity Report
            'Adult',
            # Standard formats
            'Adults', 'No of Adults',
        ],
        'children': [
            # SynXis Activity Report
            'Child',
            # Standard formats
            'Children', 'Kids', 'No of Children',
        ],
        
        # =========================================================================
        # ROOM TYPE
        # =========================================================================
        'room_no': [
            # SynXis Activity Report
            'Room Type',
            # Standard formats
            'Room', 'Room No', 'Room Number', 'RoomNo', 'RoomType', 'Room Name',
        ],
        
        # =========================================================================
        # SOURCE / CHANNEL
        # =========================================================================
        'source': [
            # SynXis Activity Report
            'CompanyName/TravelAgent',
            # Standard formats
            'Source', 'Business Source', 'Channel', 'Booking Source', 'channel',
        ],
        
        'user': [
            # SynXis Activity Report
            'User Name',
            # Standard formats
            'User', 'Created By', 'Agent', 'Booked By',
        ],
        
        # =========================================================================
        # RATE PLAN
        # =========================================================================
        'rate_plan': [
            'Rate Type', 'Rate Plan', 'RatePlan', 'Meal Plan', 'Board',
            'Board Type', 'Package',
        ],
        
        # =========================================================================
        # AMOUNTS
        # =========================================================================
        'total_amount': [
            # SynXis Activity Report
            'TotalRoomRate',
            # Standard formats
            'Total', 'Grand Total', 'Total Amount',
            'Revenue($)', 'Balance Due($)', 'Revenue', 'Amount', 'Net Amount',
        ],
        
        'adr': [
            # SynXis Activity Report
            'AvgRoomRate',
            # Standard formats
            'ADR', 'Average Daily Rate', 'Daily Rate', 'Rate',
        ],
        
        'deposit': ['Deposit', 'Deposit Amount', 'Advance'],
        
        'total_charges': ['Total Charges', 'Charges', 'Extra Charges'],
        
        # =========================================================================
        # GUEST INFO
        # =========================================================================
        'guest_name': [
            # SynXis Activity Report
            'Guest Name',
            # Standard formats
            'Name', 'Guest', 'Customer', 'Customer Name',
        ],
        
        'country': [
            # SynXis Activity Report
            'Nationality',
            # Standard formats
            'Country', 'Guest Country',
        ],
        
        'city': ['City', 'Guest City'],
        'state': ['State', 'Province', 'Guest State'],
        'zip_code': ['Zip Code', 'Postal Code', 'Zip', 'Postcode'],
        'email': ['Email', 'Guest Email', 'E-mail'],
        
        # =========================================================================
        # STATUS
        # =========================================================================
        'status': [
            'Status', 'Booking Status', 'State', 'Res.Type', 'Reservation Status',
        ],
        
        # SynXis Activity Report uses 'Type' column for action type
        'reservation_type': [
            # SynXis Activity Report - CRITICAL for status mapping
            'Type',
            # Standard formats
            'Reservationn Type', 'Reservation Type', 'Res Type', 'Booking Type',
        ],
        
        # =========================================================================
        # OTHER
        # =========================================================================
        'market_code': [
            # SynXis Activity Report
            'Segment',
            # Standard formats
            'Market Code', 'Market',
        ],
        
        'payment_type': ['Payment Type', 'Payment Method', 'Payment'],
        
        'rooms_count': [
            # SynXis Activity Report
            'No Of Rooms',
            # Standard formats
            'Rooms',
        ],
        
        'hotel_name': ['Hotel Name', 'Property', 'Hotel', 'Property/Code'],
        
        'pms_confirmation': ['PMS Confirmation\nCode', 'PMS Confirmation Code'],
        'promotion': ['Promotion'],
    }
    
    # Status mapping from import values to model choices
    STATUS_MAPPING = {
        'confirmed': [
            'confirmed', 'confirm', 'active', 'booked',
            'confirm booking',
        ],
        'cancelled': [
            'cancelled', 'canceled', 'cancel', 'void',
        ],
        'checked_in': [
            'checked in', 'checkedin', 'in house', 'inhouse', 'arrived',
        ],
        'checked_out': [
            'checked out', 'checkedout', 'departed', 'completed',
        ],
        'no_show': [
            'no show', 'noshow', 'no-show',
        ],
    }
    
    def __init__(self, column_mapping: Dict = None, hotel=None):
        """
        Initialize import service.
        
        Args:
            column_mapping: Custom column mapping (optional)
            hotel: Property instance to import to (optional)
        """
        self.column_mapping = column_mapping or self.DEFAULT_COLUMN_MAPPING
        self.hotel = hotel
        self.errors = []
        self.stats = {
            'rows_total': 0,
            'rows_processed': 0,
            'rows_created': 0,
            'rows_updated': 0,
            'rows_skipped': 0,
        }
        # Track sequence numbers for multi-room bookings
        # Key: (confirmation_no, arrival_date) -> sequence counter
        self._sequence_tracker = defaultdict(int)
        # Flag to indicate SynXis Activity Report format
        self._is_synxis_activity = False
    
    def import_file(self, file_path: str, file_import=None, hotel=None) -> Dict:
        """
        Import reservations from a file.
        
        Args:
            file_path: Path to Excel or CSV file
            file_import: Optional FileImport record for tracking
            hotel: Property to import to (optional, overrides __init__ hotel)
        
        Returns:
            Dict with import results
        """
        from pricing.models import FileImport, Property
        
        file_path = Path(file_path)
        
        # Use provided hotel or fall back to instance hotel
        self.hotel = hotel or self.hotel
        
        # Create or get FileImport record
        if file_import is None:
            file_import = FileImport.objects.create(
                hotel=self.hotel,
                filename=file_path.name,
                status='processing',
                started_at=timezone.now(),
            )
        else:
            file_import.status = 'processing'
            file_import.started_at = timezone.now()
            file_import.save()
        
        try:
            # Calculate file hash for duplicate detection
            file_import.file_hash = self._calculate_file_hash(file_path)
            file_import.save()
            
            # Read the file (with SynXis header detection)
            df = self._read_file(file_path)
            
            if df is None or df.empty:
                file_import.status = 'failed'
                file_import.errors = [{'row': 0, 'message': 'File is empty or could not be read'}]
                file_import.completed_at = timezone.now()
                file_import.save()
                return self._build_result(file_import)
            
            self.stats['rows_total'] = len(df)
            file_import.rows_total = len(df)
            file_import.save()
            
            # Clean Excel-escaped values (="314" format)
            df = self._clean_excel_escapes(df)
            
            # Map columns
            df = self._map_columns(df)
            
            # Filter invalid confirmation numbers (footer rows, etc.)
            if 'confirmation_no' in df.columns:
                initial_count = len(df)
                df['_conf_str'] = df['confirmation_no'].astype(str)
                df = df[df['_conf_str'].str.match(r'^\d+$', na=False)]
                df = df.drop(columns=['_conf_str'])
                
                invalid_filtered = initial_count - len(df)
                if invalid_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {invalid_filtered} invalid/footer rows'
                    })
            
            # Filter out day-use bookings (Nights == 0)
            if 'nights' in df.columns:
                initial_count = len(df)
                df = df[df['nights'].fillna(0).astype(float).astype(int) > 0]
                day_use_filtered = initial_count - len(df)
                
                if day_use_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {day_use_filtered} day-use bookings (Nights=0)'
                    })
            
            # Update rows_total after filtering
            self.stats['rows_total'] = len(df)
            file_import.rows_total = len(df)
            file_import.save()
            
            # Process rows
            self._process_dataframe(df, file_import)
            
            # Update file import record
            file_import.rows_processed = self.stats['rows_processed']
            file_import.rows_created = self.stats['rows_created']
            file_import.rows_updated = self.stats['rows_updated']
            file_import.rows_skipped = self.stats['rows_skipped']
            file_import.errors = self.errors[:100]  # Limit stored errors
            file_import.completed_at = timezone.now()
            
            if self.errors and any(e.get('row', 0) > 0 for e in self.errors):
                file_import.status = 'completed_with_errors'
            else:
                file_import.status = 'completed'
            
            file_import.save()
            
            # Link multi-room bookings after all reservations are imported
            self._link_multi_room_bookings(file_import)
            
            return self._build_result(file_import)
            
        except Exception as e:
            file_import.status = 'failed'
            file_import.errors = [{'row': 0, 'message': str(e)}]
            file_import.completed_at = timezone.now()
            file_import.save()
            raise
    
    def _read_file(self, file_path: Path) -> Optional[pd.DataFrame]:
        """
        Read Excel or CSV file into DataFrame.
        
        Handles SynXis Activity Report format with 3 header rows.
        """
        suffix = file_path.suffix.lower()
        
        try:
            # First, check if this is a SynXis Activity Report
            skiprows = 0
            
            if suffix == '.csv':
                # Read first line to check for SynXis header
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        first_line = f.readline()
                    
                    if 'Reservation Activity Report' in first_line or first_line.startswith(',,'):
                        skiprows = 3
                        self._is_synxis_activity = True
                        self.errors.append({
                            'row': 0,
                            'message': 'Detected SynXis Activity Report format - skipped 3 header rows'
                        })
                except:
                    pass
            
            # Read the file
            if suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path, skiprows=skiprows)
            elif suffix == '.csv':
                # Try different encodings
                df = None
                for encoding in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        df = pd.read_csv(
                            file_path, 
                            encoding=encoding, 
                            index_col=False,
                            skiprows=skiprows
                        )
                        break
                    except UnicodeDecodeError:
                        continue
                
                if df is None:
                    df = pd.read_csv(
                        file_path, 
                        encoding='utf-8', 
                        errors='replace', 
                        index_col=False,
                        skiprows=skiprows
                    )
            else:
                self.errors.append({
                    'row': 0,
                    'message': f'Unsupported file format: {suffix}'
                })
                return None
            
            # Detect SynXis format by columns
            if df is not None and ('FXRes#' in df.columns or 'Type' in df.columns):
                self._is_synxis_activity = True
            
            return df
            
        except Exception as e:
            self.errors.append({
                'row': 0,
                'message': f'Error reading file: {str(e)}'
            })
            return None
    
    def _clean_excel_escapes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean Excel-escaped values like ="314" to just 314.
        
        This format is common when exporting from some PMS systems.
        """
        def clean_value(val):
            if pd.isna(val):
                return val
            val_str = str(val).strip()
            # Match pattern: ="value" or ='value'
            match = re.match(r'^[=]?["\'](.+)["\']$', val_str)
            if match:
                return match.group(1)
            return val_str
        
        # Apply to all object (string) columns
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].apply(clean_value)
        
        return df
    
    def _map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map source columns to standard column names."""
        # Create mapping from source column names to standard names
        column_map = {}
        
        # Clean column names (remove trailing spaces, etc.)
        df.columns = [col.strip() for col in df.columns]
        
        for standard_name, possible_names in self.column_mapping.items():
            for col in df.columns:
                col_lower = col.strip().lower()
                if col_lower in [name.lower() for name in possible_names]:
                    column_map[col] = standard_name
                    break
        
        # Rename columns
        df = df.rename(columns=column_map)
        
        # Log unmapped columns
        mapped_cols = set(column_map.values())
        required_cols = {'confirmation_no', 'arrival_date', 'departure_date'}
        missing_required = required_cols - mapped_cols
        
        if missing_required:
            missing_list = ', '.join(sorted(missing_required))
            self.errors.append({
                'row': 0,
                'message': 'Missing required columns: ' + missing_list
            })
        
        return df
    
    def _process_dataframe(self, df: pd.DataFrame, file_import) -> None:
        """Process each row of the DataFrame."""
        from pricing.models import Reservation, RoomType, RatePlan
        
        # Pre-fetch reference data for performance
        if self.hotel:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.filter(hotel=self.hotel)}
        else:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.all()}
        
        rate_plans = {rp.name.lower(): rp for rp in RatePlan.objects.all()}
        
        # Reset sequence tracker for this import
        self._sequence_tracker = defaultdict(int)
        
        for i, (idx, row) in enumerate(df.iterrows()):
            row_num = i + 2  # Excel row number (1-indexed + header)
            if self._is_synxis_activity:
                row_num += 3  # Account for skipped header rows
            
            try:
                self._process_row(row, row_num, file_import, room_types, rate_plans)
                self.stats['rows_processed'] += 1
            except Exception as e:
                self.errors.append({
                    'row': row_num,
                    'message': str(e)
                })
                self.stats['rows_skipped'] += 1
    
    def _process_row(self, row: pd.Series, row_num: int, file_import,
                     room_types: Dict, rate_plans: Dict) -> None:
        """Process a single row and create/update reservation."""
        from pricing.models import Reservation, BookingSource, Channel, Guest
        
        # =====================================================================
        # CONFIRMATION NUMBER
        # =====================================================================
        raw_conf = str(row.get('confirmation_no', '')).strip()
        if not raw_conf or raw_conf == 'nan':
            self.stats['rows_skipped'] += 1
            return
        
        base_conf, sequence = Reservation.parse_confirmation_no(raw_conf)
        
        # =====================================================================
        # DATES - Parse early (needed for sequence tracking)
        # =====================================================================
        booking_date = self._parse_date(row.get('booking_date'))
        arrival_date = self._parse_date(row.get('arrival_date'))
        departure_date = self._parse_date(row.get('departure_date'))
        cancellation_date = self._parse_date(row.get('cancellation_date'))
        
        if not arrival_date or not departure_date:
            self.errors.append({
                'row': row_num,
                'message': f'Invalid dates for confirmation {raw_conf}'
            })
            self.stats['rows_skipped'] += 1
            return
        
        # =====================================================================
        # MULTI-ROOM SEQUENCE TRACKING
        # =====================================================================
        # For SynXis Activity Report (and similar), generate sequence based on
        # occurrence within the same confirmation_no + arrival_date
        if self._is_synxis_activity:
            tracker_key = (base_conf, arrival_date)
            self._sequence_tracker[tracker_key] += 1
            sequence = self._sequence_tracker[tracker_key]
        
        # =====================================================================
        # NIGHTS
        # =====================================================================
        nights = self._parse_int(row.get('nights'))
        if not nights:
            nights = (departure_date - arrival_date).days
        
        # =====================================================================
        # PAX
        # =====================================================================
        adults, children = self._parse_pax(row)
        
        # =====================================================================
        # ROOM TYPE
        # =====================================================================
        room_type_raw = str(row.get('room_no', '')).strip()
        room_type, room_type_name = self._extract_room_type(room_type_raw, room_types)
        
        # =====================================================================
        # RATE PLAN
        # =====================================================================
        rate_plan_raw = str(row.get('rate_plan', '')).strip()
        rate_plan, rate_plan_name = self._map_rate_plan(rate_plan_raw, rate_plans)
        
        # =====================================================================
        # BOOKING SOURCE / CHANNEL
        # =====================================================================
        source_str = str(row.get('source', '')).strip()
        
        if not source_str or source_str == 'nan' or source_str.upper() == 'PMS':
            source_str = 'Direct'
        
        # Map to channel
        channel = self._map_channel(source_str)
        
        # Get or create booking source
        booking_source = BookingSource.find_source(
            source_str,
            str(row.get('user', ''))
        )
        
        if not booking_source:
            booking_source = BookingSource.get_or_create_unknown()
        
        # Update channel on booking source if we mapped one
        if channel and booking_source and not booking_source.channel:
            booking_source.channel = channel
            booking_source.save(update_fields=['channel'])
        
        # =====================================================================
        # GUEST
        # =====================================================================
        guest_name = str(row.get('guest_name', '')).strip()
        country = str(row.get('country', '')).strip()
        email = str(row.get('email', '')).strip()
        
        if guest_name and guest_name != 'nan':
            guest = Guest.find_or_create(
                name=guest_name,
                country=country if country not in ['nan', '-', ''] else None,
                email=email if email not in ['nan', '-', ''] else None
            )
        else:
            guest = None
        
        # =====================================================================
        # AMOUNTS
        # =====================================================================
        total_amount = self._parse_decimal(row.get('total_amount'))
        adr = self._parse_decimal(row.get('adr'))
        
        # Calculate ADR if not provided
        if adr == Decimal('0.00') and total_amount > 0 and nights > 0:
            adr = (total_amount / Decimal(str(nights))).quantize(Decimal('0.01'))
        
        # =====================================================================
        # STATUS - CRITICAL FOR SYNXIS
        # =====================================================================
        raw_status = str(row.get('status', 'confirmed')).strip()
        status = self._map_status(raw_status)
        
        # SynXis Activity Report: Type column determines actual status
        # Type='Cancel' -> cancelled, Type='New'/'Amend' -> confirmed
        res_type = str(row.get('reservation_type', '')).strip().lower()
        if res_type == 'cancel':
            status = 'cancelled'
        elif res_type in ['new', 'amend']:
            status = 'confirmed'
        
        # Cancellation date also indicates cancelled
        if cancellation_date and status == 'confirmed':
            status = 'cancelled'
        
        # =====================================================================
        # CREATE OR UPDATE RESERVATION
        # =====================================================================
        is_multi_room = sequence > 1
        raw_data = {k: str(v) for k, v in row.items() if pd.notna(v)}
        
        with transaction.atomic():
            # IMPORTANT: Lookup includes arrival_date to differentiate
            # same confirmation_no with different stay dates
            lookup = {
                'confirmation_no': base_conf,
                'arrival_date': arrival_date,
                'room_sequence': sequence,
            }
            
            if self.hotel:
                lookup['hotel'] = self.hotel
            
            defaults = {
                'original_confirmation_no': raw_conf,
                'booking_date': booking_date or arrival_date,
                'departure_date': departure_date,
                'nights': nights,
                'adults': adults,
                'children': children,
                'room_type': room_type,
                'room_type_name': room_type_name,
                'rate_plan': rate_plan,
                'rate_plan_name': rate_plan_name,
                'booking_source': booking_source,
                'channel': channel or (booking_source.channel if booking_source else None),
                'guest': guest,
                'total_amount': total_amount,
                'adr': adr,
                'status': status,
                'cancellation_date': cancellation_date,
                'is_multi_room': is_multi_room,
                'file_import': file_import,
                'raw_data': raw_data,
            }
            
            if self.hotel:
                defaults['hotel'] = self.hotel
            
            reservation, created = Reservation.objects.update_or_create(
                **lookup,
                defaults=defaults
            )
            
            if created:
                self.stats['rows_created'] += 1
            else:
                self.stats['rows_updated'] += 1
            
            # Update guest stats
            if guest:
                guest.update_stats()
    
    def _parse_pax(self, row: pd.Series) -> Tuple[int, int]:
        """
        Parse pax/adults/children from row.
        
        Handles formats:
        - "2 \\ 0" (backslash separator)
        - "2 / 0" (forward slash separator)
        - " 2 / 0" (with leading space)
        - Separate adults/children columns
        
        Returns:
            Tuple of (adults, children)
        """
        # First check for combined pax field
        pax_value = row.get('pax', '')
        
        if pd.notna(pax_value):
            pax_str = str(pax_value).strip()
            
            # Try backslash separator: "2 \ 0" or "2 \\ 0"
            if '\\' in pax_str:
                parts = pax_str.split('\\')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try forward slash separator: "2 / 0"
            if '/' in pax_str:
                parts = pax_str.split('/')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try single number (just adults)
            try:
                adults = int(float(pax_str))
                return (adults, 0)
            except (ValueError, TypeError):
                pass
        
        # Fall back to separate columns
        adults = self._parse_int(row.get('adults'), default=2)
        children = self._parse_int(row.get('children'), default=0)
        
        return (adults, children)
    
    def _extract_room_type(self, room_input: Any, room_types: Dict[str, Any]) -> Tuple[Optional[Any], str]:
        """
        Extracts room type from a 'Room' column.
        
        Handles:
        - SynXis short codes: "STS", "DEF", "PDS", etc.
        - "116 Standard" -> "Standard"
        - "Room 101 - Deluxe" -> "Deluxe"
        - "Premium Seaview" -> "Premium Seaview"
        
        Args:
            room_input: The raw value from the 'Room' column.
            room_types: Dict mapping lowercase names to RoomType objects.
            
        Returns:
            Tuple of (Matched Object or None, Extracted String Name)
        """
        # 1. Basic Cleaning
        room_str = str(room_input or '').strip()
        if not room_str or room_str.lower() == 'nan':
            return None, ''
        
        # 2. Check SynXis room type codes first
        room_upper = room_str.upper()
        if room_upper in self.SYNXIS_ROOM_TYPE_MAPPING:
            mapped_name = self.SYNXIS_ROOM_TYPE_MAPPING[room_upper]
            if mapped_name.lower() in room_types:
                return room_types[mapped_name.lower()], mapped_name
            return None, mapped_name
        
        # 3. Extract Name (Removing Room Numbers)
        # Handles "116 Standard" or "116 - Standard"
        match = re.match(r'^\d+[\s\-\:]*(.+)$', room_str)
        if match:
            room_type_name = match.group(1).strip()
        else:
            room_type_name = room_str

        room_type_lower = room_type_name.lower()
        
        # 4. Layered Matching Logic (Waterfall)
        
        # Tier 1: Exact Match
        if room_type_lower in room_types:
            return room_types[room_type_lower], room_type_name
        
        # Tier 2: Substring Matching (Known type inside input OR input inside known type)
        for rt_name, rt_obj in room_types.items():
            if rt_name in room_type_lower or room_type_lower in rt_name:
                return rt_obj, room_type_name
                
        # Tier 3: Keyword Mapping
        keywords_map = {
            'standard': ['standard', 'std'],
            'deluxe': ['deluxe', 'premium', 'dlx'],
            'suite': ['suite', 'family', 'executive'],
            'superior': ['superior', 'sup'],
            'villa': ['villa', 'bungalow'],
            'view': ['sea', 'seaview', 'ocean', 'beach', 'garden', 'pool', 'island']
        }
        
        found_groups = {
            group for group, synonyms in keywords_map.items()
            if any(syn in room_type_lower for syn in synonyms)
        }
        
        if found_groups:
            for rt_name, rt_obj in room_types.items():
                rt_name_lower = rt_name.lower()
                if any(any(syn in rt_name_lower for syn in keywords_map[group]) for group in found_groups):
                    return rt_obj, room_type_name

        # 5. Fallback: No structured match found
        return None, room_type_name
    
    def _map_channel(self, source_str: str) -> Optional[Any]:
        """Map source string to Channel object."""
        from pricing.models import Channel
        
        if not source_str or source_str == 'nan':
            return None
        
        source_lower = source_str.strip().lower()
        
        # Check mapping
        channel_name = None
        for key, name in self.CHANNEL_MAPPING.items():
            if key and key in source_lower:
                channel_name = name
                break
        
        if not channel_name:
            # Try to determine from content
            if 'booking.com' in source_lower:
                channel_name = 'Booking.com'
            elif 'agoda' in source_lower:
                channel_name = 'Agoda'
            elif 'expedia' in source_lower:
                channel_name = 'Expedia'
            elif 'trip.com' in source_lower:
                channel_name = 'Trip.com'
        
        if channel_name:
            return Channel.objects.filter(name__iexact=channel_name).first()
        
        return None
    
    def _map_rate_plan(self, rate_plan_str: str, rate_plans: Dict) -> Tuple[Optional[Any], str]:
        """
        Map rate plan string to RatePlan model.
        
        Returns:
            Tuple of (RatePlan or None, original rate plan name)
        """
        rate_plan_str = str(rate_plan_str or '').strip()
        
        if not rate_plan_str or rate_plan_str == 'nan':
            return None, ''
        
        rate_plan_lower = rate_plan_str.lower()
        
        # Exact match
        if rate_plan_lower in rate_plans:
            return rate_plans[rate_plan_lower], rate_plan_str
        
        # Common abbreviation mappings
        abbreviation_map = {
            'ro': 'room only',
            'bb': 'bed & breakfast',
            'b&b': 'bed & breakfast',
            'bed and breakfast': 'bed & breakfast',
            'hb': 'half board',
            'fb': 'full board',
            'ai': 'all inclusive',
        }
        
        expanded = abbreviation_map.get(rate_plan_lower)
        if expanded and expanded in rate_plans:
            return rate_plans[expanded], rate_plan_str
        
        # Also try the expanded form directly
        if rate_plan_lower in abbreviation_map.values():
            for rp_name, rp in rate_plans.items():
                if rate_plan_lower in rp_name or rp_name in rate_plan_lower:
                    return rp, rate_plan_str
        
        # Partial match
        for rp_name, rp in rate_plans.items():
            if rp_name in rate_plan_lower or rate_plan_lower in rp_name:
                return rp, rate_plan_str
        
        return None, rate_plan_str
    
    def _map_status(self, status_str: str) -> str:
        """Map status string to model choice."""
        status_str = str(status_str or '').strip().lower()
        
        for status_choice, variations in self.STATUS_MAPPING.items():
            if status_str in variations:
                return status_choice
        
        return 'confirmed'  # Default
    
    def _parse_date(self, value) -> Optional[date]:
        """Parse date from various formats including SynXis datetime with AM/PM."""
        if pd.isna(value):
            return None
        
        if isinstance(value, (datetime, date)):
            return value.date() if isinstance(value, datetime) else value
        
        value = str(value).strip()
        
        if not value or value == 'nan' or value == '-':
            return None
        
        # Date formats to try - ORDER MATTERS (most specific first)
        formats = [
            # SynXis Activity Report format (MUST BE FIRST)
            '%Y-%m-%d %I:%M %p',       # 2025-06-06 2:30 PM
            '%Y-%m-%d %I:%M:%S %p',    # 2025-06-06 2:30:00 PM
            
            # DateTime formats with AM/PM
            '%d-%m-%Y %I:%M:%S %p',    # 19-01-2026 11:31:00 AM
            '%d-%m-%Y %H:%M:%S',       # 19-01-2026 11:31:00
            '%d/%m/%Y %I:%M:%S %p',    # 19/01/2026 11:31:00 AM
            '%d/%m/%Y %H:%M:%S',       # 19/01/2026 11:31:00
            
            # Date-only formats
            '%Y-%m-%d',    # 2026-01-02
            '%d-%m-%Y',    # 02-01-2026
            '%d/%m/%Y',    # 02/01/2026
            '%m/%d/%Y',    # 01/02/2026
            '%Y/%m/%d',    # 2026/01/02
            '%d.%m.%Y',    # 02.01.2026
            '%d %b %Y',    # 02 Jan 2026
            '%d %B %Y',    # 02 January 2026
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.date()
            except ValueError:
                continue
        
        return None
    
    def _parse_int(self, value, default: int = 0) -> int:
        """Parse integer from value."""
        if pd.isna(value):
            return default
        
        try:
            # Handle string values that might have extra characters
            val_str = str(value).strip()
            if not val_str or val_str == 'nan' or val_str == '-':
                return default
            return int(float(val_str))
        except (ValueError, TypeError):
            return default
    
    def _parse_decimal(self, value, default: Decimal = None) -> Decimal:
        """Parse decimal from value."""
        if default is None:
            default = Decimal('0.00')
        
        if pd.isna(value):
            return default
        
        try:
            # Remove currency symbols, commas, and handle negative with prefix
            value_str = str(value).strip()
            
            if not value_str or value_str == 'nan' or value_str == '-':
                return default
            
            # Handle "-0" format
            if value_str == '-0':
                return Decimal('0.00')
            
            value_str = value_str.replace('$', '').replace(',', '').strip()
            return Decimal(value_str).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            return default
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def _link_multi_room_bookings(self, file_import) -> None:
        """
        Link multi-room bookings after import.
        
        Finds reservations with sequence > 1 and links them to sequence 1.
        """
        from pricing.models import Reservation
        
        # Find all reservations with sequence > 1 from this import
        multi_room_qs = Reservation.objects.filter(
            file_import=file_import,
            room_sequence__gt=1
        )
        
        if self.hotel:
            multi_room_qs = multi_room_qs.filter(hotel=self.hotel)
        
        for res in multi_room_qs:
            # Find the parent (sequence 1) with same confirmation AND arrival date
            parent_lookup = {
                'confirmation_no': res.confirmation_no,
                'arrival_date': res.arrival_date,
                'room_sequence': 1
            }
            if self.hotel:
                parent_lookup['hotel'] = self.hotel
            
            parent = Reservation.objects.filter(**parent_lookup).first()
            
            if parent:
                res.parent_reservation = parent
                res.is_multi_room = True
                res.save(update_fields=['parent_reservation', 'is_multi_room'])
                
                # Also mark the parent as multi-room
                if not parent.is_multi_room:
                    parent.is_multi_room = True
                    parent.save(update_fields=['is_multi_room'])
    
    def _build_result(self, file_import) -> Dict:
        """Build result dictionary from file import."""
        return {
            'success': file_import.status in ['completed', 'completed_with_errors'],
            'file_import_id': file_import.id,
            'filename': file_import.filename,
            'status': file_import.status,
            'rows_total': file_import.rows_total,
            'rows_created': file_import.rows_created,
            'rows_updated': file_import.rows_updated,
            'rows_skipped': file_import.rows_skipped,
            'success_rate': float(file_import.success_rate) if hasattr(file_import, 'success_rate') else 0,
            'errors': file_import.errors,
            'duration_seconds': file_import.duration_seconds if hasattr(file_import, 'duration_seconds') else 0,
        }
    
    def validate_file(self, file_path: str) -> Dict:
        """
        Validate a file before importing.
        
        Checks:
        - File can be read
        - Required columns exist
        - Date formats are valid
        - No duplicate confirmation numbers
        
        Returns:
            Dict with validation results
        """
        file_path = Path(file_path)
        issues = []
        warnings = []
        
        # Check file exists
        if not file_path.exists():
            return {
                'valid': False,
                'issues': [{'message': 'File not found'}],
                'warnings': [],
            }
        
        # Read file
        df = self._read_file(file_path)
        
        if df is None or df.empty:
            return {
                'valid': False,
                'issues': [{'message': 'File is empty or could not be read'}],
                'warnings': [],
            }
        
        # Clean Excel escapes
        df = self._clean_excel_escapes(df)
        
        # Map columns
        df = self._map_columns(df)
        
        # Check required columns
        required = {'confirmation_no', 'arrival_date', 'departure_date'}
        present = set(df.columns)
        missing = required - present
        
        if missing:
            issues.append({
                'message': f'Missing required columns: {missing}'
            })
        
        # Filter invalid confirmation numbers for stats
        if 'confirmation_no' in df.columns:
            df['_conf_str'] = df['confirmation_no'].astype(str)
            invalid_conf = len(df[~df['_conf_str'].str.match(r'^\d+$', na=False)])
            if invalid_conf > 0:
                warnings.append({
                    'message': f'{invalid_conf} rows with invalid confirmation numbers will be filtered'
                })
            df = df[df['_conf_str'].str.match(r'^\d+$', na=False)]
            df = df.drop(columns=['_conf_str'])
        
        # Check for day-use bookings
        if 'nights' in df.columns:
            day_use_count = len(df[df['nights'].fillna(0).astype(float).astype(int) == 0])
            if day_use_count > 0:
                warnings.append({
                    'message': f'{day_use_count} day-use bookings will be filtered out'
                })
        
        # Check for cancelled reservations (SynXis Type column)
        if 'reservation_type' in df.columns:
            type_counts = df['reservation_type'].value_counts()
            if 'Cancel' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["Cancel"]} cancelled reservations (Type=Cancel) - will be imported with status=cancelled'
                })
            if 'New' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["New"]} new reservations (Type=New) - will be imported with status=confirmed'
                })
            if 'Amend' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["Amend"]} amended reservations (Type=Amend) - will be imported with status=confirmed'
                })
        elif 'status' in df.columns:
            cancelled_count = len(df[df['status'].str.lower().str.contains('cancel', na=False)])
            if cancelled_count > 0:
                warnings.append({
                    'message': f'{cancelled_count} cancelled reservations found'
                })
        
        # Check date validity
        if 'arrival_date' in df.columns:
            invalid_dates = 0
            for val in df['arrival_date'].dropna():
                if self._parse_date(val) is None:
                    invalid_dates += 1
            
            if invalid_dates > 0:
                issues.append({
                    'message': f'{invalid_dates} rows have invalid arrival dates'
                })
        
        # Summary stats
        stats = {
            'total_rows': len(df),
            'columns_found': list(df.columns),
            'date_range': None,
            'is_synxis_activity': self._is_synxis_activity,
        }
        
        if 'arrival_date' in df.columns:
            dates = [self._parse_date(d) for d in df['arrival_date'].dropna()]
            valid_dates = [d for d in dates if d]
            if valid_dates:
                stats['date_range'] = {
                    'start': min(valid_dates).isoformat(),
                    'end': max(valid_dates).isoformat(),
                }
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'stats': stats,
        }
        

"""
Booking Analysis Service.

Calculates dashboard metrics from Reservation data:
- KPIs (Total Revenue, Room Nights, ADR, Occupancy, Reservations)
- Cancellation Metrics (Count, Rate, Lost Revenue, by Channel)
- Monthly breakdown (Revenue, Room Nights, Available, Occupancy, ADR)
- Channel mix
- Meal plan mix
- Room type performance

Usage:
    from pricing.services.booking_analysis import BookingAnalysisService
    
    # For specific property
    service = BookingAnalysisService(property=prop)
    data = service.get_dashboard_data(year=2026)
    
    # For all properties (legacy)
    service = BookingAnalysisService()
    data = service.get_dashboard_data(year=2026)
"""

from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.db.models.functions import TruncMonth
import calendar


class BookingAnalysisService:
    """
    Service for analyzing booking/reservation data.
    
    Generates metrics for the Booking Analysis Dashboard including
    cancellation analysis.
    
    Supports multi-property filtering via the property parameter.
    """
    
    def __init__(self, property=None):
        """
        Initialize the service.
        
        Args:
            property: Optional Property instance to filter reservations.
                     If None, analyzes all reservations (legacy behavior).
        """
        self.property = property
    
    def _get_base_queryset(self):
        """Get base Reservation queryset with optional property filtering."""
        from pricing.models import Reservation
        
        queryset = Reservation.objects.all()
        
        if self.property:
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def _get_room_types(self):
        """Get RoomType queryset with optional property filtering."""
        from pricing.models import RoomType
        
        queryset = RoomType.objects.all()
        
        if self.property:
            # FIX: RoomType uses 'hotel' field, not 'property'
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def get_dashboard_data(self, year=None, start_date=None, end_date=None, include_cancelled=False):
        """
        Get all dashboard data for a given period.
        
        Args:
            year: Optional year to filter by arrival date (default: current year)
            start_date: Optional start date for custom range
            end_date: Optional end date for custom range
            include_cancelled: If True, include cancelled bookings in main metrics
        
        Returns:
            Dict with all dashboard data
        """
        # Default to current year
        if year is None and start_date is None:
            year = date.today().year
        
        # Build base querysets with property filtering
        base_queryset = self._get_base_queryset()
        
        # ACTIVE bookings (exclude cancelled)
        active_queryset = base_queryset.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        # CANCELLED bookings
        cancelled_queryset = base_queryset.filter(
            status='cancelled'
        )
        
        # ALL bookings
        all_queryset = base_queryset
        
        # Apply date filters
        if start_date and end_date:
            active_queryset = active_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            cancelled_queryset = cancelled_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            all_queryset = all_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
        elif year:
            active_queryset = active_queryset.filter(arrival_date__year=year)
            cancelled_queryset = cancelled_queryset.filter(arrival_date__year=year)
            all_queryset = all_queryset.filter(arrival_date__year=year)
        
        # Get total rooms for occupancy calculation (with property filtering)
        room_types = self._get_room_types()
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 20
        
        # Calculate all metrics
        kpis = self._calculate_kpis(active_queryset, total_rooms, year)
        cancellation_metrics = self._calculate_cancellation_metrics(
            cancelled_queryset, all_queryset, year
        )
        monthly_data = self._calculate_monthly_data(active_queryset, total_rooms, year)
        monthly_cancellations = self._calculate_monthly_cancellations(cancelled_queryset, year)
        channel_mix = self._calculate_channel_mix(active_queryset)
        cancellation_by_channel = self._calculate_cancellation_by_channel(
            cancelled_queryset, all_queryset
        )
        meal_plan_mix = self._calculate_meal_plan_mix(active_queryset)
        room_type_performance = self._calculate_room_type_performance(active_queryset)
        
        return {
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'total_rooms': total_rooms,
            'kpis': kpis,
            'cancellation_metrics': cancellation_metrics,
            'monthly_data': monthly_data,
            'monthly_cancellations': monthly_cancellations,
            'channel_mix': channel_mix,
            'cancellation_by_channel': cancellation_by_channel,
            'meal_plan_mix': meal_plan_mix,
            'room_type_performance': room_type_performance,
        }
    
    def _calculate_kpis(self, queryset, total_rooms, year):
        """
        Calculate KPI card values.
        
        Returns:
            Dict with total_revenue, room_nights, avg_adr, avg_occupancy, reservations
        """
        from django.db.models import Sum, Count
        
        # Aggregate basic stats
        stats = queryset.aggregate(
            total_revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            reservation_count=Count('id'),
        )
        
        total_revenue = stats['total_revenue'] or Decimal('0.00')
        room_nights = stats['room_nights'] or 0
        reservation_count = stats['reservation_count'] or 0
        
        # Calculate ADR
        avg_adr = Decimal('0.00')
        if room_nights > 0:
            avg_adr = (total_revenue / room_nights).quantize(Decimal('0.01'))
        
        # Calculate average occupancy for the year
        if year:
            # Total available room nights for the year
            days_in_year = 366 if calendar.isleap(year) else 365
            total_available = total_rooms * days_in_year
            avg_occupancy = Decimal('0.00')
            if total_available > 0:
                avg_occupancy = (
                    Decimal(str(room_nights)) / Decimal(str(total_available)) * 100
                ).quantize(Decimal('0.1'))
        else:
            avg_occupancy = Decimal('0.0')
        
        return {
            'total_revenue': total_revenue,
            'room_nights': room_nights,
            'avg_adr': avg_adr,
            'avg_occupancy': avg_occupancy,
            'reservations': reservation_count,
        }
    
    def _calculate_cancellation_metrics(self, cancelled_queryset, all_queryset, year):
        """
        Calculate cancellation-specific metrics.
        
        Returns:
            Dict with cancellation count, rate, lost revenue, avg lead time
        """
        from django.db.models import Sum, Count, F
        
        # Count cancelled bookings
        cancelled_stats = cancelled_queryset.aggregate(
            count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        )
        
        # Total bookings (all statuses)
        total_bookings = all_queryset.count()
        
        cancelled_count = cancelled_stats['count'] or 0
        lost_revenue = cancelled_stats['lost_revenue'] or Decimal('0.00')
        lost_room_nights = cancelled_stats['lost_room_nights'] or 0
        
        # Calculate cancellation rate
        cancellation_rate = Decimal('0.0')
        if total_bookings > 0:
            cancellation_rate = (
                Decimal(str(cancelled_count)) / Decimal(str(total_bookings)) * 100
            ).quantize(Decimal('0.1'))
        
        # Calculate average cancellation lead time
        # (days between booking_date and cancellation_date)
        cancellations_with_dates = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            booking_date__isnull=False
        ).annotate(
            lead_time=F('cancellation_date') - F('booking_date')
        )
        
        avg_cancel_lead_time = 0
        if cancellations_with_dates.exists():
            # Calculate average days
            total_days = 0
            count = 0
            for res in cancellations_with_dates:
                if res.lead_time:
                    total_days += res.lead_time.days
                    count += 1
            if count > 0:
                avg_cancel_lead_time = round(total_days / count, 1)
        
        # Calculate average days before arrival when cancelled
        # (days between cancellation_date and arrival_date)
        avg_days_before_arrival = 0
        cancellations_with_arrival = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            arrival_date__isnull=False
        )
        
        if cancellations_with_arrival.exists():
            total_days = 0
            count = 0
            for res in cancellations_with_arrival:
                days_before = (res.arrival_date - res.cancellation_date).days
                if days_before >= 0:  # Only count if cancelled before arrival
                    total_days += days_before
                    count += 1
            if count > 0:
                avg_days_before_arrival = round(total_days / count, 1)
        
        return {
            'count': cancelled_count,
            'rate': cancellation_rate,
            'lost_revenue': lost_revenue,
            'lost_room_nights': lost_room_nights,
            'total_bookings': total_bookings,
            'avg_cancel_lead_time': avg_cancel_lead_time,  # Days after booking
            'avg_days_before_arrival': avg_days_before_arrival,  # Days before arrival
        }
    
    def _calculate_monthly_data(self, queryset, total_rooms, year):
        """
        Calculate monthly breakdown.
        
        Returns:
            List of dicts with month, revenue, room_nights, available, occupancy, adr
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            if year:
                # Calculate available room nights for this month
                days_in_month = calendar.monthrange(year, month_num)[1]
                available = total_rooms * days_in_month
            else:
                available = 0
            
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'month_full': calendar.month_name[month_num],
                'revenue': Decimal('0.00'),
                'room_nights': 0,
                'available': available,
                'occupancy': Decimal('0.0'),
                'adr': Decimal('0.00'),
                'bookings': 0,
            })
        
        # Aggregate by arrival month
        monthly_stats = queryset.values('arrival_date__month').annotate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            revenue = stat['revenue'] or Decimal('0.00')
            room_nights = stat['room_nights'] or 0
            available = monthly_data[month_idx]['available']
            
            monthly_data[month_idx]['revenue'] = revenue
            monthly_data[month_idx]['room_nights'] = room_nights
            monthly_data[month_idx]['bookings'] = stat['bookings']
            
            # Calculate occupancy
            if available > 0:
                monthly_data[month_idx]['occupancy'] = (
                    Decimal(str(room_nights)) / Decimal(str(available)) * 100
                ).quantize(Decimal('0.1'))
            
            # Calculate ADR
            if room_nights > 0:
                monthly_data[month_idx]['adr'] = (
                    revenue / room_nights
                ).quantize(Decimal('0.01'))
        
        return monthly_data
    
    def _calculate_monthly_cancellations(self, cancelled_queryset, year):
        """
        Calculate monthly cancellation breakdown.
        
        Returns:
            List of dicts with month, cancelled_count, lost_revenue, lost_room_nights
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'cancelled_count': 0,
                'lost_revenue': Decimal('0.00'),
                'lost_room_nights': 0,
            })
        
        # Aggregate cancellations by arrival month
        monthly_stats = cancelled_queryset.values('arrival_date__month').annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            monthly_data[month_idx]['cancelled_count'] = stat['cancelled_count'] or 0
            monthly_data[month_idx]['lost_revenue'] = stat['lost_revenue'] or Decimal('0.00')
            monthly_data[month_idx]['lost_room_nights'] = stat['lost_room_nights'] or 0
        
        return monthly_data
    
    def _calculate_channel_mix(self, queryset):
        """
        Calculate channel/source breakdown.
        
        Returns:
            List of dicts with channel, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Try to group by channel first
        channel_stats = queryset.values(
            'channel__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no channel data, try booking_source
        if not channel_stats.exists() or all(s['channel__name'] is None for s in channel_stats):
            channel_stats = queryset.values(
                'booking_source__name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'booking_source__name'
        else:
            name_field = 'channel__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in channel_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return channel_data
    
    def _calculate_cancellation_by_channel(self, cancelled_queryset, all_queryset):
        """
        Calculate cancellation rate by channel.
        
        Returns:
            List of dicts with channel, cancelled_count, total_count, rate, lost_revenue
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Get cancelled by channel
        cancelled_by_channel = cancelled_queryset.values(
            'channel__name'
        ).annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('-cancelled_count')
        
        # Get total by channel
        total_by_channel = all_queryset.values(
            'channel__name'
        ).annotate(
            total_count=Count('id'),
        )
        
        # Build lookup for totals
        total_lookup = {
            stat['channel__name']: stat['total_count'] 
            for stat in total_by_channel
        }
        
        for stat in cancelled_by_channel:
            name = stat.get('channel__name') or 'Unknown'
            cancelled_count = stat['cancelled_count'] or 0
            total_count = total_lookup.get(name, cancelled_count)
            
            # Calculate cancellation rate for this channel
            rate = Decimal('0.0')
            if total_count > 0:
                rate = (
                    Decimal(str(cancelled_count)) / Decimal(str(total_count)) * 100
                ).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'cancelled_count': cancelled_count,
                'total_count': total_count,
                'rate': rate,
                'lost_revenue': stat['lost_revenue'] or Decimal('0.00'),
                'lost_room_nights': stat['lost_room_nights'] or 0,
            })
        
        # Sort by cancellation rate (highest first)
        channel_data.sort(key=lambda x: x['rate'], reverse=True)
        
        return channel_data
    
    def _calculate_meal_plan_mix(self, queryset):
        """
        Calculate meal plan/rate plan breakdown.
        
        Returns:
            List of dicts with meal_plan, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        meal_plan_data = []
        
        # Group by rate_plan
        plan_stats = queryset.values(
            'rate_plan__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no rate_plan data, try rate_plan_name
        if not plan_stats.exists() or all(s['rate_plan__name'] is None for s in plan_stats):
            plan_stats = queryset.values(
                'rate_plan_name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'rate_plan_name'
        else:
            name_field = 'rate_plan__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in plan_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            meal_plan_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return meal_plan_data
    
    def _calculate_room_type_performance(self, queryset):
        """
        Calculate room type breakdown.
        
        Groups by room_type FK if available, otherwise by room_type_name.
        
        Returns:
            List of dicts with room_type, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        room_type_data = []
        
        # First, try to get stats for reservations WITH room_type FK
        rt_stats_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # Then, get stats for reservations WITHOUT room_type FK (use room_type_name)
        rt_stats_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        # Combine results - first from FK, then from name
        seen_names = set()
        
        for stat in rt_stats_fk:
            name = stat.get('room_type__name') or 'Unknown'
            if name in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        for stat in rt_stats_name:
            name = stat.get('room_type_name') or 'Unknown'
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        # Sort by revenue descending
        room_type_data.sort(key=lambda x: x['revenue'], reverse=True)
        
        return room_type_data
    
    def get_chart_data(self, year=None):
        """
        Get data formatted for Chart.js charts.
        
        Returns:
            Dict with chart-ready data (lists for labels, values, etc.)
            All Decimal values are converted to float for JSON serialization.
        """
        dashboard_data = self.get_dashboard_data(year=year)
        monthly = dashboard_data['monthly_data']
        monthly_cancel = dashboard_data['monthly_cancellations']
        
        # Helper to convert Decimal to float
        def to_float(val):
            if isinstance(val, Decimal):
                return float(val)
            return val
        
        # Convert KPIs to JSON-safe format
        kpis_safe = {
            'total_revenue': to_float(dashboard_data['kpis']['total_revenue']),
            'room_nights': dashboard_data['kpis']['room_nights'],
            'avg_adr': to_float(dashboard_data['kpis']['avg_adr']),
            'avg_occupancy': to_float(dashboard_data['kpis']['avg_occupancy']),
            'reservations': dashboard_data['kpis']['reservations'],
        }
        
        # Convert cancellation metrics to JSON-safe format
        cancel_metrics_safe = {
            'count': dashboard_data['cancellation_metrics']['count'],
            'rate': to_float(dashboard_data['cancellation_metrics']['rate']),
            'lost_revenue': to_float(dashboard_data['cancellation_metrics']['lost_revenue']),
            'lost_room_nights': dashboard_data['cancellation_metrics']['lost_room_nights'],
            'total_bookings': dashboard_data['cancellation_metrics']['total_bookings'],
            'avg_cancel_lead_time': dashboard_data['cancellation_metrics']['avg_cancel_lead_time'],
            'avg_days_before_arrival': dashboard_data['cancellation_metrics']['avg_days_before_arrival'],
        }
        
        return {
            # Monthly metrics
            'months': [m['month_name'] for m in monthly],
            'revenue': [float(m['revenue']) for m in monthly],
            'room_nights': [m['room_nights'] for m in monthly],
            'available': [m['available'] for m in monthly],
            'occupancy': [float(m['occupancy']) for m in monthly],
            'adr': [float(m['adr']) for m in monthly],
            'bookings': [m['bookings'] for m in monthly],
            
            # Cancellation metrics
            'cancelled_count': [m['cancelled_count'] for m in monthly_cancel],
            'lost_revenue': [float(m['lost_revenue']) for m in monthly_cancel],
            'lost_room_nights': [m['lost_room_nights'] for m in monthly_cancel],
            
            # Channel mix
            'channel_labels': [c['name'] for c in dashboard_data['channel_mix']],
            'channel_values': [float(c['revenue']) for c in dashboard_data['channel_mix']],
            'channel_percents': [float(c['percent']) for c in dashboard_data['channel_mix']],
            
            # Cancellation by channel
            'cancel_channel_labels': [c['name'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_counts': [c['cancelled_count'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_rates': [float(c['rate']) for c in dashboard_data['cancellation_by_channel']],
            
            # Meal plan mix
            'meal_plan_labels': [m['name'] for m in dashboard_data['meal_plan_mix']],
            'meal_plan_values': [float(m['revenue']) for m in dashboard_data['meal_plan_mix']],
            'meal_plan_percents': [float(m['percent']) for m in dashboard_data['meal_plan_mix']],
            
            # KPIs for display (JSON-safe)
            'kpis': kpis_safe,
            'cancellation_metrics': cancel_metrics_safe,
        }
    
    def get_net_pickup(self, start_date=None, end_date=None, days=30):
        """
        Calculate net pickup (new bookings - cancellations) for a period.
        
        Args:
            start_date: Start of period (default: days ago)
            end_date: End of period (default: today)
            days: Number of days to look back (default: 30)
        
        Returns:
            Dict with gross_bookings, cancellations, net_bookings, net_revenue
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=days)
        
        # Use property-filtered base queryset
        base_queryset = self._get_base_queryset()
        
        # New bookings created in this period
        new_bookings = base_queryset.filter(
            booking_date__gte=start_date,
            booking_date__lte=end_date
        ).exclude(status='cancelled')
        
        from django.db.models import Sum, Count
        
        new_stats = new_bookings.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        # Cancellations in this period
        cancellations = base_queryset.filter(
            cancellation_date__gte=start_date,
            cancellation_date__lte=end_date,
            status='cancelled'
        )
        
        cancel_stats = cancellations.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        gross_bookings = new_stats['count'] or 0
        gross_revenue = new_stats['revenue'] or Decimal('0.00')
        gross_room_nights = new_stats['room_nights'] or 0
        
        cancelled_count = cancel_stats['count'] or 0
        cancelled_revenue = cancel_stats['revenue'] or Decimal('0.00')
        cancelled_room_nights = cancel_stats['room_nights'] or 0
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'gross_bookings': gross_bookings,
            'gross_revenue': gross_revenue,
            'gross_room_nights': gross_room_nights,
            'cancellations': cancelled_count,
            'cancelled_revenue': cancelled_revenue,
            'cancelled_room_nights': cancelled_room_nights,
            'net_bookings': gross_bookings - cancelled_count,
            'net_revenue': gross_revenue - cancelled_revenue,
            'net_room_nights': gross_room_nights - cancelled_room_nights,
        }
        
    def get_month_detail(self, year, month):
        """
        Get detailed analysis for a specific arrival month.
        
        Args:
            year: Arrival year
            month: Arrival month (1-12)
        
        Returns:
            Dict with summary, velocity, room_distribution, lead_time, 
            channel_distribution, country_distribution
        """
        from django.db.models import Sum, Count, Avg, F
        from django.db.models.functions import TruncMonth
        
        # Base queryset for this arrival month
        base_qs = self._get_base_queryset().filter(
            arrival_date__year=year,
            arrival_date__month=month
        )
        
        # Active bookings only for summary
        active_qs = base_qs.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        # Get room types for available calculation
        room_types = self._get_room_types()
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 1
        days_in_month = calendar.monthrange(year, month)[1]
        available = total_rooms * days_in_month
        
        # ===================
        # SUMMARY
        # ===================
        summary_stats = active_qs.aggregate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id')
        )
        
        revenue = float(summary_stats['revenue'] or 0)
        room_nights = summary_stats['room_nights'] or 0
        adr = revenue / room_nights if room_nights > 0 else 0
        occupancy = (room_nights / available * 100) if available > 0 else 0
        
        summary = {
            'revenue': revenue,
            'room_nights': room_nights,
            'occupancy': occupancy,
            'adr': adr,
            'bookings': summary_stats['bookings'] or 0,
            'available': available,
        }
        
        # ===================
        # BOOKING VELOCITY
        # ===================
        velocity = self._get_velocity_for_month(base_qs, year, month)
        
        # ===================
        # ROOM DISTRIBUTION
        # ===================
        room_distribution = self._get_room_distribution_detail(active_qs)
        
        # ===================
        # LEAD TIME DISTRIBUTION
        # ===================
        lead_time = self._get_lead_time_distribution_detail(active_qs)
        
        # ===================
        # CHANNEL DISTRIBUTION
        # ===================
        channel_distribution = self._get_channel_distribution_detail(active_qs)
        
        # ===================
        # COUNTRY DISTRIBUTION
        # ===================
        country_distribution = self._get_country_distribution(active_qs)
        
        return {
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'summary': summary,
            'velocity': velocity,
            'room_distribution': room_distribution,
            'lead_time': lead_time,
            'channel_distribution': channel_distribution,
            'country_distribution': country_distribution,
        }

    def _get_velocity_for_month(self, base_qs, year, month):
        """
        Get booking velocity for a specific arrival month.
        
        IMPORTANT: This now calculates properly so cumulative matches final OTB:
        - New RN: Only counts ACTIVE bookings created in that month
        - Lost RN: Cancelled/Void/NoShow bookings created in that month
        - Net Pickup: New - Lost
        - Cumulative: Running total = Final Active OTB
        """
        from django.db.models import Sum, Count
        from django.db.models.functions import TruncMonth
        
        # Active statuses
        active_statuses = ['confirmed', 'checked_in', 'checked_out']
        # Lost statuses (cancelled, void, no_show)
        lost_statuses = ['cancelled', 'void', 'no_show']
        
        # Get ACTIVE bookings grouped by booking month
        active_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=active_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            new_bookings=Count('id'),
            new_nights=Sum('nights'),
        ).order_by('bm')
        
        # Get LOST bookings (cancelled/void/no_show) grouped by booking month
        lost_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=lost_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            lost_bookings=Count('id'),
            lost_nights=Sum('nights'),
        ).order_by('bm')
        
        # Build lookups
        active_lookup = {a['bm']: a for a in active_bookings}
        lost_lookup = {l['bm']: l for l in lost_bookings}
        
        # Get all booking months
        all_months = sorted(set(
            list(active_lookup.keys()) + list(lost_lookup.keys())
        ))
        
        # Build velocity data
        velocity = []
        for bm in all_months:
            active_data = active_lookup.get(bm, {})
            lost_data = lost_lookup.get(bm, {})
            
            new_nights = active_data.get('new_nights', 0) or 0
            lost_nights = lost_data.get('lost_nights', 0) or 0
            
            velocity.append({
                'booking_month': bm.strftime('%b %Y') if bm else 'Unknown',
                'new_bookings': active_data.get('new_bookings', 0) or 0,
                'new_nights': new_nights,
                'cancellations': lost_data.get('lost_bookings', 0) or 0,
                'cancelled_nights': lost_nights,
                'net_pickup': new_nights,  # Only active bookings count
            })
        
        return velocity

    def _get_room_distribution_detail(self, queryset):
        """Get room night distribution by room type for month detail."""
        from django.db.models import Sum, Count
        
        # Try room_type FK first
        by_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        # Then try room_type_name
        by_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        seen = set()
        
        for row in by_fk:
            name = row['room_type__name'] or 'Unknown'
            if name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        for row in by_name:
            name = row['room_type_name'] or 'Unknown'
            if name and name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_lead_time_distribution_detail(self, queryset):
        """Get lead time distribution (days between booking and arrival)."""
        from django.db.models import F
        
        # Get bookings with lead time calculated
        bookings_with_lead = queryset.filter(
            booking_date__isnull=False,
            arrival_date__isnull=False
        )
        
        # Define buckets
        buckets = [
            ('0-7 days', 0, 7),
            ('8-14 days', 8, 14),
            ('15-30 days', 15, 30),
            ('31-60 days', 31, 60),
            ('61-90 days', 61, 90),
            ('90+ days', 91, 9999),
        ]
        
        distribution = []
        
        for label, min_days, max_days in buckets:
            bucket_data = {
                'bookings': 0,
                'room_nights': 0,
                'revenue': Decimal('0.00'),
            }
            
            for booking in bookings_with_lead:
                if booking.booking_date and booking.arrival_date:
                    days = (booking.arrival_date - booking.booking_date).days
                    if min_days <= days <= max_days:
                        bucket_data['bookings'] += 1
                        bucket_data['room_nights'] += booking.nights or 0
                        bucket_data['revenue'] += booking.total_amount or Decimal('0.00')
            
            avg_adr = 0
            if bucket_data['room_nights'] > 0:
                avg_adr = float(bucket_data['revenue']) / bucket_data['room_nights']
            
            distribution.append({
                'bucket': label,
                'bookings': bucket_data['bookings'],
                'room_nights': bucket_data['room_nights'],
                'revenue': float(bucket_data['revenue']),
                'avg_adr': avg_adr,
            })
        
        return distribution

    def _get_channel_distribution_detail(self, queryset):
        """Get distribution by booking channel for month detail."""
        from django.db.models import Sum, Count
        
        # Try channel FK first
        by_channel = queryset.values(
            'channel__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        for row in by_channel:
            name = row['channel__name'] or 'Direct/Unknown'
            distribution.append({
                'channel': name,
                'room_nights': row['room_nights'] or 0,
                'revenue': float(row['revenue'] or 0),
                'bookings': row['bookings'] or 0,
            })
        
        # If no channel data, try booking_source
        if not distribution or all(d['channel'] == 'Direct/Unknown' for d in distribution):
            by_source = queryset.values(
                'booking_source__name'
            ).annotate(
                room_nights=Sum('nights'),
                revenue=Sum('total_amount'),
                bookings=Count('id')
            ).order_by('-room_nights')
            
            distribution = []
            for row in by_source:
                name = row['booking_source__name'] or 'Unknown'
                distribution.append({
                    'channel': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_country_distribution(self, queryset):
        """Get distribution by guest country."""
        from django.db.models import Sum, Count
        
        by_country = queryset.exclude(
            guest__country__isnull=True
        ).exclude(
            guest__country=''
        ).exclude(
            guest__country='-'
        ).values(
            'guest__country'
        ).annotate(
            room_nights=Sum('nights'),
            bookings=Count('id')
        ).order_by('-room_nights')[:10]  # Top 10 countries
        
        distribution = []
        for row in by_country:
            country = row['guest__country'] or 'Unknown'
            distribution.append({
                'country': country,
                'room_nights': row['room_nights'] or 0,
                'bookings': row['bookings'] or 0,
            })
        
        # If no guest country data, return placeholder
        if not distribution:
            distribution = [{'country': 'Unknown', 'room_nights': 0, 'bookings': 0}]
        
        return distribution