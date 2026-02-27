"""
Analytics views: Booking Analysis Dashboard and related AJAX endpoints.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View
from django.views.decorators.http import require_GET
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
import calendar

from pricing.models import (
    Organization, Property, Season, RoomType, Channel, Reservation,
)
from pricing.services import BookingAnalysisService

from .mixins import PropertyMixin

logger = logging.getLogger(__name__)


def _attach_demand_indices(prop, monthly_data, year):
    """Attach per-month demand index to monthly_data list in place."""
    try:
        from platform_data.services import MarketSignalService
        month_dates = [date(year, m['month'], 1) for m in monthly_data]
        indices = MarketSignalService.get_monthly_demand_indices(prop, month_dates)
        for m in monthly_data:
            key = date(year, m['month'], 1)
            idx = indices.get(key)
            if idx and idx['has_data']:
                m['demand_pct'] = idx['pct']
                m['demand_driver'] = idx['top_driver']
                m['demand_national_pct'] = idx['national_pct']
                m['demand_source'] = idx['source']
            else:
                m['demand_pct'] = None
                m['demand_driver'] = ''
                m['demand_national_pct'] = None
                m['demand_source'] = ''
    except Exception:
        for m in monthly_data:
            m['demand_pct'] = None
            m['demand_driver'] = ''
            m['demand_national_pct'] = None
            m['demand_source'] = ''


class BookingAnalysisDashboardView(PropertyMixin, TemplateView):
    """
    Booking Analysis Dashboard.
    
    Shows:
    - KPI cards (Revenue, Room Nights, ADR, Occupancy, Reservations)
    - Monthly revenue/occupancy charts
    - Channel mix
    - Meal plan mix
    - Room type performance
    """
    template_name = 'pricing/analytics/booking_analysis_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'analytics'
        prop = context['property']

        from pricing.services import BookingAnalysisService
        
        # Get year from query param
        year = self.request.GET.get('year')
        try:
            year = int(year) if year else date.today().year
        except ValueError:
            year = date.today().year
        
        # Check if property has reservation data
        has_data = Reservation.objects.filter(hotel=prop).exists()
        context['has_data'] = has_data
        context['year'] = year
        
        if not has_data:
            return context
        
        # Get dashboard data filtered by hotel
        # FIX: Use single = (keyword argument), not == (comparison)
        service = BookingAnalysisService(property=prop)
        dashboard_data = service.get_dashboard_data(year=year)
        chart_data = service.get_chart_data(year=year)
        
        # Pass data to template
        context['total_rooms'] = dashboard_data['total_rooms']
        context['kpis'] = dashboard_data['kpis']
        context['monthly_data'] = dashboard_data['monthly_data']
        context['channel_mix'] = dashboard_data['channel_mix']
        context['meal_plan_mix'] = dashboard_data['meal_plan_mix']
        context['room_type_performance'] = dashboard_data['room_type_performance']
        context['chart_data_json'] = json.dumps(chart_data)

        # Attach demand indices to monthly data
        _attach_demand_indices(prop, dashboard_data['monthly_data'], year)

        # Available years for selector
        years_with_data = Reservation.objects.filter(
            hotel=prop
        ).dates('arrival_date', 'year')
        context['available_years'] = [d.year for d in years_with_data]
        
        # Reservation count
        context['reservation_count'] = Reservation.objects.filter(
            hotel=prop,
            arrival_date__year=year,
            status__in=Reservation.ACTIVE_STATUSES
        ).count()

        # Source market trends
        source_market = service.get_source_market_trends(year=year)
        context['source_market_summary'] = source_market['summary']
        context['source_market_monthly_json'] = json.dumps(source_market['monthly'])

        return context


def booking_analysis_data_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to get booking analysis data.
    """
    from pricing.services import BookingAnalysisService
    
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        
        year = request.GET.get('year')
        try:
            year = int(year) if year else date.today().year
        except ValueError:
            year = date.today().year
        
        service = BookingAnalysisService(hotel=prop)
        dashboard_data = service.get_dashboard_data(year=year)
        chart_data = service.get_chart_data(year=year)

        _attach_demand_indices(prop, dashboard_data['monthly_data'], year)

        kpis = dashboard_data['kpis']
        
        return JsonResponse({
            'success': True,
            'year': year,
            'kpis': {
                'total_revenue': float(kpis['total_revenue']),
                'room_nights': kpis['room_nights'],
                'avg_adr': float(kpis['avg_adr']),
                'avg_occupancy': float(kpis['avg_occupancy']),
                'reservations': kpis['reservations'],
            },
            'chart_data': chart_data,
            'channel_mix': [
                {
                    'name': c['name'],
                    'bookings': c['bookings'],
                    'revenue': float(c['revenue']),
                    'percent': float(c['percent']),
                }
                for c in dashboard_data['channel_mix']
            ],
            'meal_plan_mix': [
                {
                    'name': m['name'],
                    'bookings': m['bookings'],
                    'revenue': float(m['revenue']),
                    'percent': float(m['percent']),
                }
                for m in dashboard_data['meal_plan_mix']
            ],
            'room_type_performance': [
                {
                    'name': r['name'],
                    'bookings': r['bookings'],
                    'revenue': float(r['revenue']),
                    'percent': float(r['percent']),
                }
                for r in dashboard_data['room_type_performance']
            ],
            'monthly_data': [
                {
                    'month': m['month'],
                    'month_name': m['month_name'],
                    'revenue': float(m['revenue']),
                    'room_nights': m['room_nights'],
                    'available': m['available'],
                    'occupancy': float(m['occupancy']),
                    'adr': float(m['adr']),
                    'demand_pct': m.get('demand_pct'),
                    'demand_driver': m.get('demand_driver', ''),
                    'demand_national_pct': m.get('demand_national_pct'),
                    'demand_source': m.get('demand_source', ''),
                }
                for m in dashboard_data['monthly_data']
            ],
        })
    
    except Exception as e:
        logger.exception("Booking analysis AJAX error")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)



