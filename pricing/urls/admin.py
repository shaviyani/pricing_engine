"""Admin URL patterns: Management CRUD and organization/property settings."""

from django.urls import path
from pricing.views import (
    PricingManagementView, PropertyUpdateView,
    ManageLandingView, ManageOrganizationView, ManagePropertyView,
    ManagePricingView, ManageDynamicView, ManageImportView,
    ManageVersionDetailView,
    SeasonListView, SeasonCreateView, SeasonUpdateView, SeasonDeleteView,
    RoomTypeListView, RoomTypeCreateView, RoomTypeUpdateView, RoomTypeDeleteView, RoomTypeReorderView,
    RatePlanListView, RatePlanCreateView, RatePlanUpdateView, RatePlanDeleteView,
    ChannelListView, ChannelCreateView, ChannelUpdateView, ChannelDeleteView,
    ChannelNormalizeDistributionView, ChannelEqualDistributionView,
    RateModifierListView, RateModifierCreateView, RateModifierUpdateView,
    RateModifierDeleteView, RateModifierToggleView,
    SeasonModifierOverrideListView, SeasonModifierOverrideUpdateView,
    SeasonModifierOverrideResetView, SeasonModifierOverrideBulkPopulateView,
    OrganizationUpdateView, PropertyCreateView, PropertyDeleteView,
    RoomTypeSeasonModifierListView, RoomTypeSeasonModifierUpdateView,
    RoomTypeSeasonModifierBulkUpdateView, RoomTypeSeasonModifierResetView,
    ImportUploadView, ImportExecuteView,
    ImportTemplateListView, ImportTemplateSaveView,
    ImportTemplateUpdateView, ImportTemplateDeleteView,
    ReservationListView, ReservationUpdateView, ReservationDeleteView,
    ReservationBulkDeleteView,
    RoomTypeMappingListView, RoomTypeMappingUpdateView,
    ManageAgentsView,
    TravelAgentListView, TravelAgentCreateView, TravelAgentUpdateView, TravelAgentDeleteView,
    ManageCompetitiveView,
    CompetitiveSetUploadView,
    CompetitorCreateView,
    CompetitorUpdateView,
    CompetitorDeleteView,
    MarketPositionUpdateView,
    MarketPositionRecalculateView,
    # Revenue management
    ManageBudgetView,
    BudgetSaveView,
    ManageGroupsView,
    GroupAllotmentCreateView,
    GroupAllotmentUpdateView,
    GroupAllotmentDeleteView,
    DisplacementAnalysisView,
)

