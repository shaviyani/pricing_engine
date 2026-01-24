"""
Pricing Views - Refactored for Multi-Property Architecture

URL Structure:
    /                                       → RootRedirectView (redirect to last property)
    /org/                                   → OrganizationSelectorView (list orgs)
    /org/<org_code>/                        → OrganizationDashboardView (list properties)
    /org/<org_code>/<prop_code>/            → PropertyDashboardView (main dashboard)
    /org/<org_code>/<prop_code>/matrix/     → PricingMatrixView
    /org/<org_code>/<prop_code>/booking-analysis/
    /org/<org_code>/<prop_code>/pickup/
    /org/<org_code>/<prop_code>/api/...     → AJAX endpoints
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View, ListView
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from .models import (
    Organization, Property,
    Season, RoomType, RatePlan, Channel, RateModifier, SeasonModifierOverride,
    Reservation,
)
from .services import (
    calculate_final_rate,
    calculate_final_rate_with_modifier,
)

logger = logging.getLogger(__name__)


# =============================================================================
# MIXINS
# =============================================================================

class OrganizationMixin:
    """
    Mixin to get organization from URL kwargs.
    
    Adds to context:
        - organization: Organization instance
        - org: Shorthand alias
    """
    
    def get_organization(self):
        """Get organization by code from URL."""
        org_code = self.kwargs.get('org_code')
        return get_object_or_404(
            Organization.objects.filter(is_active=True),
            code=org_code
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['organization'] = self.get_organization()
        context['org'] = context['organization']
        return context


class PropertyMixin(OrganizationMixin):
    """
    Mixin to get property from URL kwargs.
    
    Adds to context:
        - organization, org: Organization instance
        - property, prop: Property instance
        
    Also stores in session for convenience.
    """
    
    def get_property(self):
        """Get property by code from URL, scoped to organization."""
        org = self.get_organization()
        prop_code = self.kwargs.get('prop_code')
        return get_object_or_404(
            Property.objects.filter(is_active=True),
            organization=org,
            code=prop_code
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = self.get_property()
        context['property'] = prop
        context['prop'] = prop
        
        # Store in session for redirect convenience
        self.request.session['current_property_id'] = prop.id
        self.request.session['current_org_id'] = context['organization'].id
        
        return context
    
    def get_property_querysets(self, prop):
        """
        Get common querysets filtered by property/hotel.
        
        Property-Specific (have hotel FK): Season, RoomType
        Shared/Global (no hotel FK): RatePlan, Channel, RateModifier
        
        Returns dict with seasons, rooms, rate_plans, channels.
        """
        return {
            'seasons': Season.objects.filter(hotel=prop).order_by('start_date'),
            'rooms': RoomType.objects.filter(hotel=prop).order_by('sort_order'),
            'rate_plans': RatePlan.objects.all().order_by('sort_order'),  # Global
            'channels': Channel.objects.all().order_by('sort_order'),  # Global
        }


# =============================================================================
# ROOT & SELECTOR VIEWS
# =============================================================================

class RootRedirectView(View):
    """
    Root URL handler - redirects to appropriate destination.
    
    Priority:
    1. Last used property (from session)
    2. Default property (if only one org/property)
    3. Organization selector (if multiple)
    """
    
    def get(self, request):
        # Check session for last used property
        property_id = request.session.get('current_property_id')
        if property_id:
            try:
                prop = Property.objects.select_related('organization').get(
                    pk=property_id,
                    is_active=True,
                    organization__is_active=True
                )
                return redirect('pricing:property_dashboard',
                                org_code=prop.organization.code,
                                prop_code=prop.code)
            except Property.DoesNotExist:
                # Clear invalid session data
                request.session.pop('current_property_id', None)
        
        # Check organization count
        orgs = Organization.objects.filter(is_active=True)
        org_count = orgs.count()
        
        if org_count == 0:
            return render(request, 'pricing/no_setup.html')
        
        if org_count == 1:
            org = orgs.first()
            props = org.properties.filter(is_active=True)
            prop_count = props.count()
            
            if prop_count == 1:
                prop = props.first()
                return redirect('pricing:property_dashboard',
                                org_code=org.code,
                                prop_code=prop.code)
            elif prop_count > 1:
                return redirect('pricing:org_dashboard', org_code=org.code)
            else:
                return redirect('pricing:org_dashboard', org_code=org.code)
        
        # Multiple organizations - show selector
        return redirect('pricing:org_selector')


class OrganizationSelectorView(TemplateView):
    """
    Organization selector page.
    
    Shows all active organizations with their properties.
    """
    template_name = 'pricing/organization_selector.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['organizations'] = Organization.objects.filter(
            is_active=True
        ).prefetch_related('properties')
        return context


# =============================================================================
# ORGANIZATION VIEWS
# =============================================================================

class OrganizationDashboardView(OrganizationMixin, TemplateView):
    """
    Organization dashboard - lists all properties with consolidated metrics.
    
    This is the "home" view for an organization.
    """
    template_name = 'pricing/organization_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = context['organization']
        
        # Get all active properties
        properties = org.properties.filter(is_active=True).order_by('name')
        context['properties'] = properties
        
        # Calculate consolidated metrics
        context['consolidated'] = self._get_consolidated_metrics(properties)
        
        # Property performance cards
        context['property_cards'] = self._get_property_cards(properties)
        
        return context
    
    def _get_consolidated_metrics(self, properties):
        """Calculate consolidated metrics across all properties."""
        import calendar
        
        year = date.today().year
        
        # Aggregate reservations across all properties
        reservations = Reservation.objects.filter(
            hotel__in=properties,
            arrival_date__year=year,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        stats = reservations.aggregate(
            total_revenue=Sum('total_amount'),
            total_room_nights=Sum('nights'),
            total_reservations=Count('id'),
        )
        
        total_revenue = stats['total_revenue'] or Decimal('0.00')
        total_room_nights = stats['total_room_nights'] or 0
        total_reservations = stats['total_reservations'] or 0
        
        # Calculate portfolio ADR
        portfolio_adr = Decimal('0.00')
        if total_room_nights > 0:
            portfolio_adr = (total_revenue / total_room_nights).quantize(Decimal('0.01'))
        
        # Calculate portfolio occupancy
        total_rooms = sum(p.total_rooms for p in properties)
        days_in_year = 366 if calendar.isleap(year) else 365
        total_available = total_rooms * days_in_year
        
        portfolio_occupancy = Decimal('0.0')
        if total_available > 0:
            portfolio_occupancy = (
                Decimal(str(total_room_nights)) / Decimal(str(total_available)) * 100
            ).quantize(Decimal('0.1'))
        
        return {
            'total_revenue': total_revenue,
            'total_room_nights': total_room_nights,
            'total_reservations': total_reservations,
            'portfolio_adr': portfolio_adr,
            'portfolio_occupancy': portfolio_occupancy,
            'total_rooms': total_rooms,
            'property_count': properties.count(),
            'year': year,
        }
    
    def _get_property_cards(self, properties):
        """Get performance data for each property card."""
        year = date.today().year
        cards = []
        
        for prop in properties:
            reservations = Reservation.objects.filter(
                hotel=prop,
                arrival_date__year=year,
                status__in=['confirmed', 'checked_in', 'checked_out']
            )
            
            stats = reservations.aggregate(
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
                bookings=Count('id'),
            )
            
            revenue = stats['revenue'] or Decimal('0.00')
            room_nights = stats['room_nights'] or 0
            
            adr = Decimal('0.00')
            if room_nights > 0:
                adr = (revenue / room_nights).quantize(Decimal('0.01'))
            
            cards.append({
                'property': prop,
                'revenue': revenue,
                'room_nights': room_nights,
                'bookings': stats['bookings'] or 0,
                'adr': adr,
            })
        
        # Sort by revenue descending
        cards.sort(key=lambda x: x['revenue'], reverse=True)
        
        return cards


class PropertyListView(OrganizationMixin, ListView):
    """List of properties in an organization."""
    template_name = 'pricing/property_list.html'
    context_object_name = 'properties'
    
    def get_queryset(self):
        org = self.get_organization()
        return Property.objects.filter(
            organization=org,
            is_active=True
        ).order_by('name')


# =============================================================================
# PROPERTY DASHBOARD
# =============================================================================

class PropertyDashboardView(PropertyMixin, TemplateView):
    """
    Property dashboard - main landing page for a property.
    
    Includes:
    - Quick stats (rooms, seasons, channels, rate plans)
    - Rate parity summary
    - Recent reservations
    - Revenue forecast (via AJAX)
    """
    template_name = 'pricing/property_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']
        
        # Get property-scoped querysets
        qs = self.get_property_querysets(prop)
        
        # Quick stats
        context['stats'] = {
            'seasons_count': qs['seasons'].count(),
            'rooms_count': qs['rooms'].count(),
            'room_inventory': sum(rt.number_of_rooms for rt in qs['rooms']),
            'rate_plans_count': qs['rate_plans'].count(),
            'channels_count': qs['channels'].count(),
        }
        
        # Pass querysets for display
        context['room_types'] = qs['rooms']
        context['seasons'] = qs['seasons']
        context['channels'] = qs['channels']
        
        # Recent reservations
        context['recent_reservations'] = Reservation.objects.filter(
            hotel=prop
        ).select_related('guest', 'room_type', 'channel').order_by('-booking_date')[:10]
        
        # Rate parity summary
        self._add_parity_context(context, prop, qs)
        
        return context
    
    def _add_parity_context(self, context, prop, qs):
        """Calculate rate parity summary for the property."""
        parity_data = []
        parity_season = None
        parity_room = None
        parity_rate_plan = None
        bar_rate = None
        
        try:
            seasons = qs['seasons']
            rooms = qs['rooms']
            channels = qs['channels']
            rate_plans = qs['rate_plans']
            
            all_seasons = list(seasons)
            context['all_seasons'] = all_seasons
            
            # Check we have data
            if not all([seasons.exists(), rooms.exists(), channels.exists(), rate_plans.exists()]):
                context['parity_data'] = []
                return
            
            # Get selected or default season
            selected_season_id = self.request.GET.get('parity_season')
            if selected_season_id:
                try:
                    parity_season = seasons.get(id=selected_season_id)
                except (Season.DoesNotExist, ValueError):
                    parity_season = seasons.first()
            else:
                parity_season = seasons.first()
            
            parity_room = rooms.first()
            parity_rate_plan = rate_plans.first()
            
            # Calculate BAR (Best Available Rate - no discounts)
            bar_rate, _ = calculate_final_rate_with_modifier(
                room_base_rate=parity_room.get_effective_base_rate(),
                season_index=parity_season.season_index,
                meal_supplement=parity_rate_plan.meal_supplement,
                channel_base_discount=Decimal('0.00'),
                modifier_discount=Decimal('0.00'),
                commission_percent=Decimal('0.00'),
                occupancy=2
            )
            
            # Calculate rate for each channel
            for channel in channels:
                # Get standard modifier discount for this channel/season
                # RateModifier is shared (linked to global Channel)
                season_discount = Decimal('0.00')
                modifiers = RateModifier.objects.filter(
                    channel=channel,
                    active=True
                )
                if modifiers.exists():
                    # Try to get standard (0% discount) modifier first
                    modifier = modifiers.filter(discount_percent=0).first()
                    if not modifier:
                        modifier = modifiers.first()
                    season_discount = modifier.get_discount_for_season(parity_season)
                
                channel_rate, breakdown = calculate_final_rate_with_modifier(
                    room_base_rate=parity_room.get_effective_base_rate(),
                    season_index=parity_season.season_index,
                    meal_supplement=parity_rate_plan.meal_supplement,
                    channel_base_discount=channel.base_discount_percent,
                    modifier_discount=season_discount,
                    commission_percent=channel.commission_percent,
                    occupancy=2
                )
                
                difference = channel_rate - bar_rate
                difference_percent = (difference / bar_rate * 100) if bar_rate > 0 else Decimal('0.00')
                
                # Determine parity status
                if abs(difference_percent) < Decimal('1.0'):
                    status = 'good'
                    status_text = 'At Parity'
                elif difference_percent < 0:
                    status = 'warning'
                    status_text = 'Below BAR'
                else:
                    status = 'info'
                    status_text = 'Above BAR'
                
                parity_data.append({
                    'channel': channel,
                    'rate': channel_rate,
                    'bar_rate': bar_rate,
                    'difference': difference,
                    'difference_percent': difference_percent,
                    'status': status,
                    'status_text': status_text,
                    'net_revenue': breakdown['net_revenue'],
                })
        
        except Exception as e:
            logger.exception("Error calculating rate parity")
            parity_data = []
        
        context['parity_data'] = parity_data
        context['parity_season'] = parity_season
        context['parity_room'] = parity_room
        context['parity_rate_plan'] = parity_rate_plan
        context['bar_rate'] = bar_rate


# =============================================================================
# PRICING MATRIX
# =============================================================================

class PricingMatrixView(PropertyMixin, TemplateView):
    """
    Pricing matrix showing all rate combinations.
    
    Display structure:
    - Seasons as columns
    - For each Channel:
        - For each Room Type + Rate Plan:
            - BAR row showing baseline rates
            - Modifier rows showing discounted rates
    """
    template_name = 'pricing/matrix.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']
        
        # Get property-scoped data
        qs = self.get_property_querysets(prop)
        seasons = qs['seasons']
        rooms = qs['rooms']
        rate_plans = qs['rate_plans']
        channels = qs['channels']
        
        # Check if we have data
        if not all([seasons.exists(), rooms.exists(), rate_plans.exists(), channels.exists()]):
            context['has_data'] = False
            context['seasons'] = seasons
            context['rooms'] = rooms
            context['rate_plans'] = rate_plans
            context['channels'] = channels
            return context
        
        context['has_data'] = True
        
        # Get selected season (default to first)
        season_id = self.request.GET.get('season')
        if season_id:
            try:
                selected_season = seasons.get(id=season_id)
            except (Season.DoesNotExist, ValueError):
                selected_season = seasons.first()
        else:
            selected_season = seasons.first()
        
        # Build matrix
        matrix = self._build_matrix(prop, seasons, rooms, rate_plans, channels, selected_season)
        
        context['seasons'] = seasons
        context['selected_season'] = selected_season
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        
        return context
    
    def _build_matrix(self, prop, seasons, rooms, rate_plans, channels, selected_season):
        """
        Build the pricing matrix data structure.
        
        Structure: matrix[channel_id][room_id][rate_plan_id] = {
            'bar_rate': Decimal,
            'modifiers': [{
                'modifier': RateModifier,
                'seasons': {season_id: {'rate': Decimal, 'breakdown': dict}}
            }]
        }
        """
        matrix = {}
        
        for channel in channels:
            matrix[channel.id] = {}
            
            # Get active modifiers for this channel (RateModifier is shared)
            modifiers = RateModifier.objects.filter(
                channel=channel,
                active=True
            ).order_by('sort_order')
            
            for room in rooms:
                matrix[channel.id][room.id] = {}
                
                for rate_plan in rate_plans:
                    # Calculate BAR for selected season (display reference)
                    seasonal_rate = room.get_effective_base_rate() * selected_season.season_index
                    meal_cost = rate_plan.meal_supplement * 2
                    bar_rate = seasonal_rate + meal_cost
                    
                    # Calculate rates for each modifier across ALL seasons
                    modifiers_list = []
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        for season in seasons:
                            season_discount = modifier.get_discount_for_season(season)
                            
                            final_rate, breakdown = calculate_final_rate_with_modifier(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                        
                        modifiers_list.append(modifier_data)
                    
                    matrix[channel.id][room.id][rate_plan.id] = {
                        'bar_rate': bar_rate,
                        'modifiers': modifiers_list
                    }
        
        return matrix


# =============================================================================
# BOOKING ANALYSIS
# =============================================================================

# =============================================================================
# BOOKING ANALYSIS VIEW - CORRECTED
# =============================================================================
# Fix: property=prop (not property==prop)
# =============================================================================

import json
from datetime import date

from django.views.generic import TemplateView

from .models import Reservation


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
    template_name = 'pricing/booking_analysis_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']
        
        from .services import BookingAnalysisService
        
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
    template_name = 'pricing/pickup_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = context['property']
        
        from pricing.models import PickupCurve, RoomType, Season
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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
        # PICKUP CURVES
        # =====================================================================
        curves = {}
        default_curves = service.get_default_pickup_curves()
        
        for season_type in ['peak', 'high', 'shoulder', 'low']:
            curve_data = PickupCurve.objects.filter(
                season_type=season_type,
                season__isnull=True
            )
            
            if hasattr(PickupCurve, 'hotel'):
                curve_data = curve_data.filter(hotel=prop)
            
            curve_data = curve_data.order_by('-days_out')
            
            if curve_data.exists():
                curves[season_type] = [
                    {'days_out': c.days_out, 'percent': float(c.cumulative_percent)}
                    for c in curve_data
                ]
            else:
                curves[season_type] = [
                    {'days_out': d, 'percent': p}
                    for d, p in default_curves[season_type]
                ]
        
        context['pickup_curves'] = curves
        
        # =====================================================================
        # CHART DATA AS JSON (for JavaScript)
        # =====================================================================
        chart_data = {
            'bookingPace': {
                'dates': booking_pace['dates'],
                'cumNights': booking_pace['cum_nights'],
                'cumRevenue': booking_pace['cum_revenue'],
                'stlyNights': booking_pace['stly_nights'],
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
            'velocity': {
                'dates': daily_velocity['dates'],
                'dailyCount': daily_velocity['daily_count'],
                'dailyRevenue': daily_velocity['daily_revenue'],
            },
            'pickupCurves': {
                'daysOut': [90, 75, 60, 45, 30, 15, 7, 0],
                'peak': [d['percent'] for d in curves.get('peak', [])[-8:]],
                'high': [d['percent'] for d in curves.get('high', [])[-8:]],
                'shoulder': [d['percent'] for d in curves.get('shoulder', [])[-8:]],
                'low': [d['percent'] for d in curves.get('low', [])[-8:]],
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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
            status__in=['confirmed', 'checked_in', 'checked_out']
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

@require_GET
def parity_data_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to return parity data for a specific season.
    """
    try:
        # Get property
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        
        season_id = request.GET.get('season')
        
        # Property-specific: Season, RoomType
        # Shared/Global: RatePlan, Channel, RateModifier
        seasons = Season.objects.filter(hotel=prop).order_by('start_date')
        rooms = RoomType.objects.filter(hotel=prop)
        channels = Channel.objects.all()  # Global
        rate_plans = RatePlan.objects.all()  # Global
        
        if not all([seasons.exists(), rooms.exists(), channels.exists(), rate_plans.exists()]):
            return JsonResponse({'success': False, 'message': 'Missing required data'})
        
        # Get selected season
        if season_id:
            try:
                parity_season = seasons.get(id=season_id)
            except (Season.DoesNotExist, ValueError):
                parity_season = seasons.first()
        else:
            parity_season = seasons.first()
        
        parity_room = rooms.first()
        parity_rate_plan = rate_plans.first()
        
        # Calculate BAR
        bar_rate, _ = calculate_final_rate_with_modifier(
            room_base_rate=parity_room.get_effective_base_rate(),
            season_index=parity_season.season_index,
            meal_supplement=parity_rate_plan.meal_supplement,
            channel_base_discount=Decimal('0.00'),
            modifier_discount=Decimal('0.00'),
            commission_percent=Decimal('0.00'),
            occupancy=2
        )
        
        # Calculate parity for each channel
        parity_data = []
        for channel in channels:
            season_discount = Decimal('0.00')
            modifiers = RateModifier.objects.filter(
                channel=channel,
                active=True
            )
            if modifiers.exists():
                modifier = modifiers.filter(discount_percent=0).first() or modifiers.first()
                season_discount = modifier.get_discount_for_season(parity_season)
            
            channel_rate, breakdown = calculate_final_rate_with_modifier(
                room_base_rate=parity_room.get_effective_base_rate(),
                season_index=parity_season.season_index,
                meal_supplement=parity_rate_plan.meal_supplement,
                channel_base_discount=channel.base_discount_percent,
                modifier_discount=season_discount,
                commission_percent=channel.commission_percent,
                occupancy=2
            )
            
            difference = channel_rate - bar_rate
            difference_percent = (difference / bar_rate * 100) if bar_rate > 0 else Decimal('0.00')
            
            if abs(difference_percent) < Decimal('1.0'):
                status, status_text = 'good', 'At Parity'
            elif difference_percent < 0:
                status, status_text = 'warning', 'Below BAR'
            else:
                status, status_text = 'info', 'Above BAR'
            
            parity_data.append({
                'channel': channel,
                'rate': channel_rate,
                'bar_rate': bar_rate,
                'difference': difference,
                'difference_percent': difference_percent,
                'status': status,
                'status_text': status_text,
                'net_revenue': breakdown['net_revenue'],
            })
        
        html = render_to_string('pricing/partials/parity_table.html', {
            'parity_data': parity_data,
        })
        
        return JsonResponse({
            'success': True,
            'html': html,
            'season_name': parity_season.name,
            'room_name': parity_room.name,
            'rate_plan_name': parity_rate_plan.name,
        })
    
    except Exception as e:
        logger.exception("Parity AJAX error")
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@require_GET
def revenue_forecast_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to return revenue AND occupancy forecast data.
    """
    try:
        from .services import RevenueForecastService
        
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
        channels = Channel.objects.all()  # Global
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
def booking_analysis_data_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to get booking analysis data.
    """
    from .services import BookingAnalysisService
    
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


