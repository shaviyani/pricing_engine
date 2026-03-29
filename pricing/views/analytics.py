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

from .mixins import PropertyMixin, AnalyticsAccessMixin

logger = logging.getLogger(__name__)


class AnalyticsBaseView(AnalyticsAccessMixin, PropertyMixin, TemplateView):
    """Shared base for all analytics views — sets nav and data check."""
    nav_sub = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'analytics'
        context['nav_sub'] = self.nav_sub
        prop = context['property']
        context['has_data'] = Reservation.objects.filter(hotel=prop).exists()
        return context


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


class BookingAnalysisDashboardView(AnalyticsBaseView):
    """
    Booking Analysis Dashboard.

    Tabs: Overview | Trends | Channel Mix | Room Types
    All tabs rendered client-side within a single template.
    """
    template_name = 'pricing/analytics/booking_analysis_dashboard.html'
    nav_sub = 'booking_analysis'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']

        from pricing.services import BookingAnalysisService

        active_tab = self.request.GET.get('tab', 'overview')
        context['active_tab'] = active_tab

        if not context['has_data']:
            return context

        service = BookingAnalysisService(property=prop)

        # ---- Overview data ----
        year = self.request.GET.get('year')
        try:
            year = int(year) if year else date.today().year
        except ValueError:
            year = date.today().year

        context['year'] = year

        dashboard_data = service.get_dashboard_data(year=year)
        chart_data = service.get_chart_data(year=year)

        context['total_rooms'] = dashboard_data['total_rooms']
        context['kpis'] = dashboard_data['kpis']
        context['monthly_data'] = dashboard_data['monthly_data']
        context['channel_mix'] = dashboard_data['channel_mix']
        context['meal_plan_mix'] = dashboard_data['meal_plan_mix']
        context['room_type_performance'] = dashboard_data['room_type_performance']
        context['chart_data_json'] = json.dumps(chart_data)

        _attach_demand_indices(prop, dashboard_data['monthly_data'], year)

        # Attach per-month cancel rate to monthly_data
        monthly_cancellations = dashboard_data.get('monthly_cancellations', [])
        for m_data, m_cancel in zip(
            dashboard_data['monthly_data'], monthly_cancellations
        ):
            cancelled = m_cancel.get('cancelled_count', 0)
            active = m_data.get('bookings', 0)
            total = active + cancelled
            m_data['cancel_rate'] = round(
                cancelled / total * 100, 1
            ) if total > 0 else 0
            m_data['cancelled_count'] = cancelled

        years_with_data = Reservation.objects.filter(
            hotel=prop
        ).dates('arrival_date', 'year')
        context['available_years'] = [d.year for d in years_with_data]

        context['reservation_count'] = Reservation.objects.filter(
            hotel=prop,
            arrival_date__year=year,
            status__in=Reservation.ACTIVE_STATUSES
        ).count()

        source_market = service.get_source_market_trends(year=year)
        context['source_market_summary'] = source_market['summary']
        context['source_market_monthly_json'] = json.dumps(source_market['monthly'])

        # ---- Trends data ----
        days = int(self.request.GET.get('days', 30))
        days = max(7, min(90, days))

        trends = service.get_booking_trends(days=days)

        context['trends'] = trends
        context['days'] = days
        context['daily_pace_json'] = json.dumps(trends['daily_pace'])
        context['arrival_mix_json'] = json.dumps(trends['arrival_mix'])
        context['country_mix_json'] = json.dumps(trends['country_mix'])
        context['room_mix_json'] = json.dumps(trends['room_mix'])
        context['channel_mix_json'] = json.dumps(trends['channel_mix'])

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

        # Attach per-month cancel rate
        monthly_cancellations = dashboard_data.get('monthly_cancellations', [])
        for m_data, m_cancel in zip(
            dashboard_data['monthly_data'], monthly_cancellations
        ):
            cancelled = m_cancel.get('cancelled_count', 0)
            active = m_data.get('bookings', 0)
            total = active + cancelled
            m_data['cancel_rate'] = round(
                cancelled / total * 100, 1
            ) if total > 0 else 0

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
                    'cancel_rate': m.get('cancel_rate', 0),
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


class BookingTrendsView(AnalyticsBaseView):
    """
    30-day booking trends: pace, arrival mix, source markets, rooms.
    Answers "what happened recently and how does it compare?"
    """
    template_name = 'pricing/analytics/booking_trends.html'
    nav_sub = 'booking_trends'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']

        if not context['has_data']:
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


