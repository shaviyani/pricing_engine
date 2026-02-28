"""
Forecast views: Pickup Dashboard, Revenue Forecast, and related AJAX endpoints.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.views.generic import TemplateView, View
from django.views.decorators.http import require_GET
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import calendar

from pricing.models import (
    Organization, Property, Season, Channel,
    Reservation, DailyPickupSnapshot, MonthlyPickupSnapshot,
    OccupancyForecast,
)
from pricing.services import RevenueForecastService, PickupAnalysisService, PricingService
from pricing.services.period_forecast_service import PeriodForecastService

from .mixins import PropertyMixin

logger = logging.getLogger(__name__)

class PickupDashboardView(PropertyMixin, TemplateView):
    """
    Main pickup analysis dashboard.
    
    Shows:
    - KPI cards (velocity, OTB, lead time)
    - Forecast overview table for next 6 months
    - Booking pace chart
    - Lead time distribution
    - Channel breakdown
    - Daily velocity chart
    - Pickup curves by season
    """
    template_name = 'pricing/forecasts/pickup_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'forecasts'
        prop = context['property']

        from pricing.services import PickupAnalysisService

        # Pass property to service
        service = PickupAnalysisService(property=prop)
        today = date.today()
        
        # Check for RESERVATION data (not MonthlyPickupSnapshot)
        has_data = Reservation.objects.filter(hotel=prop).exists()
        context['has_data'] = has_data
        
        if not has_data:
            return context
        
        # =====================================================================
        # KPI CARDS
        # =====================================================================
        
        # Bookings this week (created in last 7 days for future arrivals)
        week_ago = today - timedelta(days=7)
        weekly_bookings = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=week_ago,
            booking_date__lte=today,
            arrival_date__gte=today,
            status__in=Reservation.ACTIVE_STATUSES
        )
        
        weekly_stats = weekly_bookings.aggregate(
            count=Count('id'),
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
        )
        
        context['weekly_pickup'] = weekly_stats['room_nights'] or 0
        context['weekly_bookings'] = weekly_stats['count'] or 0
        context['weekly_revenue'] = float(weekly_stats['revenue'] or 0)
        
        # Total OTB for next 3 months
        three_months = today + timedelta(days=90)
        future_reservations = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            arrival_date__lte=three_months,
            status__in=Reservation.ACTIVE_STATUSES
        )
        
        otb_stats = future_reservations.aggregate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        )
        
        context['total_otb_nights'] = otb_stats['room_nights'] or 0
        context['total_otb_revenue'] = float(otb_stats['revenue'] or 0)
        context['total_otb_bookings'] = otb_stats['count'] or 0
        
        # Velocity (last 14 days)
        next_month = (today + timedelta(days=30)).replace(day=1)
        velocity_data = service.calculate_booking_velocity(next_month)
        context['velocity'] = velocity_data
        
        # Lead time analysis
        lead_time_data = service.analyze_lead_time_distribution()
        context['avg_lead_time'] = lead_time_data['avg_lead_time']
        context['lead_time_data'] = lead_time_data
        
        # =====================================================================
        # FORECAST SUMMARY (for table)
        # =====================================================================
        forecast_summary = service.get_forecast_summary(months_ahead=6)
        context['forecast_summary'] = forecast_summary
        
        # =====================================================================
        # BOOKING PACE DATA (cumulative bookings over time)
        # =====================================================================
        booking_pace = self._get_booking_pace_data(prop, today)
        context['booking_pace'] = booking_pace
        
        # =====================================================================
        # DAILY VELOCITY DATA (daily new bookings)
        # =====================================================================
        daily_velocity = self._get_daily_velocity_data(prop, today)
        context['daily_velocity'] = daily_velocity
        
        # =====================================================================
        # CHANNEL BREAKDOWN
        # =====================================================================
        channel_data = self._get_channel_breakdown(prop, today)
        context['channel_data'] = channel_data
        
        # =====================================================================
        # PICKUP CURVES (from real reservation data)
        # =====================================================================
        pickup_result = self._calculate_real_pickup_curves(prop, today)
        curves = pickup_result['curves']
        context['pickup_curves'] = curves

        # Build a combined list for easy template iteration
        season_colors = {'peak': '#ef4444', 'shoulder': '#3b82f6', 'low': '#9ca3af'}
        pickup_season_details = []
        for st in ['peak', 'shoulder', 'low']:
            if st in pickup_result['insights']:
                pickup_season_details.append({
                    'type': st,
                    'color': season_colors.get(st, '#6b7280'),
                    'half_booked_days': pickup_result['insights'][st]['half_booked_days'],
                    'description': pickup_result['insights'][st]['description'],
                    'quality': pickup_result['data_quality'].get(st, 'insufficient'),
                    'count': pickup_result['season_count'].get(st, 0),
                })
        context['pickup_season_details'] = pickup_season_details
        
        # =====================================================================
        # CHART DATA AS JSON (for JavaScript)
        # =====================================================================
        chart_data = {
    'bookingPace': {
        'dates': booking_pace['dates'],
        'cum_nights': booking_pace['cum_nights'],       # was cumNights
        'cum_revenue': booking_pace['cum_revenue'],     # was cumRevenue
        'stly_nights': booking_pace['stly_nights'],     # was stlyNights
    },
    'leadTime': {
        'labels': [b['label'] for b in lead_time_data['buckets']],
        'counts': [b['count'] for b in lead_time_data['buckets']],
        'percents': [b['percent'] for b in lead_time_data['buckets']],
    },
    'channels': {
        'labels': [c['name'] for c in channel_data],
        'data': [c['percent'] for c in channel_data],
    },
    'dailyVelocity': {                                  # was 'velocity'
        'dates': daily_velocity['dates'],
        'bookings': daily_velocity['daily_count'],      # was dailyCount
        'revenue': daily_velocity['daily_revenue'],     # was dailyRevenue
    },
    'pickupCurves': {
        'days_out': [90, 75, 60, 45, 30, 15, 7, 0],
        'series': {
            st: [d['percent'] for d in points[-8:]]
            for st, points in curves.items()
        },
    },
}
        context['chart_data_json'] = json.dumps(chart_data)
        
        # Last updated timestamp
        context['last_updated'] = today.strftime('%b %d, %Y')
        
        return context
    
    def _get_booking_pace_data(self, prop, today):
        """
        Get cumulative booking pace data for the chart.
        
        Shows how bookings accumulated over time for future arrivals.
        """
        from dateutil.relativedelta import relativedelta
        
        # Look at bookings made in the last 30 days
        lookback_days = 30
        start_date = today - timedelta(days=lookback_days)
        
        # Future arrival window (next 3 months)
        arrival_start = today
        arrival_end = today + timedelta(days=90)
        
        # Get bookings by booking_date
        bookings = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=start_date,
            booking_date__lte=today,
            arrival_date__gte=arrival_start,
            arrival_date__lte=arrival_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).values('booking_date').annotate(
            nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        ).order_by('booking_date')
        
        # Build cumulative data
        dates = []
        cum_nights = []
        cum_revenue = []
        
        running_nights = 0
        running_revenue = Decimal('0.00')
        
        for booking in bookings:
            if booking['booking_date']:
                dates.append(booking['booking_date'].strftime('%b %d'))
                running_nights += booking['nights'] or 0
                running_revenue += booking['revenue'] or Decimal('0.00')
                cum_nights.append(running_nights)
                cum_revenue.append(float(running_revenue))
        
        # Get STLY (Same Time Last Year) for comparison
        stly_start = start_date - relativedelta(years=1)
        stly_end = today - relativedelta(years=1)
        stly_arrival_start = arrival_start - relativedelta(years=1)
        stly_arrival_end = arrival_end - relativedelta(years=1)
        
        stly_bookings = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=stly_start,
            booking_date__lte=stly_end,
            arrival_date__gte=stly_arrival_start,
            arrival_date__lte=stly_arrival_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).values('booking_date').annotate(
            nights=Sum('nights'),
        ).order_by('booking_date')
        
        stly_nights = []
        stly_running = 0
        for booking in stly_bookings:
            stly_running += booking['nights'] or 0
            stly_nights.append(stly_running)
        
        # Pad STLY to match current length
        while len(stly_nights) < len(dates):
            stly_nights.append(stly_nights[-1] if stly_nights else 0)
        
        return {
            'dates': dates,
            'cum_nights': cum_nights,
            'cum_revenue': cum_revenue,
            'stly_nights': stly_nights[:len(dates)],
        }
    
    def _get_daily_velocity_data(self, prop, today):
        """
        Get daily booking velocity data for the chart.
        
        Shows new bookings per day.
        """
        lookback_days = 14
        start_date = today - timedelta(days=lookback_days)
        
        # Get daily bookings
        daily_bookings = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=start_date,
            booking_date__lte=today,
            status__in=Reservation.ACTIVE_STATUSES
        ).values('booking_date').annotate(
            count=Count('id'),
            revenue=Sum('total_amount'),
        ).order_by('booking_date')
        
        dates = []
        daily_count = []
        daily_revenue = []
        
        for booking in daily_bookings:
            if booking['booking_date']:
                dates.append(booking['booking_date'].strftime('%b %d'))
                daily_count.append(booking['count'] or 0)
                daily_revenue.append(float(booking['revenue'] or 0))
        
        return {
            'dates': dates,
            'daily_count': daily_count,
            'daily_revenue': daily_revenue,
        }
    
    def _get_channel_breakdown(self, prop, today):
        """
        Get channel breakdown for future bookings.
        """
        # Future arrivals
        future_reservations = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            status__in=Reservation.ACTIVE_STATUSES
        )
        
        channel_stats = future_reservations.values('channel__name').annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        ).order_by('-room_nights')
        
        total_nights = sum(s['room_nights'] or 0 for s in channel_stats)
        
        result = []
        for stat in channel_stats:
            name = stat['channel__name'] or 'Unknown'
            room_nights = stat['room_nights'] or 0
            percent = round(room_nights / total_nights * 100, 1) if total_nights > 0 else 0
            
            result.append({
                'name': name,
                'room_nights': room_nights,
                'revenue': float(stat['revenue'] or 0),
                'bookings': stat['count'] or 0,
                'percent': percent,
            })
        
        return result

    def _calculate_real_pickup_curves(self, prop, today):
        """
        Calculate pickup curves from real reservation data.

        For each season_type that has past completed seasons, calculates
        what percentage of total room nights were booked at each checkpoint
        (90, 75, 60, 45, 30, 15, 7, 0 days before season start).

        Returns dict with:
            curves: {season_type: [{'days_out': N, 'percent': P}, ...]}
            insights: {season_type: {'half_booked_days': N, 'description': str}}
            data_quality: {season_type: 'good'|'limited'|'insufficient'}
            season_count: {season_type: N}
        """
        from pricing.models import Season, Reservation

        checkpoints = [90, 75, 60, 45, 30, 15, 7, 0]

        # Get all past completed seasons for this property
        past_seasons = Season.objects.filter(
            hotel=prop,
            end_date__lt=today,
        ).order_by('start_date')

        # Group by season_type
        seasons_by_type = {}
        for season in past_seasons:
            st = season.season_type
            if st not in seasons_by_type:
                seasons_by_type[st] = []
            seasons_by_type[st].append(season)

        curves = {}
        insights = {}
        data_quality = {}
        season_count = {}

        for season_type, seasons in seasons_by_type.items():
            season_count[season_type] = len(seasons)

            # Assess data quality
            if len(seasons) >= 3:
                data_quality[season_type] = 'good'
            elif len(seasons) >= 1:
                data_quality[season_type] = 'limited'
            else:
                data_quality[season_type] = 'insufficient'
                continue

            # For each season, calculate pickup percentages at each checkpoint
            all_percentages = {cp: [] for cp in checkpoints}

            for season in seasons:
                # Total room nights for arrivals within this season
                total_rn = Reservation.objects.filter(
                    hotel=prop,
                    arrival_date__gte=season.start_date,
                    arrival_date__lte=season.end_date,
                    status__in=Reservation.ACTIVE_STATUSES,
                ).aggregate(total=Sum('nights'))['total'] or 0

                if total_rn == 0:
                    continue

                for cp in checkpoints:
                    cutoff_date = season.start_date - timedelta(days=cp)
                    booked_rn = Reservation.objects.filter(
                        hotel=prop,
                        arrival_date__gte=season.start_date,
                        arrival_date__lte=season.end_date,
                        booking_date__lte=cutoff_date,
                        status__in=Reservation.ACTIVE_STATUSES,
                    ).aggregate(total=Sum('nights'))['total'] or 0

                    pct = round(booked_rn / total_rn * 100, 1)
                    all_percentages[cp].append(pct)

            # Average across seasons
            curve_points = []
            for cp in checkpoints:
                vals = all_percentages[cp]
                if vals:
                    avg_pct = round(sum(vals) / len(vals), 1)
                else:
                    avg_pct = 0.0
                curve_points.append({'days_out': cp, 'percent': avg_pct})

            curves[season_type] = curve_points

            # Calculate "50% booked by N days" via interpolation
            half_booked_days = None
            for i in range(len(curve_points) - 1):
                p1 = curve_points[i]
                p2 = curve_points[i + 1]
                if p1['percent'] <= 50 <= p2['percent']:
                    # Linear interpolation
                    if p2['percent'] != p1['percent']:
                        ratio = (50 - p1['percent']) / (p2['percent'] - p1['percent'])
                        days = p1['days_out'] - ratio * (p1['days_out'] - p2['days_out'])
                        half_booked_days = round(days)
                    else:
                        half_booked_days = p1['days_out']
                    break

            if half_booked_days is None:
                # Check if already above 50% at 90 days
                if curve_points and curve_points[0]['percent'] >= 50:
                    half_booked_days = 90
                    description = 'Very early bookers'
                else:
                    half_booked_days = 0
                    description = 'Last-minute heavy'
            else:
                if half_booked_days >= 60:
                    description = 'Fast early pickup'
                elif half_booked_days >= 30:
                    description = 'Steady buildup'
                else:
                    description = 'Later decisions'

            insights[season_type] = {
                'half_booked_days': half_booked_days,
                'description': description,
            }

        return {
            'curves': curves,
            'insights': insights,
            'data_quality': data_quality,
            'season_count': season_count,
        }


@require_GET

def pickup_dashboard_data_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to refresh pickup dashboard data.
    
    Returns JSON with all dashboard metrics.
    """
    from pricing.services import PickupAnalysisService
    from pricing.models import Organization, Property
    
    try:
        org = Organization.objects.get(code=org_code)
        prop = Property.objects.get(organization=org, code=prop_code)
    except (Organization.DoesNotExist, Property.DoesNotExist):
        return JsonResponse({'success': False, 'message': 'Property not found'})
    
    service = PickupAnalysisService(property=prop)
    dashboard_data = service.get_dashboard_data()
    
    return JsonResponse({
        'success': True,
        'data': dashboard_data,
    })


