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
    ModelCrudMixin,
)

# Core views
from .core import (
    RootRedirectView,
    OrganizationSelectorView,
    OrganizationDashboardView,
    PropertyListView,
    PropertyDashboardView,
    MarketContextAjaxView,
)

# Pricing views
from .pricing import (
    PricingMatrixView,
    PricingMatrixPDFView,
    PricingMatrixChannelView,
    RateLookupView,
    RateLookupAPIView,
    ItineraryQuoteAPIView,
    AgentRatesView,
    AgentRateCardView,
    AgentRateCardPDFView,
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
    DemandIndexAjaxView,
    BookingTrendsView,
    booking_trends_data_ajax,
    BookingOriginMatrixView,
)

# Forecast views
from .forecasts import (
    PickupDashboardView,
    pickup_dashboard_data_ajax,
    forecast_month_detail_ajax,
    revenue_forecast_ajax,
    pickup_summary_ajax,
    occupancy_calendar_ajax,
    DemandForecastView,
    generate_demand_forecast_ajax,
)

# Admin / Management views
from .admin_views import (
    PricingManagementView,
    ManageLandingView,
    ManageOrganizationView,
    ManagePropertyView,
    ManagePricingView,
    ManageDynamicView,
    ManageOffersView,
    ManageImportView,
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
    OrganizationUpdateView,
    PropertyCreateView,
    PropertyDeleteView,
    # Room Type Season Modifiers
    RoomTypeSeasonModifierListView,
    RoomTypeSeasonModifierUpdateView,
    RoomTypeSeasonModifierBulkUpdateView,
    RoomTypeSeasonModifierResetView,
    ManageVersionDetailView,
    # Import Templates
    ImportUploadView,
    ImportExecuteView,
    ImportTemplateListView,
    ImportTemplateSaveView,
    ImportTemplateUpdateView,
    ImportTemplateDeleteView,
    # Reservations
    ReservationListView,
    ReservationUpdateView,
    ReservationDeleteView,
    ReservationBulkDeleteView,
    # Room Type Mapping
    RoomTypeMappingListView,
    RoomTypeMappingUpdateView,
    # Travel Agents
    ManageAgentsView,
    TravelAgentListView,
    TravelAgentCreateView,
    TravelAgentUpdateView,
    TravelAgentDeleteView,
    # Competitive Set
    ManageCompetitiveView,
    CompetitiveSetUploadView,
    CompetitorCreateView,
    CompetitorUpdateView,
    CompetitorDeleteView,
    MarketPositionUpdateView,
    MarketPositionRecalculateView,
)

# Revenue management views
from .revenue_views import (
    ManageBudgetView,
    BudgetSaveView,
    ManageGroupsView,
    GroupAllotmentCreateView,
    GroupAllotmentUpdateView,
    GroupAllotmentDeleteView,
)