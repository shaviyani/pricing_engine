"""Admin URL patterns: Management CRUD and organization/property settings."""

from django.urls import path
from pricing.views import (
    PricingManagementView, PropertyUpdateView,
    ManageLandingView, ManageOrganizationView, ManagePropertyView,
    ManagePricingView, ManageOffersView, ManageImportView, ManageReportsView,
    SeasonListView, SeasonCreateView, SeasonUpdateView, SeasonDeleteView,
    RoomTypeListView, RoomTypeCreateView, RoomTypeUpdateView, RoomTypeDeleteView, RoomTypeReorderView,
    RatePlanListView, RatePlanCreateView, RatePlanUpdateView, RatePlanDeleteView,
    ChannelListView, ChannelCreateView, ChannelUpdateView, ChannelDeleteView,
    ChannelNormalizeDistributionView, ChannelEqualDistributionView,
    RateModifierListView, RateModifierCreateView, RateModifierUpdateView,
    RateModifierDeleteView, RateModifierToggleView,
    SeasonModifierOverrideListView, SeasonModifierOverrideUpdateView,
    SeasonModifierOverrideResetView, SeasonModifierOverrideBulkPopulateView,
    OrganizationSettingsView, OrganizationUpdateView, PropertyCreateView, PropertyDeleteView,
    RoomTypeSeasonModifierListView, RoomTypeSeasonModifierUpdateView,
    RoomTypeSeasonModifierBulkUpdateView, RoomTypeSeasonModifierResetView,
)

# Property-scoped management URLs
urlpatterns = [
    # Management landing + section pages
    path('<slug:org_code>/<slug:prop_code>/manage/',
         ManageLandingView.as_view(), name='manage_landing'),
    path('<slug:org_code>/<slug:prop_code>/manage/overview/',
         ManageLandingView.as_view(), name='pricing_management'),
    path('<slug:org_code>/<slug:prop_code>/manage/organization/',
         ManageOrganizationView.as_view(), name='manage_organization'),
    path('<slug:org_code>/<slug:prop_code>/manage/property/',
         ManagePropertyView.as_view(), name='manage_property'),
    path('<slug:org_code>/<slug:prop_code>/manage/pricing/',
         ManagePricingView.as_view(), name='manage_pricing'),
    path('<slug:org_code>/<slug:prop_code>/manage/offers/',
         ManageOffersView.as_view(), name='manage_offers'),
    path('<slug:org_code>/<slug:prop_code>/manage/import/',
         ManageImportView.as_view(), name='manage_import'),
    path('<slug:org_code>/<slug:prop_code>/manage/reports/',
         ManageReportsView.as_view(), name='manage_reports'),

    # Property settings
    path('<slug:org_code>/<slug:prop_code>/api/property/update/',
         PropertyUpdateView.as_view(), name='api_property_update'),

    # Seasons
    path('<slug:org_code>/<slug:prop_code>/api/seasons/',
         SeasonListView.as_view(), name='api_season_list'),
    path('<slug:org_code>/<slug:prop_code>/api/seasons/create/',
         SeasonCreateView.as_view(), name='api_season_create'),
    path('<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/update/',
         SeasonUpdateView.as_view(), name='api_season_update'),
    path('<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/delete/',
         SeasonDeleteView.as_view(), name='api_season_delete'),

    # Room Types
    path('<slug:org_code>/<slug:prop_code>/api/room-types/',
         RoomTypeListView.as_view(), name='api_room_type_list'),
    path('<slug:org_code>/<slug:prop_code>/api/room-types/create/',
         RoomTypeCreateView.as_view(), name='api_room_type_create'),
    path('<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/update/',
         RoomTypeUpdateView.as_view(), name='api_room_type_update'),
    path('<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/delete/',
         RoomTypeDeleteView.as_view(), name='api_room_type_delete'),
    path('<slug:org_code>/<slug:prop_code>/api/room-types/reorder/',
         RoomTypeReorderView.as_view(), name='api_room_type_reorder'),

    # Season Modifier Overrides
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/',
         SeasonModifierOverrideListView.as_view(), name='api_season_override_list'),
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/update/',
         SeasonModifierOverrideUpdateView.as_view(), name='api_season_override_update'),
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/reset/',
         SeasonModifierOverrideResetView.as_view(), name='api_season_override_reset'),
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/populate/',
         SeasonModifierOverrideBulkPopulateView.as_view(), name='api_season_override_populate'),

    # Room Type Season Modifiers
    path('<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/',
         RoomTypeSeasonModifierListView.as_view(), name='api_rt_season_modifier_list'),
    path('<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/update/',
         RoomTypeSeasonModifierUpdateView.as_view(), name='api_rt_season_modifier_update'),
    path('<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/bulk-update/',
         RoomTypeSeasonModifierBulkUpdateView.as_view(), name='api_rt_season_modifier_bulk_update'),
    path('<slug:org_code>/<slug:prop_code>/api/room-type-season-modifiers/reset/',
         RoomTypeSeasonModifierResetView.as_view(), name='api_rt_season_modifier_reset'),
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

    # Organization Settings
    path('<slug:org_code>/settings/', OrganizationSettingsView.as_view(), name='organization_settings'),
    path('<slug:org_code>/api/organization/update/', OrganizationUpdateView.as_view(), name='api_organization_update'),
    path('<slug:org_code>/api/properties/create/', PropertyCreateView.as_view(), name='api_property_create'),
    path('<slug:org_code>/api/properties/<int:pk>/delete/', PropertyDeleteView.as_view(), name='api_property_delete'),
    path('<slug:org_code>/<slug:prop_code>/api/property/update/', PropertyUpdateView.as_view(), name='api_property_update'),
]

urlpatterns += shared_urlpatterns