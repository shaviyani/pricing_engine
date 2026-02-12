"""
Pricing Management URL Patterns
===============================

Add these to your pricing/urls.py file.

URL Structure:
    /pricing/manage/                              - Management dashboard
    /pricing/manage/seasons/                      - Season CRUD
    /pricing/manage/room-types/                   - Room Type CRUD
    /pricing/manage/rate-plans/                   - Rate Plan CRUD
    /pricing/manage/channels/                     - Channel CRUD
    /pricing/manage/modifiers/                    - Rate Modifier CRUD
    /pricing/manage/season-overrides/             - Season Modifier Override CRUD
"""

from django.urls import path
from .views import (
    # Dashboard
    PricingManagementView,
    
    # Property Settings
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
    
    # Season Modifier Overrides
    OrganizationSettingsView,
    OrganizationUpdateView,
    PropertyUpdateView,
    PropertyCreateView,
    PropertyDeleteView,
)

# NOTE: app_name is defined in pricing/urls.py, not here
# This file is included into the main urlpatterns

# Property-specific patterns (with org_code and prop_code)
urlpatterns = [
    # Management Dashboard
    path('<slug:org_code>/<slug:prop_code>/manage/', 
         PricingManagementView.as_view(), 
         name='pricing_management'),
    
    # =========================================================================
    # PROPERTY SETTINGS
    # =========================================================================
    path('<slug:org_code>/<slug:prop_code>/api/property/update/', 
         PropertyUpdateView.as_view(), 
         name='api_property_update'),
    
    # =========================================================================
    # SEASONS (Property-specific)
    # =========================================================================
    path('<slug:org_code>/<slug:prop_code>/api/seasons/', 
         SeasonListView.as_view(), 
         name='api_season_list'),
    
    path('<slug:org_code>/<slug:prop_code>/api/seasons/create/', 
         SeasonCreateView.as_view(), 
         name='api_season_create'),
    
    path('<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/update/', 
         SeasonUpdateView.as_view(), 
         name='api_season_update'),
    
    path('<slug:org_code>/<slug:prop_code>/api/seasons/<int:pk>/delete/', 
         SeasonDeleteView.as_view(), 
         name='api_season_delete'),
    
    # =========================================================================
    # ROOM TYPES (Property-specific)
    # =========================================================================
    path('<slug:org_code>/<slug:prop_code>/api/room-types/', 
         RoomTypeListView.as_view(), 
         name='api_room_type_list'),
    
    path('<slug:org_code>/<slug:prop_code>/api/room-types/create/', 
         RoomTypeCreateView.as_view(), 
         name='api_room_type_create'),
    
    path('<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/update/', 
         RoomTypeUpdateView.as_view(), 
         name='api_room_type_update'),
    
    path('<slug:org_code>/<slug:prop_code>/api/room-types/<int:pk>/delete/', 
         RoomTypeDeleteView.as_view(), 
         name='api_room_type_delete'),
    
    path('<slug:org_code>/<slug:prop_code>/api/room-types/reorder/', 
         RoomTypeReorderView.as_view(), 
         name='api_room_type_reorder'),
    
    # =========================================================================
    # SEASON MODIFIER OVERRIDES (Property-specific)
    # =========================================================================
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/', 
         SeasonModifierOverrideListView.as_view(), 
         name='api_season_override_list'),
    
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/update/', 
         SeasonModifierOverrideUpdateView.as_view(), 
         name='api_season_override_update'),
    
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/<int:pk>/reset/', 
         SeasonModifierOverrideResetView.as_view(), 
         name='api_season_override_reset'),
    
    path('<slug:org_code>/<slug:prop_code>/api/season-overrides/populate/', 
         SeasonModifierOverrideBulkPopulateView.as_view(), 
         name='api_season_override_populate'),
]

# Shared patterns (with /pricing/ prefix - these are global/shared)
shared_urlpatterns = [
    # =========================================================================
    # RATE PLANS (Shared)
    # =========================================================================
    path('pricing/api/rate-plans/', 
         RatePlanListView.as_view(), 
         name='api_rate_plan_list'),
    
    path('pricing/api/rate-plans/create/', 
         RatePlanCreateView.as_view(), 
         name='api_rate_plan_create'),
    
    path('pricing/api/rate-plans/<int:pk>/update/', 
         RatePlanUpdateView.as_view(), 
         name='api_rate_plan_update'),
    
    path('pricing/api/rate-plans/<int:pk>/delete/', 
         RatePlanDeleteView.as_view(), 
         name='api_rate_plan_delete'),
    
    # =========================================================================
    # CHANNELS (Shared)
    # =========================================================================
    path('pricing/api/channels/', 
         ChannelListView.as_view(), 
         name='api_channel_list'),
    
    path('pricing/api/channels/create/', 
         ChannelCreateView.as_view(), 
         name='api_channel_create'),
    
    path('pricing/api/channels/<int:pk>/update/', 
         ChannelUpdateView.as_view(), 
         name='api_channel_update'),
    
    path('pricing/api/channels/<int:pk>/delete/', 
         ChannelDeleteView.as_view(), 
         name='api_channel_delete'),
    
    path('pricing/api/channels/normalize-distribution/', 
         ChannelNormalizeDistributionView.as_view(), 
         name='api_channel_normalize'),
    
    path('pricing/api/channels/equal-distribution/', 
         ChannelEqualDistributionView.as_view(), 
         name='api_channel_equal'),
    
    # =========================================================================
    # RATE MODIFIERS (Shared)
    # =========================================================================
    path('pricing/api/modifiers/', 
         RateModifierListView.as_view(), 
         name='api_modifier_list'),
    
    path('pricing/api/modifiers/create/', 
         RateModifierCreateView.as_view(), 
         name='api_modifier_create'),
    
    path('pricing/api/modifiers/<int:pk>/update/', 
         RateModifierUpdateView.as_view(), 
         name='api_modifier_update'),
    
    path('pricing/api/modifiers/<int:pk>/delete/', 
         RateModifierDeleteView.as_view(), 
         name='api_modifier_delete'),
    
    path('pricing/api/modifiers/<int:pk>/toggle/', 
         RateModifierToggleView.as_view(), 
         name='api_modifier_toggle'),
    
    
    
    
     # Organization Settings
    path('<slug:org_code>/settings/', 
         OrganizationSettingsView.as_view(), 
         name='organization_settings'),
    
    path('<slug:org_code>/api/organization/update/', 
         OrganizationUpdateView.as_view(), 
         name='api_organization_update'),
    
    path('<slug:org_code>/api/properties/create/', 
         PropertyCreateView.as_view(), 
         name='api_property_create'),
    
    path('<slug:org_code>/api/properties/<int:pk>/delete/', 
         PropertyDeleteView.as_view(), 
         name='api_property_delete'),
    
    path('<slug:org_code>/<slug:prop_code>/api/property/update/', 
         PropertyUpdateView.as_view(), 
         name='api_property_update'),
]

# Combine patterns
urlpatterns += shared_urlpatterns