class MonthDetailAPIView(PropertyMixin, View):
    """
    API endpoint for month detail modal.
    
    URL: /org/{org_code}/{prop_code}/api/month-detail/
    Params: month (1-12), year (YYYY)
    
    Returns JSON with:
    - summary: revenue, room_nights, occupancy, adr
    - velocity: booking velocity by month
    - room_distribution: room nights by room type
    - lead_time: lead time distribution
    - channel_distribution: bookings by channel
    - country_distribution: bookings by country
    """
    
    def get(self, request, *args, **kwargs):
        prop = self.get_property()
        
        month = int(request.GET.get('month', 1))
        year = int(request.GET.get('year', date.today().year))
        
        service = BookingAnalysisService(property=prop)
        data = service.get_month_detail(year, month)
        
        return JsonResponse(data)


class DemandIndexAjaxView(PropertyMixin, View):
    """
    AJAX endpoint: per-month demand index with full component breakdown.

    GET params:
        year: int (default current year)
        month: int (1-12, optional — if omitted returns all 12)
    """

    def get(self, request, *args, **kwargs):
        prop = self.get_property()
        year = int(request.GET.get('year', date.today().year))
        month = request.GET.get('month')

        if month:
            months = [date(year, int(month), 1)]
        else:
            months = [date(year, m, 1) for m in range(1, 13)]

        try:
            from platform_data.services import MarketSignalService
            indices = MarketSignalService.get_monthly_demand_indices(prop, months)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # Serialize (date keys -> string)
        serialized = {}
        for dt, idx in indices.items():
            key = dt.strftime('%Y-%m')
            serialized[key] = {
                'factor': idx['factor'],
                'pct': idx['pct'],
                'national_pct': idx['national_pct'],
                'top_driver': idx['top_driver'],
                'source': idx['source'],
                'has_data': idx['has_data'],
                'components': idx['components'],
            }

        return JsonResponse({'success': True, 'indices': serialized})


class BookingTrendsView(PropertyMixin, TemplateView):
    """
    30-day booking trends: pace, arrival mix, source markets, rooms.
    Answers "what happened recently and how does it compare?"
    """
    template_name = 'pricing/analytics/booking_trends.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'analytics'
        prop = context['property']

        has_data = Reservation.objects.filter(hotel=prop).exists()
        context['has_data'] = has_data

        if not has_data:
            return context

        # Period from query param (default 30)
        days = int(self.request.GET.get('days', 30))
        days = max(7, min(90, days))  # Clamp 7-90

        service = BookingAnalysisService(property=prop)
        trends = service.get_booking_trends(days=days)

        context['trends'] = trends
        context['days'] = days

        # JSON for charts
        context['daily_pace_json'] = json.dumps(trends['daily_pace'])
        context['arrival_mix_json'] = json.dumps(trends['arrival_mix'])
        context['country_mix_json'] = json.dumps(trends['country_mix'])
        context['room_mix_json'] = json.dumps(trends['room_mix'])
        context['channel_mix_json'] = json.dumps(trends['channel_mix'])

        return context


def booking_trends_data_ajax(request, org_code, prop_code):
    """AJAX: booking trends data for period switching."""
    from pricing.services import BookingAnalysisService

    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)

        days = int(request.GET.get('days', 30))
        days = max(7, min(90, days))

        service = BookingAnalysisService(property=prop)
        trends = service.get_booking_trends(days=days)

        return JsonResponse({'success': True, **trends})

    except Exception as e:
        logger.exception("Booking trends AJAX error")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

