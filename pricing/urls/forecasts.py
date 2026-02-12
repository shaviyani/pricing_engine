"""Forecast URL patterns: Pickup dashboard, revenue forecast, AJAX."""

from django.urls import path
from pricing.views import (
    PickupDashboardView,
    revenue_forecast_ajax,
    pickup_summary_ajax,
)

urlpatterns = [
    path('org/<slug:org_code>/<slug:prop_code>/pickup/',
         PickupDashboardView.as_view(), name='pickup_dashboard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/revenue-forecast/',
         revenue_forecast_ajax, name='revenue_forecast_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/pickup-summary/',
         pickup_summary_ajax, name='pickup_summary_ajax'),
]