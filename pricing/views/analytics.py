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
        
        # Available years for selector
        years_with_data = Reservation.objects.filter(
            hotel=prop
        ).dates('arrival_date', 'year')
        context['available_years'] = [d.year for d in years_with_data]
        
        # Reservation count
        context['reservation_count'] = Reservation.objects.filter(
            hotel=prop,
            arrival_date__year=year,
            status__in=['confirmed', 'checked_in', 'checked_out']
        ).count()
        
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


"""
Date Rate Override Calendar View
================================

Add this view to your pricing/views.py
"""

