"""Analytics URL patterns: Booking analysis dashboard and AJAX."""

from django.urls import path
from pricing.views import (
    BookingAnalysisDashboardView,
    booking_analysis_data_ajax,
    MonthDetailAPIView,
    DemandIndexAjaxView,
    BookingTrendsView,
    booking_trends_data_ajax,
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
    path('org/<slug:org_code>/<slug:prop_code>/booking-trends/',
         BookingTrendsView.as_view(), name='booking_trends'),
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-trends/',
         booking_trends_data_ajax, name='booking_trends_ajax'),
]