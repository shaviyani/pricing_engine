"""Admin URL patterns: Management CRUD and organization/property settings."""

from django.urls import path
from pricing.views import (
    PricingManagementView, PropertyUpdateView,
    ManageLandingView, ManageOrganizationView, ManagePropertyView,
    ManagePricingView, ManageDynamicView, ManageImportView,
    ManageVersionDetailView,
    # Consolidated CRUD views
    SeasonCrudView, RoomTypeCrudView, RatePlanCrudView, ChannelCrudView,
    TravelAgentCrudView, CompetitorCrudView, ImportTemplateCrudView,
    # Backward-compat aliases (still used by getApiUrl JS helper)
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
    RoomAvailabilityView,
)

_P = 'org/<slug:org_code>/<slug:prop_code>'

# Property-scoped management URLs
urlpatterns = [
    # Management landing + section pages
    path(f'{_P}/manage/',
         ManageLandingView.as_view(), name='manage_landing'),
    path(f'{_P}/manage/overview/',
         ManageLandingView.as_view(), name='pricing_management'),
    path(f'{_P}/manage/organization/',
         ManageOrganizationView.as_view(), name='manage_organization'),
    path(f'{_P}/manage/property/',
         ManagePropertyView.as_view(), name='manage_property'),
    path(f'{_P}/manage/pricing/',
         ManagePricingView.as_view(), name='manage_pricing'),
    path(f'{_P}/manage/dynamic/',
         ManageDynamicView.as_view(), name='manage_dynamic'),
    path(f'{_P}/manage/import/',
         ManageImportView.as_view(), name='manage_import'),
    path(f'{_P}/manage/versions/<int:version_id>/',
         ManageVersionDetailView.as_view(), name='manage_version_detail'),

    # Property settings
    path(f'{_P}/api/property/update/',
         PropertyUpdateView.as_view(), name='api_property_update'),

    # ── Seasons (consolidated) ───────────────────────────────────────
    path(f'{_P}/api/seasons/',
         SeasonCrudView.as_view(), name='api_seasons'),
    path(f'{_P}/api/seasons/<int:pk>/',
         SeasonCrudView.as_view(), name='api_season_detail'),
    # Backward-compat URLs (used by getApiUrl JS helper)
    path(f'{_P}/api/seasons/', SeasonListView.as_view(), name='api_season_list'),
    path(f'{_P}/api/seasons/create/', SeasonCreateView.as_view(), name='api_season_create'),
    path(f'{_P}/api/seasons/<int:pk>/update/', SeasonUpdateView.as_view(), name='api_season_update'),
    path(f'{_P}/api/seasons/<int:pk>/delete/', SeasonDeleteView.as_view(), name='api_season_delete'),

    # ── Room Types (consolidated) ────────────────────────────────────
    path(f'{_P}/api/room-types/',
         RoomTypeCrudView.as_view(), name='api_room_types'),
    path(f'{_P}/api/room-types/<int:pk>/',
         RoomTypeCrudView.as_view(), name='api_room_type_detail'),
    # Backward-compat URLs
    path(f'{_P}/api/room-types/', RoomTypeListView.as_view(), name='api_room_type_list'),
    path(f'{_P}/api/room-types/create/', RoomTypeCreateView.as_view(), name='api_room_type_create'),
    path(f'{_P}/api/room-types/<int:pk>/update/', RoomTypeUpdateView.as_view(), name='api_room_type_update'),
    path(f'{_P}/api/room-types/<int:pk>/delete/', RoomTypeDeleteView.as_view(), name='api_room_type_delete'),
    path(f'{_P}/api/room-types/reorder/', RoomTypeReorderView.as_view(), name='api_room_type_reorder'),

    # Season Modifier Overrides (no consolidation — custom logic)
    path(f'{_P}/api/season-overrides/',
         SeasonModifierOverrideListView.as_view(), name='api_season_override_list'),
    path(f'{_P}/api/season-overrides/<int:pk>/update/',
         SeasonModifierOverrideUpdateView.as_view(), name='api_season_override_update'),
    path(f'{_P}/api/season-overrides/<int:pk>/reset/',
         SeasonModifierOverrideResetView.as_view(), name='api_season_override_reset'),
    path(f'{_P}/api/season-overrides/populate/',
         SeasonModifierOverrideBulkPopulateView.as_view(), name='api_season_override_populate'),

    # Room Type Season Modifiers (no consolidation — custom logic)
    path(f'{_P}/api/room-type-season-modifiers/',
         RoomTypeSeasonModifierListView.as_view(), name='api_rt_season_modifier_list'),
    path(f'{_P}/api/room-type-season-modifiers/update/',
         RoomTypeSeasonModifierUpdateView.as_view(), name='api_rt_season_modifier_update'),
    path(f'{_P}/api/room-type-season-modifiers/bulk-update/',
         RoomTypeSeasonModifierBulkUpdateView.as_view(), name='api_rt_season_modifier_bulk_update'),
    path(f'{_P}/api/room-type-season-modifiers/reset/',
         RoomTypeSeasonModifierResetView.as_view(), name='api_rt_season_modifier_reset'),

    # ── Import Templates (consolidated) ──────────────────────────────
    path(f'{_P}/api/import/upload/',
         ImportUploadView.as_view(), name='api_import_upload'),
    path(f'{_P}/api/import/execute/',
         ImportExecuteView.as_view(), name='api_import_execute'),
    path(f'{_P}/api/import/templates/',
         ImportTemplateCrudView.as_view(), name='api_import_templates'),
    path(f'{_P}/api/import/templates/<int:pk>/',
         ImportTemplateCrudView.as_view(), name='api_import_template_detail'),
    # Backward-compat URLs
    path(f'{_P}/api/import/templates/', ImportTemplateListView.as_view(), name='api_import_template_list'),
    path(f'{_P}/api/import/templates/save/', ImportTemplateSaveView.as_view(), name='api_import_template_save'),
    path(f'{_P}/api/import/templates/<int:pk>/update/', ImportTemplateUpdateView.as_view(), name='api_import_template_update'),
    path(f'{_P}/api/import/templates/<int:pk>/delete/', ImportTemplateDeleteView.as_view(), name='api_import_template_delete'),

    # Reservations API (no consolidation — complex list logic)
    path(f'{_P}/api/reservations/',
         ReservationListView.as_view(), name='api_reservation_list'),
    path(f'{_P}/api/reservations/<int:pk>/update/',
         ReservationUpdateView.as_view(), name='api_reservation_update'),
    path(f'{_P}/api/reservations/<int:pk>/delete/',
         ReservationDeleteView.as_view(), name='api_reservation_delete'),
    path(f'{_P}/api/reservations/bulk-delete/',
         ReservationBulkDeleteView.as_view(), name='api_reservation_bulk_delete'),
    path(f'{_P}/api/reservations/room-type-mapping/',
         RoomTypeMappingListView.as_view(), name='api_room_type_mapping_list'),
    path(f'{_P}/api/reservations/room-type-mapping/update/',
         RoomTypeMappingUpdateView.as_view(), name='api_room_type_mapping_update'),

    # ── Competitive Set (consolidated) ───────────────────────────────
    path(f'{_P}/manage/competitive/',
         ManageCompetitiveView.as_view(), name='manage_competitive'),
    path(f'{_P}/manage/competitive/upload/',
         CompetitiveSetUploadView.as_view(), name='competitive_upload'),
    path(f'{_P}/api/competitors/',
         CompetitorCrudView.as_view(), name='api_competitors'),
    path(f'{_P}/api/competitors/<int:pk>/',
         CompetitorCrudView.as_view(), name='api_competitor_detail'),
    # Backward-compat URLs
    path(f'{_P}/api/competitors/create/', CompetitorCreateView.as_view(), name='api_competitor_create'),
    path(f'{_P}/api/competitors/<int:pk>/update/', CompetitorUpdateView.as_view(), name='api_competitor_update'),
    path(f'{_P}/api/competitors/<int:pk>/delete/', CompetitorDeleteView.as_view(), name='api_competitor_delete'),
    path(f'{_P}/api/market-position/update/',
         MarketPositionUpdateView.as_view(), name='api_market_position_update'),
    path(f'{_P}/api/market-position/recalculate/',
         MarketPositionRecalculateView.as_view(), name='api_market_position_recalculate'),

    # Budget & Groups (Revenue Management — no consolidation)
    path(f'{_P}/manage/budget/',
         ManageBudgetView.as_view(), name='manage_budget'),
    path(f'{_P}/api/budget/save/',
         BudgetSaveView.as_view(), name='api_budget_save'),
    path(f'{_P}/manage/groups/',
         ManageGroupsView.as_view(), name='manage_groups'),
    path(f'{_P}/api/groups/create/',
         GroupAllotmentCreateView.as_view(), name='api_group_create'),
    path(f'{_P}/api/groups/<int:pk>/update/',
         GroupAllotmentUpdateView.as_view(), name='api_group_update'),
    path(f'{_P}/api/groups/<int:pk>/delete/',
         GroupAllotmentDeleteView.as_view(), name='api_group_delete'),
    path(f'{_P}/api/displacement-analysis/',
         DisplacementAnalysisView.as_view(), name='api_displacement_analysis'),
    path(f'{_P}/api/room-availability/',
         RoomAvailabilityView.as_view(), name='api_room_availability'),

    # ── Travel Agents (consolidated) ─────────────────────────────────
    path(f'{_P}/manage/agents/',
         ManageAgentsView.as_view(), name='manage_agents'),
    path(f'{_P}/api/travel-agents/',
         TravelAgentCrudView.as_view(), name='api_travel_agents'),
    path(f'{_P}/api/travel-agents/<int:pk>/',
         TravelAgentCrudView.as_view(), name='api_travel_agent_detail'),
    # Backward-compat URLs
    path(f'{_P}/api/travel-agents/', TravelAgentListView.as_view(), name='api_travel_agent_list'),
    path(f'{_P}/api/travel-agents/create/', TravelAgentCreateView.as_view(), name='api_travel_agent_create'),
    path(f'{_P}/api/travel-agents/<int:pk>/update/', TravelAgentUpdateView.as_view(), name='api_travel_agent_update'),
    path(f'{_P}/api/travel-agents/<int:pk>/delete/', TravelAgentDeleteView.as_view(), name='api_travel_agent_delete'),
]

