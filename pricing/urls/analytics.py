"""Analytics URL patterns: Booking analysis dashboard and AJAX."""

from django.urls import path
from pricing.views import (
    BookingAnalysisDashboardView,
    booking_analysis_data_ajax,
    MonthDetailAPIView,
)

urlpatterns = [
    path('org/<slug:org_code>/<slug:prop_code>/booking-analysis/',
         BookingAnalysisDashboardView.as_view(), name='booking_analysis_dashboard'),
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-analysis/',
         booking_analysis_data_ajax, name='booking_analysis_data_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/month-detail/',
         MonthDetailAPIView.as_view(), name='month_detail_api'),
]