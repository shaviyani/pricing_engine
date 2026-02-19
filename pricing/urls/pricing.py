"""Pricing URL patterns: Matrix, overrides, pricing AJAX."""

from django.urls import path
from pricing.views import (
    PricingMatrixView,
    PricingMatrixPDFView,
    PricingMatrixChannelView,
    RateLookupView,
    RateLookupAPIView,
    ItineraryQuoteAPIView,
    AgentRatesView,
    AgentRateCardView,
    DateRateOverrideCalendarView,
    parity_data_ajax,
    update_room,
    update_season,
    date_rate_detail_ajax,
    calendar_rates_ajax,
)

urlpatterns = [
    # Agent token-based rate card (public, no org/prop in URL)
    path('agent/<slug:token>/',
         AgentRateCardView.as_view(), name='agent_rate_card'),

    # Rate Lookup (operational - front desk, sales)
    path('org/<slug:org_code>/<slug:prop_code>/rates/',
         RateLookupView.as_view(), name='rate_lookup'),
    path('org/<slug:org_code>/<slug:prop_code>/api/rate-card/',
         RateLookupAPIView.as_view(), name='rate_card_api'),
    path('org/<slug:org_code>/<slug:prop_code>/api/itinerary-quote/',
         ItineraryQuoteAPIView.as_view(), name='itinerary_quote_api'),
    path('org/<slug:org_code>/<slug:prop_code>/agent-rates/',
         AgentRatesView.as_view(), name='agent_rates'),

    # Matrix views
    path('org/<slug:org_code>/<slug:prop_code>/matrix/',
         PricingMatrixView.as_view(), name='matrix'),
    path('org/<slug:org_code>/<slug:prop_code>/pricing/matrix/pdf/',
         PricingMatrixPDFView.as_view(), name='pricing_matrix_pdf'),
    path('org/<slug:org_code>/<slug:prop_code>/pricing/matrix/channel/',
         PricingMatrixChannelView.as_view(), name='pricing_matrix_channel'),

    # Override calendar
    path('org/<slug:org_code>/<slug:prop_code>/override-calendar/',
         DateRateOverrideCalendarView.as_view(), name='override_calendar'),

    # AJAX endpoints
    path('org/<slug:org_code>/<slug:prop_code>/api/parity-data/',
         parity_data_ajax, name='parity_data_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/room/<int:room_id>/update/',
         update_room, name='update_room'),
    path('org/<slug:org_code>/<slug:prop_code>/api/season/<int:season_id>/update/',
         update_season, name='update_season'),
    path('org/<slug:org_code>/<slug:prop_code>/api/date-rate-detail/',
         date_rate_detail_ajax, name='date_rate_detail_ajax'),
    path('org/<slug:org_code>/<slug:prop_code>/api/calendar-rates/',
         calendar_rates_ajax, name='calendar_rates_ajax'),
]