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
    UserOrganizationRole,
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
)

# Analytics: Reservations, guests, imports
from .analytics import (
    BookingSource,
    Guest,
    ImportTemplate,
    FileImport,
    Reservation,
)


# Competitive intelligence
from .competitive import (
    CompetitiveSet,
    MarketPosition,
)

# Revenue management
from .revenue import (
    MarketSegment,
    GroupAllotment,
    MonthlyBudget,
    LengthOfStayTier,
)

__all__ = [
    # Core
    'Organization', 'Property', 'UserOrganizationRole', 'PropertyModifier', 'ModifierRule',
    # Pricing
    'PricingMatrixVersion',
    'Season', 'RoomType', 'RatePlan', 'Channel', 'TravelAgent', 'RateModifier',
    'SeasonModifierOverride', 'RoomTypeSeasonModifier',
    'DateRateOverride', 'DateRateOverridePeriod',
    'BookingWindowConfig', 'BookingWindowBand',
    'DynamicPricingRule', 'DynamicPricingBand', 'DynamicPricingMultiplier',
    'EventUplift',
    # Analytics
    'BookingSource', 'Guest', 'ImportTemplate', 'FileImport', 'Reservation',
    # Competitive
    'CompetitiveSet', 'MarketPosition',
    # Revenue management
    'MarketSegment', 'GroupAllotment', 'MonthlyBudget', 'LengthOfStayTier',
]