@require_GET
def forecast_month_detail_ajax(request, org_code, prop_code, year, month):
    """
    AJAX endpoint for detailed forecast data for a specific month.
    
    Returns JSON with forecast details for modal display.
    """
    from pricing.services import PickupAnalysisService
    from pricing.models import Organization, Property
    from dateutil.relativedelta import relativedelta
    
    try:
        org = Organization.objects.get(code=org_code)
        prop = Property.objects.get(organization=org, code=prop_code)
    except (Organization.DoesNotExist, Property.DoesNotExist):
        return JsonResponse({'success': False, 'message': 'Property not found'})
    
    target_month = date(year, month, 1)
    
    service = PickupAnalysisService(property=prop)
    forecasts = service.get_forecast_summary(months_ahead=12)
    
    # Find the requested month
    forecast = None
    for f in forecasts:
        if f['month'] == target_month:
            forecast = f
            break
    
    if not forecast:
        return JsonResponse({'success': False, 'message': 'Forecast not found'})
    
    return JsonResponse({
        'success': True,
        'forecast': forecast,
    })

# =============================================================================
# AJAX ENDPOINTS
# =============================================================================


def revenue_forecast_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to return revenue AND occupancy forecast data.
    """
    try:
        from pricing.services import RevenueForecastService
        
        # Get property
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        
        forecast_service = RevenueForecastService(hotel=prop)
        
        # Get forecasts
        monthly_forecast = forecast_service.calculate_monthly_forecast()
        occupancy_forecast = forecast_service.calculate_occupancy_forecast()
        
        if not monthly_forecast:
            html = render_to_string('pricing/partials/revenue_forecast.html', {
                'has_forecast_data': False,
            })
            return JsonResponse({
                'success': True,
                'has_data': False,
                'html': html,
                'message': 'No forecast data available.'
            })
        
        # Prepare chart data
        forecast_months = [f"{item['month_name'][:3]}" for item in monthly_forecast]
        forecast_gross = [float(item['gross_revenue']) for item in monthly_forecast]
        forecast_net = [float(item['net_revenue']) for item in monthly_forecast]
        forecast_commission = [float(item['commission_amount']) for item in monthly_forecast]
        
        occupancy_months = [item['month_name'] for item in occupancy_forecast['monthly_data']]
        occupancy_percentages = [item['occupancy_percent'] for item in occupancy_forecast['monthly_data']]
        
        # Annual totals
        annual_gross = sum(item['gross_revenue'] for item in monthly_forecast)
        annual_net = sum(item['net_revenue'] for item in monthly_forecast)
        annual_commission = sum(item['commission_amount'] for item in monthly_forecast)
        annual_room_nights = sum(item['occupied_room_nights'] for item in monthly_forecast)
        annual_adr = (annual_gross / annual_room_nights) if annual_room_nights > 0 else Decimal('0.00')
        
        # Channel breakdown
        channels = Channel.objects.filter(hotel=hotel)
        channel_data = []
        for channel in channels:
            channel_gross = sum(
                sum(ch['gross_revenue'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            channel_net = sum(
                sum(ch['net_revenue'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            channel_commission = sum(
                sum(ch['commission_amount'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            
            if channel_gross > 0:
                channel_data.append({
                    'name': channel.name,
                    'share_percent': float(channel.distribution_share_percent),
                    'gross_revenue': float(channel_gross),
                    'net_revenue': float(channel_net),
                    'commission': float(channel_commission),
                })
        
        # Validate distribution
        is_valid, total_dist, message = forecast_service.validate_channel_distribution()
        
        revenue_chart_data = json.dumps({
            'months': forecast_months,
            'gross_revenue': forecast_gross,
            'net_revenue': forecast_net,
            'commission': forecast_commission
        })
        
        occupancy_chart_data = json.dumps({
            'months': occupancy_months,
            'occupancy': occupancy_percentages
        })
        
        revenue_html = render_to_string('pricing/partials/revenue_forecast.html', {
            'has_forecast_data': True,
            'annual_gross_revenue': annual_gross,
            'annual_net_revenue': annual_net,
            'annual_commission': annual_commission,
            'annual_adr': annual_adr,
            'annual_room_nights': annual_room_nights,
            'channel_breakdown': channel_data,
            'forecast_chart_data': revenue_chart_data,
            'distribution_valid': is_valid,
            'distribution_total': total_dist,
            'distribution_message': message,
        })
        
        occupancy_html = render_to_string('pricing/partials/occupancy_forecast.html', {
            'has_occupancy_data': True,
            'occupancy_chart_data': occupancy_chart_data,
            'annual_metrics': occupancy_forecast['annual_metrics'],
            'seasonal_data': occupancy_forecast['seasonal_data'],
        })
        
        return JsonResponse({
            'success': True,
            'has_data': True,
            'revenue_html': revenue_html,
            'occupancy_html': occupancy_html,
            'annual_gross': float(annual_gross),
            'annual_net': float(annual_net),
            'annual_adr': float(annual_adr),
            'annual_room_nights': int(annual_room_nights),
            'distribution_valid': is_valid,
        })
    
    except Exception as e:
        logger.exception("Revenue forecast AJAX error")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_GET

def pickup_summary_ajax(request, org_code, prop_code):
    """
    AJAX endpoint for pickup summary card on dashboard.
    """
    from pricing.models import MonthlyPickupSnapshot
    from pricing.services import PickupAnalysisService
    
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        
        service = PickupAnalysisService(property=prop)

        has_data = (MonthlyPickupSnapshot.objects.filter(hotel=prop).exists()
                    or Reservation.objects.filter(hotel=prop).exists())
        
        if not has_data:
            html = render_to_string('pricing/partials/pickup_summary.html', {
                'has_data': False,
            })
            return JsonResponse({'success': True, 'html': html, 'has_data': False})
        
        # Forecast summary (next 3 months)
        forecast_summary = service.get_forecast_summary(months_ahead=3)
        
        # Velocity
        today = date.today()
        next_month = (today + relativedelta(months=1)).replace(day=1)
        velocity = service.calculate_booking_velocity(next_month)
        
        # Alerts
        alerts = []
        for forecast in forecast_summary:
            if forecast.get('vs_stly_pace') and forecast['vs_stly_pace'] < -5:
                alerts.append({
                    'month': forecast['month_name'],
                    'message': f"{forecast['month_name']} is {abs(forecast['vs_stly_pace']):.1f}% behind STLY pace",
                    'type': 'warning'
                })
            elif forecast.get('variance_percent') and forecast['variance_percent'] < -10:
                alerts.append({
                    'month': forecast['month_name'],
                    'message': f"{forecast['month_name']} pickup forecast below scenario target",
                    'type': 'info'
                })
        
        html = render_to_string('pricing/partials/pickup_summary.html', {
            'has_data': True,
            'forecast_summary': forecast_summary,
            'velocity': velocity,
            'alerts': alerts[:2],
        })
        
        return JsonResponse({
            'success': True,
            'html': html,
            'has_data': True,
        })
    
    except Exception as e:
        logger.exception("Pickup summary AJAX error")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_GET
def occupancy_calendar_ajax(request, org_code, prop_code):
    """
    AJAX endpoint for per-day occupancy calendar data.

    Query params: year (int), month (int 1-12)
    Returns JSON with per-day rooms occupied, occupancy %, season info,
    plus monthly forecast occupancy as a header reference.
    """
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)

        today = date.today()

        try:
            year = int(request.GET.get('year', today.year))
            month = int(request.GET.get('month', today.month))
            if month < 1 or month > 12:
                month = today.month
        except (ValueError, TypeError):
            year, month = today.year, today.month

        # Month boundaries
        _, last_day = calendar.monthrange(year, month)
        first_date = date(year, month, 1)
        last_date = date(year, month, last_day)

        # Total rooms from property
        total_rooms = prop.get_total_rooms()

        # Build per-day occupancy map
        from pricing.utils import build_daily_occupancy_map
        occupancy_map = build_daily_occupancy_map(prop, first_date, last_date)

        # Build season map for the month
        seasons = Season.objects.filter(
            hotel=prop,
            start_date__lte=last_date,
            end_date__gte=first_date,
        )
        season_map = {}
        for season in seasons:
            s_start = max(season.start_date, first_date)
            s_end = min(season.end_date, last_date)
            cur = s_start
            while cur <= s_end:
                season_map[cur] = {
                    'name': season.name,
                    'type': season.season_type,
                }
                cur += timedelta(days=1)

        # Build per-day response
        days_data = {}
        current_date = first_date
        while current_date <= last_date:
            date_str = current_date.strftime('%Y-%m-%d')
            rooms_occupied = occupancy_map.get(current_date, 0)
            occupancy_pct = round(rooms_occupied / total_rooms * 100, 1) if total_rooms > 0 else 0
            season_info = season_map.get(current_date)

            days_data[date_str] = {
                'day': current_date.day,
                'weekday': current_date.weekday(),  # 0=Monday
                'rooms_occupied': rooms_occupied,
                'total_rooms': total_rooms,
                'occupancy_percent': occupancy_pct,
                'season_name': season_info['name'] if season_info else None,
                'season_type': season_info['type'] if season_info else None,
                'is_today': current_date == today,
                'is_past': current_date < today,
            }
            current_date += timedelta(days=1)

        # Monthly forecast (optional — shown in header)
        forecast_occupancy = None
        forecast_room_nights = None
        try:
            service = PickupAnalysisService(property=prop)
            target_month = date(year, month, 1)
            forecast = service.generate_forecast(target_month)
            if forecast:
                forecast_occupancy = forecast.get('forecast_occupancy')
                forecast_room_nights = forecast.get('forecast_room_nights')
        except Exception:
            pass

        # Prev / next month
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        return JsonResponse({
            'success': True,
            'year': year,
            'month': month,
            'month_name': first_date.strftime('%B %Y'),
            'total_rooms': total_rooms,
            'forecast_occupancy': forecast_occupancy,
            'forecast_room_nights': forecast_room_nights,
            'days': days_data,
            'prev': {'year': prev_year, 'month': prev_month},
            'next': {'year': next_year, 'month': next_month},
        })

    except Exception as e:
        logger.exception("Occupancy calendar AJAX error")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


class DemandForecastView(PropertyMixin, TemplateView):
    """
    Demand Forecast dashboard: bi-weekly occupancy forecast with rate suggestions.
    """
    template_name = 'pricing/forecasts/demand_forecast.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'forecasts'
        prop = context['property']

        has_data = Reservation.objects.filter(hotel=prop).exists()
        context['has_data'] = has_data
        context['total_rooms'] = prop.total_rooms or prop.get_total_rooms()

        # Load market position defaults for input fields
        context['bb_floor'] = 50
        context['bb_ceiling'] = 80
        try:
            from pricing.models import MarketPosition
            mp = MarketPosition.objects.get(hotel=prop)
            context['bb_floor'] = int(mp.bb_floor)
            context['bb_ceiling'] = int(mp.bb_ceiling)
        except Exception:
            pass

        return context


def generate_demand_forecast_ajax(request, org_code, prop_code):
    """AJAX: generate bi-weekly demand forecast."""
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)

        months_ahead = int(request.GET.get('months', 3))
        months_ahead = max(1, min(6, months_ahead))

        bb_floor = request.GET.get('bb_floor')
        bb_ceiling = request.GET.get('bb_ceiling')
        cancel_rate = request.GET.get('cancel_rate')

        bb_floor = int(bb_floor) if bb_floor else None
        bb_ceiling = int(bb_ceiling) if bb_ceiling else None
        cancel_rate = float(cancel_rate) / 100 if cancel_rate else None

        svc = PeriodForecastService(property=prop)
        result = svc.generate_forecast(
            months_ahead=months_ahead,
            bb_floor=bb_floor,
            bb_ceiling=bb_ceiling,
            cancel_rate=cancel_rate,
        )

        return JsonResponse({'success': True, **result})

    except Exception as e:
        logger.exception("Demand forecast AJAX error")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
