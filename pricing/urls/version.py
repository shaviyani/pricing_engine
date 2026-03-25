"""URL patterns for version management and dynamic pricing."""

from django.urls import path
from pricing.views.version_views import (
    VersionListView, VersionCreateDraftView, VersionPublishView,
    VersionDiscardView, VersionRevertView, VersionInitializeView,
    DynamicPricingRuleListView, DynamicPricingMultiplierUpdateView,
    DynamicPricingSeedView, DynamicPricingPreviewView,
    EventUpliftListView, EventUpliftCreateView, EventUpliftUpdateView, EventUpliftDeleteView,
)

urlpatterns = [
    # Version management
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/',
         VersionListView.as_view(), name='api_version_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/create-draft/',
         VersionCreateDraftView.as_view(), name='api_version_create_draft'),
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/publish/',
         VersionPublishView.as_view(), name='api_version_publish'),
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/discard/',
         VersionDiscardView.as_view(), name='api_version_discard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/revert/<int:version_number>/',
         VersionRevertView.as_view(), name='api_version_revert'),
    path('org/<slug:org_code>/<slug:prop_code>/api/versions/initialize/',
         VersionInitializeView.as_view(), name='api_version_initialize'),

    # Dynamic pricing
    path('org/<slug:org_code>/<slug:prop_code>/api/dynamic-pricing/rules/',
         DynamicPricingRuleListView.as_view(), name='api_dp_rule_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/dynamic-pricing/multiplier/update/',
         DynamicPricingMultiplierUpdateView.as_view(), name='api_dp_multiplier_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/dynamic-pricing/seed/',
         DynamicPricingSeedView.as_view(), name='api_dp_seed'),
    path('org/<slug:org_code>/<slug:prop_code>/api/dynamic-pricing/preview/',
         DynamicPricingPreviewView.as_view(), name='api_dp_preview'),

    # Event uplifts
    path('org/<slug:org_code>/<slug:prop_code>/api/event-uplifts/',
         EventUpliftListView.as_view(), name='api_event_uplift_list'),
    path('org/<slug:org_code>/<slug:prop_code>/api/event-uplifts/create/',
         EventUpliftCreateView.as_view(), name='api_event_uplift_create'),
    path('org/<slug:org_code>/<slug:prop_code>/api/event-uplifts/<int:pk>/update/',
         EventUpliftUpdateView.as_view(), name='api_event_uplift_update'),
    path('org/<slug:org_code>/<slug:prop_code>/api/event-uplifts/<int:pk>/delete/',
         EventUpliftDeleteView.as_view(), name='api_event_uplift_delete'),

]