# Shared (org-level or global) URLs
shared_urlpatterns = [
    # ── Rate Plans (consolidated) ────────────────────────────────────
    path('pricing/api/rate-plans/', RatePlanCrudView.as_view(), name='api_rate_plans'),
    path('pricing/api/rate-plans/<int:pk>/', RatePlanCrudView.as_view(), name='api_rate_plan_detail'),
    # Backward-compat URLs
    path('pricing/api/rate-plans/', RatePlanListView.as_view(), name='api_rate_plan_list'),
    path('pricing/api/rate-plans/create/', RatePlanCreateView.as_view(), name='api_rate_plan_create'),
    path('pricing/api/rate-plans/<int:pk>/update/', RatePlanUpdateView.as_view(), name='api_rate_plan_update'),
    path('pricing/api/rate-plans/<int:pk>/delete/', RatePlanDeleteView.as_view(), name='api_rate_plan_delete'),

    # ── Channels (consolidated) ──────────────────────────────────────
    path('pricing/api/channels/', ChannelListView.as_view(), name='api_channel_list'),
    path('pricing/api/channels/<int:pk>/', ChannelCrudView.as_view(), name='api_channel_detail'),
    # Backward-compat URLs
    path('pricing/api/channels/create/', ChannelCreateView.as_view(), name='api_channel_create'),
    path('pricing/api/channels/<int:pk>/update/', ChannelUpdateView.as_view(), name='api_channel_update'),
    path('pricing/api/channels/<int:pk>/delete/', ChannelDeleteView.as_view(), name='api_channel_delete'),
    path('pricing/api/channels/normalize-distribution/',
         ChannelNormalizeDistributionView.as_view(), name='api_channel_normalize'),
    path('pricing/api/channels/equal-distribution/',
         ChannelEqualDistributionView.as_view(), name='api_channel_equal'),

    # Rate Modifiers (no consolidation — custom stacked recalculation logic)
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