class BookingOriginMatrixView(AnalyticsBaseView):
    """
    Booking Origin Matrix: heatmap of booking-month vs arrival-month room nights.
    Shows when bookings were made and what stay months they are for.
    """
    template_name = 'pricing/analytics/booking_origin_matrix.html'
    nav_sub = 'booking_heatmap'

    def get_context_data(self, **kwargs):
        from django.db.models.functions import TruncMonth
        context = super().get_context_data(**kwargs)
        prop = context['property']

        if not context['has_data']:
            return context

        # Query: group active reservations by booking month & arrival month
        qs = Reservation.objects.filter(
            hotel=prop,
            status__in=Reservation.ACTIVE_STATUSES,
        ).annotate(
            booking_month=TruncMonth('booking_date'),
            arrival_month=TruncMonth('arrival_date'),
        ).values('booking_month', 'arrival_month').annotate(
            room_nights=Sum('nights'),
        ).order_by('booking_month', 'arrival_month')

        # Build sorted unique month lists and matrix dict
        booking_months_set = set()
        arrival_months_set = set()
        matrix = {}
        for row in qs:
            bm = row['booking_month'].strftime('%Y-%m')
            am = row['arrival_month'].strftime('%Y-%m')
            rn = row['room_nights'] or 0
            booking_months_set.add(bm)
            arrival_months_set.add(am)
            matrix.setdefault(bm, {})[am] = rn

        booking_months = sorted(booking_months_set)
        arrival_months = sorted(arrival_months_set)

        # Booking totals per booking month
        booking_totals = {}
        for bm in booking_months:
            booking_totals[bm] = sum(matrix.get(bm, {}).values())

        context['matrix_json'] = json.dumps({
            'booking_months': booking_months,
            'arrival_months': arrival_months,
            'matrix': matrix,
            'booking_totals': booking_totals,
        })

        return context


@require_GET
def booking_heatmap_ajax(request, org_code, prop_code):
    """
    AJAX: compact booking origin heatmap for dashboard.
    Returns last 3 booking months x future arrival months.
    """
    from django.db.models.functions import TruncMonth

    org = get_object_or_404(Organization, code=org_code, is_active=True)
    prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
    today = date.today()

    # Last 6 booking months
    booking_start = (today.replace(day=1) - timedelta(days=150)).replace(day=1)

    qs = Reservation.objects.filter(
        hotel=prop,
        status__in=Reservation.ACTIVE_STATUSES,
        booking_date__gte=booking_start,
    ).annotate(
        booking_month=TruncMonth('booking_date'),
        arrival_month=TruncMonth('arrival_date'),
    ).values('booking_month', 'arrival_month').annotate(
        room_nights=Sum('nights'),
    ).order_by('booking_month', 'arrival_month')

    matrix = {}
    booking_months_set = set()
    arrival_months_set = set()

    for row in qs:
        bm = row['booking_month'].strftime('%Y-%m')
        am = row['arrival_month'].strftime('%Y-%m')
        rn = row['room_nights'] or 0
        booking_months_set.add(bm)
        arrival_months_set.add(am)
        matrix.setdefault(bm, {})[am] = rn

    booking_months = sorted(booking_months_set)[-6:]
    arrival_months = sorted(am for am in arrival_months_set
                           if am >= today.strftime('%Y-%m'))[:8]

    booking_totals = {}
    for bm in booking_months:
        booking_totals[bm] = sum(
            matrix.get(bm, {}).get(am, 0) for am in arrival_months
        )

    arrival_totals = {}
    for am in arrival_months:
        arrival_totals[am] = sum(
            matrix.get(bm, {}).get(am, 0) for bm in booking_months
        )

    max_rn = max(
        (matrix.get(bm, {}).get(am, 0) for bm in booking_months for am in arrival_months),
        default=1
    )

    current_month = today.strftime('%Y-%m')

    return JsonResponse({
        'success': True,
        'booking_months': booking_months,
        'arrival_months': arrival_months,
        'matrix': matrix,
        'booking_totals': booking_totals,
        'arrival_totals': arrival_totals,
        'max_rn': max_rn,
        'current_month': current_month,
    })


