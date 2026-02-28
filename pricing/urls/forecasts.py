"""Forecast URL patterns: Pickup dashboard, revenue forecast, AJAX."""

from django.urls import path
from pricing.views import (
    PickupDashboardView,
    revenue_forecast_ajax,
    pickup_summary_ajax,
    occupancy_calendar_ajax,
    DemandForecastView,
    generate_demand_forecast_ajax,
)

urlpatterns = [
    path('org/<slug:org_code>/<slug:prop_code>/pickup/',
         PickupDashboardView.as_view(), name='pickup_dashboard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/revenue-forecast/',
         revenue_forecast_ajax, name='revenue_forecast_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/pickup-summary/',
         pickup_summary_ajax, name='pickup_summary_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/occupancy-calendar/',
         occupancy_calendar_ajax, name='occupancy_calendar_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/demand-forecast/',
         DemandForecastView.as_view(), name='demand_forecast'),
    path('org/<slug:org_code>/<slug:prop_code>/api/demand-forecast/',
         generate_demand_forecast_ajax, name='demand_forecast_ajax'),
]