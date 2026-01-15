"""
Pricing app URLs.
"""

from django.urls import path
from .views import (
    HomeView, PricingMatrixView, EnhancedPricingMatrixView, 
    AllSeasonsComparisonView, ADRAnalysisView, RevenueAnalysisView, update_room, update_season, parity_data_ajax)

app_name = 'pricing'

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('matrix/', PricingMatrixView.as_view(), name='matrix'),
    path('all-seasons/', AllSeasonsComparisonView.as_view(), name='all_seasons'),
    path('enhanced-matrix/', EnhancedPricingMatrixView.as_view(), name='enhanced_matrix'),
    path('adr-analysis/', ADRAnalysisView.as_view(), name='adr_analysis'),
    path('revenue-analysis/', RevenueAnalysisView.as_view(), name='revenue_analysis'),
    path('room/<int:room_id>/update/', update_room, name='update_room'),
    path('season/<int:season_id>/update/', update_season, name='update_season'),
    path('parity-data/', parity_data_ajax, name='parity_data_ajax'),


]
