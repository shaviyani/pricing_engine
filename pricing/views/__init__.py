"""
Views package.

Re-exports all views so existing URL imports work unchanged:
    from pricing.views import PricingMatrixView, etc.
"""

# Mixins
from .mixins import (
    OrganizationMixin,
    PropertyMixin,
    PricingManagementMixin,
    SettingsMixin,
)

# Core views
from .core import (
    RootRedirectView,
    OrganizationSelectorView,
    OrganizationDashboardView,
    PropertyListView,
    PropertyDashboardView,
)

# Pricing views
from .pricing import (
    PricingMatrixView,
    PricingMatrixPDFView,
    PricingMatrixChannelView,
    DateRateOverrideCalendarView,
    parity_data_ajax,
    update_room,
    update_season,
    date_rate_detail_ajax,
    calendar_rates_ajax,
)

# Analytics views
from .analytics import (
    BookingAnalysisDashboardView,
    booking_analysis_data_ajax,
    MonthDetailAPIView,
)

# Forecast views
from .forecasts import (
    PickupDashboardView,
    pickup_dashboard_data_ajax,
    forecast_month_detail_ajax,
    revenue_forecast_ajax,
    pickup_summary_ajax,
)

# Admin / Management views
from .admin_views import (
    PricingManagementView,
    ManageLandingView,
    ManageOrganizationView,
    ManagePropertyView,
    ManagePricingView,
    ManageOffersView,
    ManageImportView,
    ManageReportsView,
    PropertyUpdateView,
    # Seasons
    SeasonListView,
    SeasonCreateView,
    SeasonUpdateView,
    SeasonDeleteView,
    # Room Types
    RoomTypeListView,
    RoomTypeCreateView,
    RoomTypeUpdateView,
    RoomTypeDeleteView,
    RoomTypeReorderView,
    # Rate Plans
    RatePlanListView,
    RatePlanCreateView,
    RatePlanUpdateView,
    RatePlanDeleteView,
    # Channels
    ChannelListView,
    ChannelCreateView,
    ChannelUpdateView,
    ChannelDeleteView,
    ChannelNormalizeDistributionView,
    ChannelEqualDistributionView,
    # Rate Modifiers
    RateModifierListView,
    RateModifierCreateView,
    RateModifierUpdateView,
    RateModifierDeleteView,
    RateModifierToggleView,
    # Season Modifier Overrides
    SeasonModifierOverrideListView,
    SeasonModifierOverrideUpdateView,
    SeasonModifierOverrideResetView,
    SeasonModifierOverrideBulkPopulateView,
    # Organization & Property Settings
    OrganizationSettingsView,
    OrganizationUpdateView,
    PropertyCreateView,
    PropertyDeleteView,
    # Room Type Season Modifiers
    RoomTypeSeasonModifierListView,
    RoomTypeSeasonModifierUpdateView,
    RoomTypeSeasonModifierBulkUpdateView,
    RoomTypeSeasonModifierResetView,
)