@require_GET
def pickup_summary_ajax(request, org_code, prop_code):
    """
    AJAX endpoint for pickup summary card on dashboard.
    """
    from .models import MonthlyPickupSnapshot
    from .services import PickupAnalysisService
    
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        
        service = PickupAnalysisService(hotel=prop)
        
        has_data = MonthlyPickupSnapshot.objects.filter(hotel=prop).exists()
        
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


@require_POST
def update_room(request, org_code, prop_code, room_id):
    """
    AJAX endpoint to update room details.
    """
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        room = get_object_or_404(RoomType, id=room_id, hotel=prop)
        
        room.name = request.POST.get('name', room.name)
        room.base_rate = Decimal(request.POST.get('base_rate', room.base_rate))
        room.room_index = Decimal(request.POST.get('room_index', room.room_index))
        room.room_adjustment = Decimal(request.POST.get('room_adjustment', room.room_adjustment))
        room.pricing_method = request.POST.get('pricing_method', room.pricing_method)
        room.number_of_rooms = int(request.POST.get('number_of_rooms', room.number_of_rooms))
        room.sort_order = int(request.POST.get('sort_order', room.sort_order))
        
        room.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Room updated successfully',
            'room': {
                'id': room.id,
                'name': room.name,
                'base_rate': str(room.base_rate),
            }
        })
    except Exception as e:
        logger.exception("Update room error")
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@require_POST
def update_season(request, org_code, prop_code, season_id):
    """
    AJAX endpoint to update season details.
    """
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        season = get_object_or_404(Season, id=season_id, hotel=prop)
        
        season.name = request.POST.get('name', season.name)
        season.start_date = request.POST.get('start_date', season.start_date)
        season.end_date = request.POST.get('end_date', season.end_date)
        season.season_index = Decimal(request.POST.get('season_index', season.season_index))
        season.expected_occupancy = Decimal(request.POST.get('expected_occupancy', season.expected_occupancy))
        
        season.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Season updated successfully',
            'season': {
                'id': season.id,
                'name': season.name,
                'season_index': str(season.season_index),
            }
        })
    except Exception as e:
        logger.exception("Update season error")
        return JsonResponse({'success': False, 'message': str(e)}, status=400)