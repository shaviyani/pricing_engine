"""
Services package.
"""

from .pricing_service import PricingService
from .forecast_service import RevenueForecastService, PickupAnalysisService
from .analytics_service import ReservationImportService, BookingAnalysisService
from .version_service import PricingVersionService, DynamicPricingService, DynamicPricingOptimizer

from decimal import Decimal, ROUND_HALF_UP
import math


# =============================================================================
# Legacy standalone calculation functions (referenced by views)
# Updated with dynamic_multiplier support
# =============================================================================

def calculate_final_rate(room_base_rate, season_index, meal_supplement,
                         channel_base_discount, modifier_discount,
                         commission_percent, occupancy=2,
                         apply_ceiling=False, ceiling_increment=5,
                         room_type_season_modifier=Decimal('1.00'),
                         dynamic_multiplier=Decimal('1.00')):
    """
    Calculate final guest rate and hotel revenue.
    
    Calculation chain:
    1. Base Rate x Effective Index (season x RT modifier) = Seasonal Rate
    2. Seasonal Rate x Dynamic Multiplier = Dynamic Rate
    3. Dynamic Rate + Meals = BAR
    4. BAR - Channel Discount = Channel Base Rate
    5. Channel Base Rate - Modifier Discount = Final Guest Rate
    6. Final Guest Rate - Commission = Net Revenue
    
    Returns: (final_rate, breakdown_dict)
    """
    room_base_rate = Decimal(str(room_base_rate))
    season_index = Decimal(str(season_index))
    meal_supplement = Decimal(str(meal_supplement))
    channel_base_discount = Decimal(str(channel_base_discount))
    modifier_discount = Decimal(str(modifier_discount))
    commission_percent = Decimal(str(commission_percent))
    room_type_season_modifier = Decimal(str(room_type_season_modifier))
    dynamic_multiplier = Decimal(str(dynamic_multiplier))
    
    # Step 1: Effective index
    effective_index = season_index * room_type_season_modifier
    
    # Step 2: Seasonal rate
    seasonal_rate = room_base_rate * effective_index
    
    # Step 3: Dynamic multiplier (occupancy x event)
    dynamic_rate = seasonal_rate * dynamic_multiplier
    
    # Step 4: Add meals = BAR
    meal_total = meal_supplement * occupancy
    bar_rate = dynamic_rate + meal_total
    
    # Step 5: Channel discount
    channel_discount_amount = bar_rate * (channel_base_discount / Decimal('100'))
    channel_base_rate = bar_rate - channel_discount_amount
    
    # Step 6: Modifier discount
    modifier_discount_amount = channel_base_rate * (modifier_discount / Decimal('100'))
    final_rate = channel_base_rate - modifier_discount_amount
    
    # Apply ceiling
    if apply_ceiling and ceiling_increment > 0:
        final_rate = Decimal(str(math.ceil(float(final_rate) / ceiling_increment) * ceiling_increment))
    
    final_rate = final_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    # Hotel revenue (after commission)
    commission_amount = final_rate * (commission_percent / Decimal('100'))
    hotel_revenue = final_rate - commission_amount
    
    breakdown = {
        'room_base_rate': float(room_base_rate),
        'season_index': float(season_index),
        'room_type_season_modifier': float(room_type_season_modifier),
        'effective_index': float(effective_index),
        'seasonal_rate': float(seasonal_rate),
        'dynamic_multiplier': float(dynamic_multiplier),
        'dynamic_rate': float(dynamic_rate),
        'meal_supplement': float(meal_supplement),
        'meal_total': float(meal_total),
        'bar_rate': float(bar_rate),
        'channel_base_discount': float(channel_base_discount),
        'channel_discount_amount': float(channel_discount_amount),
        'channel_base_rate': float(channel_base_rate),
        'modifier_discount': float(modifier_discount),
        'modifier_discount_amount': float(modifier_discount_amount),
        'final_rate': float(final_rate),
        'commission_percent': float(commission_percent),
        'commission_amount': float(commission_amount),
        'hotel_revenue': float(hotel_revenue.quantize(Decimal('0.01'))),
    }
    
    return final_rate, breakdown


def calculate_final_rate_with_modifier(room_base_rate, season_index, meal_supplement,
                                        channel_base_discount, modifier_discount,
                                        commission_percent, occupancy=2,
                                        apply_ceiling=False, ceiling_increment=5,
                                        room_type_season_modifier=Decimal('1.00'),
                                        dynamic_multiplier=Decimal('1.00')):
    """Alias for calculate_final_rate for backward compatibility."""
    return calculate_final_rate(
        room_base_rate, season_index, meal_supplement,
        channel_base_discount, modifier_discount,
        commission_percent, occupancy,
        apply_ceiling, ceiling_increment,
        room_type_season_modifier, dynamic_multiplier
    )


# Re-export helper functions from models
from pricing.models.pricing import (
    get_override_for_date,
    get_all_overrides_for_date,
    get_overrides_for_date_range,
    apply_override_to_bar,
)


__all__ = [
    'PricingService',
    'RevenueForecastService', 'PickupAnalysisService',
    'ReservationImportService', 'BookingAnalysisService',
    'PricingVersionService', 'DynamicPricingService', 'DynamicPricingOptimizer',
    'calculate_final_rate', 'calculate_final_rate_with_modifier',
    'get_override_for_date', 'get_all_overrides_for_date',
    'get_overrides_for_date_range', 'apply_override_to_bar',
]
