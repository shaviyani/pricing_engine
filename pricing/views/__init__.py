"""
Views package.

Re-exports all views so existing URL imports work unchanged:
    from pricing.views import PricingMatrixView, etc.
"""

# Mixins and CRUD configs
from .mixins import (
    OrganizationMixin,
    PropertyMixin,
    PricingManagementMixin,
    SettingsMixin,
    ModelCrudMixin,
    RoleRequiredMixin,
    AnalyticsAccessMixin,
    PricingAccessMixin,
    DistributionAccessMixin,
    SetupAccessMixin,
    _SeasonCrud,
    _RatePlanCrud,
    _ChannelCrud,
    _RoomTypeCrud,
    _TravelAgentCrud,
    _CompetitorCrud,
    _ImportTemplateCrud,
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
    CancellationDashboardView,
    booking_heatmap_ajax,
    arrival_forecast_ajax,
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
    # Consolidated CRUD views
    SeasonCrudView,
    RoomTypeCrudView,
    RatePlanCrudView,
    ChannelCrudView,
    TravelAgentCrudView,
    CompetitorCrudView,
    ImportTemplateCrudView,
    # Seasons (backward-compat aliases)
    SeasonListView,
    SeasonCreateView,
    SeasonUpdateView,
    SeasonDeleteView,
    # Room Types (backward-compat aliases)
    RoomTypeListView,
    RoomTypeCreateView,
    RoomTypeUpdateView,
    RoomTypeDeleteView,
    RoomTypeReorderView,
    # Rate Plans (backward-compat aliases)
    RatePlanListView,
    RatePlanCreateView,
    RatePlanUpdateView,
    RatePlanDeleteView,
    # Channels (backward-compat aliases)
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
    # Travel Agents (backward-compat aliases)
    ManageAgentsView,
    TravelAgentListView,
    TravelAgentCreateView,
    TravelAgentUpdateView,
    TravelAgentDeleteView,
    # Competitive Set (backward-compat aliases)
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
    DisplacementAnalysisView,
    RoomAvailabilityView,
)