# Property-scoped management URLs
urlpatterns = [
    # Management landing + section pages
    path('org/<slug:org_code>/<slug:prop_code>/manage/',
         ManageLandingView.as_view(), name='manage_landing'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/overview/',
         ManageLandingView.as_view(), name='pricing_management'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/organization/',
         ManageOrganizationView.as_view(), name='manage_organization'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/property/',
         ManagePropertyView.as_view(), name='manage_property'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/pricing/',
         ManagePricingView.as_view(), name='manage_pricing'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/dynamic/',
         ManageDynamicView.as_view(), name='manage_dynamic'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/import/',
         ManageImportView.as_view(), name='manage_import'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/versions/<int:version_id>/',
         ManageVersionDetailView.as_view(), name='manage_version_detail'),

    # Property settings
    path('org/<slug:org_code>/<slug:prop_code>/api/property/update/',
         PropertyUpdateView.as_view(), name='api_property_update'),

    # Seasons
    path('org/<slug:org_code>/<slug:prop_code>/api/seasons/',
         SeasonListView.as_view(), name='api_season_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/seasons/create/',
         SeasonCreateView.as_view(), name='api_season_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/update/',
         SeasonUpdateView.as_view(), name='api_season_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/delete/',
         SeasonDeleteView.as_view(), name='api_season_delete'),

    # Room Types
    path('org/<slug:org_code>/<slug:prop_code>/api/room-types/',
         RoomTypeListView.as_view(), name='api_room_type_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-types/create/',
         RoomTypeCreateView.as_view(), name='api_room_type_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/update/',
         RoomTypeUpdateView.as_view(), name='api_room_type_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/delete/',
         RoomTypeDeleteView.as_view(), name='api_room_type_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-types/reorder/',
         RoomTypeReorderView.as_view(), name='api_room_type_reorder'),

    # Season Modifier Overrides
    path('org/<slug:org_code>/<slug:prop_code>/api/season-overrides/',
         SeasonModifierOverrideListView.as_view(), name='api_season_override_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/update/',
         SeasonModifierOverrideUpdateView.as_view(), name='api_season_override_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/reset/',
         SeasonModifierOverrideResetView.as_view(), name='api_season_override_reset'),
    path('org/<slug:org_code>/<slug:prop_code>/api/season-overrides/populate/',
         SeasonModifierOverrideBulkPopulateView.as_view(), name='api_season_override_populate'),

    # Room Type Season Modifiers
    path('org/<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/',
         RoomTypeSeasonModifierListView.as_view(), name='api_rt_season_modifier_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/update/',
         RoomTypeSeasonModifierUpdateView.as_view(), name='api_rt_season_modifier_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/bulk-update/',
         RoomTypeSeasonModifierBulkUpdateView.as_view(), name='api_rt_season_modifier_bulk_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/reset/',
         RoomTypeSeasonModifierResetView.as_view(), name='api_rt_season_modifier_reset'),

    # Import API
    path('org/<slug:org_code>/<slug:prop_code>/api/import/upload/',
         ImportUploadView.as_view(), name='api_import_upload'),
    path('org/<slug:org_code>/<slug:prop_code>/api/import/execute/',
         ImportExecuteView.as_view(), name='api_import_execute'),
    path('org/<slug:org_code>/<slug:prop_code>/api/import/templates/',
         ImportTemplateListView.as_view(), name='api_import_template_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/import/templates/save/',
         ImportTemplateSaveView.as_view(), name='api_import_template_save'),
    path('org/<slug:org_code>/<slug:prop_code>/api/import/templates/<int:pk>/update/',
         ImportTemplateUpdateView.as_view(), name='api_import_template_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/import/templates/<int:pk>/delete/',
         ImportTemplateDeleteView.as_view(), name='api_import_template_delete'),

    # Reservations API
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/',
         ReservationListView.as_view(), name='api_reservation_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/<int:pk>/update/',
         ReservationUpdateView.as_view(), name='api_reservation_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/<int:pk>/delete/',
         ReservationDeleteView.as_view(), name='api_reservation_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/bulk-delete/',
         ReservationBulkDeleteView.as_view(), name='api_reservation_bulk_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/room-type-mapping/',
         RoomTypeMappingListView.as_view(), name='api_room_type_mapping_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/reservations/room-type-mapping/update/',
         RoomTypeMappingUpdateView.as_view(), name='api_room_type_mapping_update'),

    # Competitive Set
    path('org/<slug:org_code>/<slug:prop_code>/manage/competitive/',
         ManageCompetitiveView.as_view(), name='manage_competitive'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/competitive/upload/',
         CompetitiveSetUploadView.as_view(), name='competitive_upload'),
    path('org/<slug:org_code>/<slug:prop_code>/api/competitors/create/',
         CompetitorCreateView.as_view(), name='api_competitor_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/competitors/<int:pk>/update/',
         CompetitorUpdateView.as_view(), name='api_competitor_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/competitors/<int:pk>/delete/',
         CompetitorDeleteView.as_view(), name='api_competitor_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-position/update/',
         MarketPositionUpdateView.as_view(), name='api_market_position_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-position/recalculate/',
         MarketPositionRecalculateView.as_view(), name='api_market_position_recalculate'),

    # Budget & Groups (Revenue Management)
    path('org/<slug:org_code>/<slug:prop_code>/manage/budget/',
         ManageBudgetView.as_view(), name='manage_budget'),
    path('org/<slug:org_code>/<slug:prop_code>/api/budget/save/',
         BudgetSaveView.as_view(), name='api_budget_save'),
    path('org/<slug:org_code>/<slug:prop_code>/manage/groups/',
         ManageGroupsView.as_view(), name='manage_groups'),
    path('org/<slug:org_code>/<slug:prop_code>/api/groups/create/',
         GroupAllotmentCreateView.as_view(), name='api_group_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/groups/<int:pk>/update/',
         GroupAllotmentUpdateView.as_view(), name='api_group_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/groups/<int:pk>/delete/',
         GroupAllotmentDeleteView.as_view(), name='api_group_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/displacement-analysis/',
         DisplacementAnalysisView.as_view(), name='api_displacement_analysis'),

    # Travel Agents
    path('org/<slug:org_code>/<slug:prop_code>/manage/agents/',
         ManageAgentsView.as_view(), name='manage_agents'),
    path('org/<slug:org_code>/<slug:prop_code>/api/travel-agents/',
         TravelAgentListView.as_view(), name='api_travel_agent_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/travel-agents/create/',
         TravelAgentCreateView.as_view(), name='api_travel_agent_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/travel-agents/<int:pk>/update/',
         TravelAgentUpdateView.as_view(), name='api_travel_agent_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/travel-agents/<int:pk>/delete/',
         TravelAgentDeleteView.as_view(), name='api_travel_agent_delete'),
]

