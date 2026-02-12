"""Core URL patterns: Root, org selection, property selection."""

from django.urls import path
from pricing.views import (
    RootRedirectView,
    OrganizationSelectorView,
    OrganizationDashboardView,
    PropertyListView,
    PropertyDashboardView,
)

urlpatterns = [
    path('', RootRedirectView.as_view(), name='root'),
    path('org/', OrganizationSelectorView.as_view(), name='org_selector'),
    path('org/<slug:org_code>/', OrganizationDashboardView.as_view(), name='org_dashboard'),
    path('org/<slug:org_code>/properties/', PropertyListView.as_view(), name='property_list'),
    path('org/<slug:org_code>/<slug:prop_code>/', PropertyDashboardView.as_view(), name='property_dashboard'),
]
