

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

