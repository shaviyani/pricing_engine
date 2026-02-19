"""
Pricing models package.

Re-exports all models so Django migrations and existing imports
continue to work unchanged:
    from pricing.models import Season, RoomType, etc.
"""

# Core: Organization, Property, Modifier configuration
from .core import (
    Organization,
    Property,
    ModifierTemplate,
    PropertyModifier,
    ModifierRule,
)

# Pricing: Versions, Seasons, rooms, rates, channels, overrides, dynamic pricing
from .pricing import (
    PricingMatrixVersion,
    Season,
    RoomType,
    RatePlan,
    Channel,
    TravelAgent,
    RateModifier,
    SeasonModifierOverride,
    RoomTypeSeasonModifier,
    DateRateOverride,
    DateRateOverridePeriod,
    BookingWindowConfig,
    BookingWindowBand,
    DynamicPricingRule,
    DynamicPricingBand,
    DynamicPricingMultiplier,
    EventUplift,
    DynamicPricingSuggestion,
)

# Analytics: Reservations, guests, imports
from .analytics import (
    BookingSource,
    Guest,
    ImportTemplate,
    FileImport,
    Reservation,
)

# Forecasts: Pickup snapshots, curves, occupancy forecasts
from .forecasts import (
    DailyPickupSnapshot,
    MonthlyPickupSnapshot,
    PickupCurve,
    OccupancyForecast,
)

__all__ = [
    # Core
    'Organization', 'Property', 'ModifierTemplate', 'PropertyModifier', 'ModifierRule',
    # Pricing
    'PricingMatrixVersion',
    'Season', 'RoomType', 'RatePlan', 'Channel', 'TravelAgent', 'RateModifier',
    'SeasonModifierOverride', 'RoomTypeSeasonModifier',
    'DateRateOverride', 'DateRateOverridePeriod',
    'BookingWindowConfig', 'BookingWindowBand',
    'DynamicPricingRule', 'DynamicPricingBand', 'DynamicPricingMultiplier',
    'EventUplift', 'DynamicPricingSuggestion',
    # Analytics
    'BookingSource', 'Guest', 'ImportTemplate', 'FileImport', 'Reservation',
    # Forecasts
    'DailyPickupSnapshot', 'MonthlyPickupSnapshot', 'PickupCurve', 'OccupancyForecast',
]