# Shared (org-level or global) URLs
shared_urlpatterns = [
    # Rate Plans
    path('pricing/api/rate-plans/', RatePlanListView.as_view(), name='api_rate_plan_list'),
    path('pricing/api/rate-plans/create/', RatePlanCreateView.as_view(), name='api_rate_plan_create'),
    path('pricing/api/rate-plans/<int:pk>/update/', RatePlanUpdateView.as_view(), name='api_rate_plan_update'),
    path('pricing/api/rate-plans/<int:pk>/delete/', RatePlanDeleteView.as_view(), name='api_rate_plan_delete'),

    # Channels
    path('pricing/api/channels/', ChannelListView.as_view(), name='api_channel_list'),
    path('pricing/api/channels/create/', ChannelCreateView.as_view(), name='api_channel_create'),
    path('pricing/api/channels/<int:pk>/update/', ChannelUpdateView.as_view(), name='api_channel_update'),
    path('pricing/api/channels/<int:pk>/delete/', ChannelDeleteView.as_view(), name='api_channel_delete'),
    path('pricing/api/channels/normalize-distribution/',
         ChannelNormalizeDistributionView.as_view(), name='api_channel_normalize'),
    path('pricing/api/channels/equal-distribution/',
         ChannelEqualDistributionView.as_view(), name='api_channel_equal'),

    # Rate Modifiers
    path('pricing/api/modifiers/', RateModifierListView.as_view(), name='api_modifier_list'),
    path('pricing/api/modifiers/create/', RateModifierCreateView.as_view(), name='api_modifier_create'),
    path('pricing/api/modifiers/<int:pk>/update/', RateModifierUpdateView.as_view(), name='api_modifier_update'),
    path('pricing/api/modifiers/<int:pk>/delete/', RateModifierDeleteView.as_view(), name='api_modifier_delete'),
    path('pricing/api/modifiers/<int:pk>/toggle/', RateModifierToggleView.as_view(), name='api_modifier_toggle'),

    # Organization API
    path('org/<slug:org_code>/api/organization/update/', OrganizationUpdateView.as_view(), name='api_organization_update'),
    path('org/<slug:org_code>/api/properties/create/', PropertyCreateView.as_view(), name='api_property_create'),
    path('org/<slug:org_code>/api/properties/<int:pk>/delete/', PropertyDeleteView.as_view(), name='api_property_delete'),
    path('org/<slug:org_code>/<slug:prop_code>/api/property/update/', PropertyUpdateView.as_view(), name='api_property_update'),
]

urlpatterns += shared_urlpatterns