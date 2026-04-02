"""Analytics URL patterns: Booking analysis dashboard and AJAX."""

from django.urls import path
from pricing.views import (
    BookingAnalysisDashboardView,
    booking_analysis_data_ajax,
    MonthDetailAPIView,
    DemandIndexAjaxView,
    # BookingTrendsView,  # kept in views but URL removed (merged into dashboard)
    booking_trends_data_ajax,
    BookingOriginMatrixView,
    CancellationDashboardView,
    booking_heatmap_ajax,
    arrival_forecast_ajax,
    DestinationReportView,
    destination_rankings_ajax,
    destination_seasonal_ajax,
    destination_shifts_ajax,
    destination_momentum_ajax,
    MarketIntelligenceView,
    market_intel_cancel_cross_ajax,
    market_intel_lead_times_ajax,
    market_intel_forecast_ajax,
    market_intel_guidance_ajax,
)

urlpatterns = [
    path('org/<slug:org_code>/<slug:prop_code>/booking-analysis/',
         BookingAnalysisDashboardView.as_view(), name='booking_analysis_dashboard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-analysis/',
         booking_analysis_data_ajax, name='booking_analysis_data_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/month-detail/',
         MonthDetailAPIView.as_view(), name='month_detail_api'),
    path('org/<slug:org_code>/<slug:prop_code>/api/demand-index/',
         DemandIndexAjaxView.as_view(), name='demand_index_api'),
    # booking-trends URL removed — merged into booking_analysis_dashboard (tabs)
    # path('org/<slug:org_code>/<slug:prop_code>/booking-trends/',
    #      BookingTrendsView.as_view(), name='booking_trends'),
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-trends/',
         booking_trends_data_ajax, name='booking_trends_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/booking-origin/',
         BookingOriginMatrixView.as_view(), name='booking_origin_matrix'),
    path('org/<slug:org_code>/<slug:prop_code>/analytics/cancellations/',
         CancellationDashboardView.as_view(), name='cancellation_dashboard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-heatmap/',
         booking_heatmap_ajax, name='booking_heatmap_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/arrival-forecast/',
         arrival_forecast_ajax, name='arrival_forecast_ajax'),

    # Destination Report
    path('org/<slug:org_code>/<slug:prop_code>/analytics/destination-report/',
         DestinationReportView.as_view(), name='destination_report'),
    path('org/<slug:org_code>/<slug:prop_code>/api/destination/rankings/',
         destination_rankings_ajax, name='destination_rankings_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/destination/seasonal/',
         destination_seasonal_ajax, name='destination_seasonal_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/destination/shifts/',
         destination_shifts_ajax, name='destination_shifts_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/destination/momentum/',
         destination_momentum_ajax, name='destination_momentum_ajax'),

    # Market Intelligence
    path('org/<slug:org_code>/<slug:prop_code>/analytics/market-intelligence/',
         MarketIntelligenceView.as_view(), name='market_intelligence'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-intel/cancel-cross/',
         market_intel_cancel_cross_ajax, name='market_intel_cancel_cross'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-intel/lead-times/',
         market_intel_lead_times_ajax, name='market_intel_lead_times'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-intel/forecast/',
         market_intel_forecast_ajax, name='market_intel_forecast'),
    path('org/<slug:org_code>/<slug:prop_code>/api/market-intel/guidance/',
         market_intel_guidance_ajax, name='market_intel_guidance'),
]