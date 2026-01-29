"""
Pricing app URLs - Multi-Property Structure

URL Hierarchy:
    /                                           → Root redirect
    /org/                                       → Organization selector
    /org/<org_code>/                            → Organization dashboard
    /org/<org_code>/properties/                 → Property list
    /org/<org_code>/<prop_code>/                → Property dashboard
    /org/<org_code>/<prop_code>/matrix/         → Pricing matrix
    /org/<org_code>/<prop_code>/booking-analysis/
    /org/<org_code>/<prop_code>/pickup/
    /org/<org_code>/<prop_code>/api/...         → AJAX endpoints
"""

from django.urls import path
from .views import (
    # Root & Selector
    RootRedirectView,
    OrganizationSelectorView,
    
    # Organization level
    OrganizationDashboardView,
    PropertyListView,
    
    # Property level
    PropertyDashboardView,
    PricingMatrixView,
    PricingMatrixPDFView,
    PricingMatrixChannelView,
    BookingAnalysisDashboardView,
    PickupDashboardView,
    MonthDetailAPIView,
    
    # AJAX endpoints
    parity_data_ajax,
    revenue_forecast_ajax,
    booking_analysis_data_ajax,
    pickup_summary_ajax,
    update_room,
    update_season,
)

app_name = 'pricing'

urlpatterns = [
    # ==========================================================================
    # ROOT & ORGANIZATION SELECTOR
    # ==========================================================================
    path('', RootRedirectView.as_view(), name='root'),
    path('org/', OrganizationSelectorView.as_view(), name='org_selector'),
    
    # ==========================================================================
    # ORGANIZATION LEVEL
    # ==========================================================================
    path('org/<slug:org_code>/', 
         OrganizationDashboardView.as_view(), 
         name='org_dashboard'),
    
    path('org/<slug:org_code>/properties/', 
         PropertyListView.as_view(), 
         name='property_list'),
    
    # ==========================================================================
    # PROPERTY LEVEL - MAIN VIEWS
    # ==========================================================================
    path('org/<slug:org_code>/<slug:prop_code>/', 
         PropertyDashboardView.as_view(), 
         name='property_dashboard'),
    
    path('org/<slug:org_code>/<slug:prop_code>/matrix/', 
         PricingMatrixView.as_view(), 
         name='matrix'),
    
    path(
        '<str:org_code>/<str:prop_code>/pricing/matrix/pdf/',
        PricingMatrixPDFView.as_view(),
        name='pricing_matrix_pdf'
    ),
    
    path(
   '<str:org_code>/<str:prop_code>/pricing/matrix/channel/',
     PricingMatrixChannelView.as_view(),
     name='pricing_matrix_channel' ),
     
    path('org/<slug:org_code>/<slug:prop_code>/booking-analysis/', 
         BookingAnalysisDashboardView.as_view(), 
         name='booking_analysis_dashboard'),
    
    path('org/<slug:org_code>/<slug:prop_code>/pickup/', 
         PickupDashboardView.as_view(), 
         name='pickup_dashboard'),
    
    # ==========================================================================
    # PROPERTY LEVEL - AJAX ENDPOINTS
    # ==========================================================================
    path('org/<slug:org_code>/<slug:prop_code>/api/parity-data/', 
         parity_data_ajax, 
         name='parity_data_ajax'),
    
    path('org/<slug:org_code>/<slug:prop_code>/api/revenue-forecast/', 
         revenue_forecast_ajax, 
         name='revenue_forecast_ajax'),
    
    path('org/<slug:org_code>/<slug:prop_code>/api/booking-analysis/', 
         booking_analysis_data_ajax, 
         name='booking_analysis_data_ajax'),
    
    path('org/<slug:org_code>/<slug:prop_code>/api/pickup-summary/', 
         pickup_summary_ajax, 
         name='pickup_summary_ajax'),
    
    path('org/<slug:org_code>/<slug:prop_code>/api/room/<int:room_id>/update/', 
         update_room, 
         name='update_room'),
    
    path('org/<slug:org_code>/<slug:prop_code>/api/season/<int:season_id>/update/', 
         update_season, 
         name='update_season'),
    
    path(
    '<str:org_code>/<str:prop_code>/api/month-detail/',
    MonthDetailAPIView.as_view(),
    name='month_detail_api'
),
]


# =============================================================================
# LEGACY URL REDIRECTS (Optional - remove after migration)
# =============================================================================
# If you have old bookmarks or links, you can add redirects here:
#
# from django.views.generic import RedirectView
# 
# urlpatterns += [
#     path('matrix/', RedirectView.as_view(pattern_name='pricing:root'), name='legacy_matrix'),
#     path('booking-analysis/', RedirectView.as_view(pattern_name='pricing:root'), name='legacy_booking'),
# ]

