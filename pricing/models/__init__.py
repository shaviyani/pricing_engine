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

# Pricing: Seasons, rooms, rates, channels, overrides
from .pricing import (
    Season,
    RoomType,
    RatePlan,
    Channel,
    RateModifier,
    SeasonModifierOverride,
    RoomTypeSeasonModifier,
    DateRateOverride,
    DateRateOverridePeriod,
)

# Analytics: Reservations, guests, imports
from .analytics import (
    BookingSource,
    Guest,
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
    'Season', 'RoomType', 'RatePlan', 'Channel', 'RateModifier',
    'SeasonModifierOverride', 'RoomTypeSeasonModifier',
    'DateRateOverride', 'DateRateOverridePeriod',
    # Analytics
    'BookingSource', 'Guest', 'FileImport', 'Reservation',
    # Forecasts
    'DailyPickupSnapshot', 'MonthlyPickupSnapshot', 'PickupCurve', 'OccupancyForecast',
]