@require_GET
def arrival_forecast_ajax(request, org_code, prop_code):
    """
    AJAX: seasonality distribution forecast for next 12 months.
    Hotel line: month's room nights as % of annual total (recency-weighted).
    National line: month's arrivals as % of annual total (recency-weighted).
    """
    from platform_data.models import MarketArrivalData, MarketKeyIndicator
    from dateutil.relativedelta import relativedelta
    from django.db.models import Sum

    org = get_object_or_404(Organization, code=org_code, is_active=True)
    prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
    today = date.today()
    country_code = getattr(prop, 'country_code', 'MV') or 'MV'

    # --- Hotel seasonality: room nights per month as % of year ---
    # Gather all complete years of reservation data, recency-weighted
    hotel_month_share = {}
    years_with_data = (
        Reservation.objects.filter(
            hotel=prop, status__in=Reservation.ACTIVE_STATUSES
        ).values_list('arrival_date__year', flat=True)
        .distinct().order_by('-arrival_date__year')
    )

    year_totals = {}  # {year: {month: room_nights}}
    for yr in years_with_data:
        monthly = (
            Reservation.objects.filter(
                hotel=prop, status__in=Reservation.ACTIVE_STATUSES,
                arrival_date__year=yr,
            ).values('arrival_date__month')
            .annotate(rn=Sum('nights'))
        )
        by_month = {row['arrival_date__month']: row['rn'] or 0 for row in monthly}
        annual_total = sum(by_month.values())
        # Only use years with at least 6 months of data for meaningful distribution
        if annual_total > 0 and len(by_month) >= 6:
            year_totals[yr] = {'months': by_month, 'total': annual_total}

    # Recency-weighted share per calendar month
    for m in range(1, 13):
        w_sum = 0.0
        w_total = 0.0
        for idx, yr in enumerate(sorted(year_totals.keys(), reverse=True)):
            yt = year_totals[yr]
            share = yt['months'].get(m, 0) / yt['total'] * 100
            w = 0.5 ** idx
            w_sum += share * w
            w_total += w
        hotel_month_share[m] = round(w_sum / w_total, 1) if w_total > 0 else 0

    # --- National seasonality: arrivals per month as % of year ---
    national_month_share = {}
    ki_years = (
        MarketKeyIndicator.objects.filter(country_code=country_code)
        .values_list('report_period__year', flat=True)
        .distinct().order_by('-report_period__year')
    )

    nat_year_totals = {}
    for yr in ki_years:
        records = MarketKeyIndicator.objects.filter(
            country_code=country_code, report_period__year=yr
        ).values('report_period__month').annotate(total=Sum('total_arrivals'))
        by_month = {row['report_period__month']: row['total'] or 0 for row in records}
        annual_total = sum(by_month.values())
        if annual_total > 0 and len(by_month) >= 6:
            nat_year_totals[yr] = {'months': by_month, 'total': annual_total}

    for m in range(1, 13):
        w_sum = 0.0
        w_total = 0.0
        for idx, yr in enumerate(sorted(nat_year_totals.keys(), reverse=True)):
            yt = nat_year_totals[yr]
            share = yt['months'].get(m, 0) / yt['total'] * 100
            w = 0.5 ** idx
            w_sum += share * w
            w_total += w
        national_month_share[m] = round(w_sum / w_total, 1) if w_total > 0 else 0

    # --- Hotel OTB occupancy per month ---
    total_rooms = RoomType.objects.filter(hotel=prop).aggregate(
        t=Sum('number_of_rooms'))['t'] or 0

    # Build results for next 12 months
    results = []
    for i in range(12):
        m = today.replace(day=1) + relativedelta(months=i)
        # OTB occupancy
        occ = 0
        if total_rooms > 0:
            _, days = calendar.monthrange(m.year, m.month)
            available = total_rooms * days
            rn = Reservation.objects.filter(
                hotel=prop,
                arrival_date__year=m.year, arrival_date__month=m.month,
                status__in=Reservation.ACTIVE_STATUSES,
            ).aggregate(t=Sum('nights'))['t'] or 0
            occ = round(rn / available * 100, 1)

        results.append({
            'month': m.strftime('%b %y'),
            'month_iso': m.strftime('%Y-%m'),
            'hotel_pct': hotel_month_share.get(m.month, 0),
            'national_pct': national_month_share.get(m.month, 0),
            'occupancy': occ,
        })

    return JsonResponse({
        'success': True,
        'months': results,
        'hotel_years': len(year_totals),
        'national_years': len(nat_year_totals),
    })


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


class CancellationDashboardView(AnalyticsBaseView):
    """Cancellation intelligence dashboard."""
    template_name = 'pricing/analytics/cancellation_dashboard.html'
    nav_sub = 'cancellations'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']

        from pricing.services import CancellationAnalysisService

        today = date.today()
        year = int(self.request.GET.get('year', today.year))
        context['selected_year'] = year
        context['available_years'] = list(range(today.year - 2, today.year + 1))

        service = CancellationAnalysisService(property=prop)

        cancel_rates = service.get_cancel_rates(year=year)
        timing_curve = service.get_cancellation_timing_curve(year=year)

        context['cancel_rates'] = cancel_rates
        context['timing_curve'] = timing_curve
        context['revenue_impact'] = service.get_revenue_impact(year=year)
        context['rebooking'] = service.get_rebooking_analysis()

        # JSON for Chart.js
        context['timing_curve_json'] = json.dumps(timing_curve)
        context['monthly_rates_json'] = json.dumps(cancel_rates.get('by_month', []))

        # Forecast next 3 months
        forecasts = []
        for i in range(3):
            m = today.month + i + 1
            y = today.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            forecast = service.forecast_cancellations(m, y)
            forecast['month_name'] = calendar.month_name[m]
            forecast['year'] = y
            forecasts.append(forecast)
        context['cancel_forecasts'] = forecasts

        return context

