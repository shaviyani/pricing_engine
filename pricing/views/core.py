"""
Core views: Root redirect, Organization selector/dashboard, Property list/dashboard.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View, ListView
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import calendar

from pricing.models import (
    Organization, Property, Season, RoomType, RatePlan, Channel,
    RateModifier, SeasonModifierOverride, Reservation,
)
from pricing.services import PricingService, BookingAnalysisService
from pricing.utils import calculate_adr

from .mixins import OrganizationMixin, PropertyMixin

logger = logging.getLogger(__name__)

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
    template_name = 'pricing/core/organization_selector.html'
    
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
    template_name = 'pricing/core/organization_dashboard.html'
    
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
            status__in=Reservation.ACTIVE_STATUSES
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
        portfolio_adr = calculate_adr(total_revenue, total_room_nights)
        
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
                status__in=Reservation.ACTIVE_STATUSES
            )
            
            stats = reservations.aggregate(
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
                bookings=Count('id'),
            )
            
            revenue = stats['revenue'] or Decimal('0.00')
            room_nights = stats['room_nights'] or 0
            
            adr = calculate_adr(revenue, room_nights)
            
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
    template_name = 'pricing/core/property_list.html'
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
    Property dashboard — revenue director view.

    Sections:
    1. Compact header (property name, rooms, current season)
    2. KPI strip (30d occ, 90d occ, month rev, demand index, ADR)
    3. 12-month chart (revenue + OTB occupancy + projected occupancy)
    4. Two-column: occupancy calendar | demand index + market context
    """
    template_name = 'pricing/core/property_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'dashboard'
        prop = context['property']
        today = date.today()

        # Get property-scoped querysets
        qs = self.get_property_querysets(prop)
        total_rooms = prop.get_total_rooms()
        context['total_rooms'] = total_rooms

        # --- Current season ---
        current_season = qs['seasons'].filter(
            start_date__lte=today, end_date__gte=today
        ).first()
        context['current_season'] = current_season

        # --- KPI strip ---
        context['kpi_30d'] = self._calc_occ_kpi(prop, today, 30, total_rooms)
        context['kpi_90d'] = self._calc_occ_kpi(prop, today, 90, total_rooms)
        context['kpi_month_rev'] = self._calc_month_revenue_kpi(prop, today)
        context['kpi_adr'] = self._calc_adr_kpi(prop, today)

        # Demand index KPI (from market data)
        try:
            from platform_data.services import MarketSignalService
            country_code = prop.country_code
            demand_idx = MarketSignalService.get_property_demand_index(
                prop, country_code, direction='backward'
            )
            context['kpi_demand'] = {
                'pct': round((demand_idx['factor'] - 1) * 100, 1),
                'national_pct': round((demand_idx.get('national_factor', 1) - 1) * 100, 1),
                'has_data': demand_idx.get('has_data', False),
            }
        except Exception:
            context['kpi_demand'] = {'pct': 0, 'national_pct': 0, 'has_data': False}

        # --- 12-month snapshot (chart data) ---
        monthly_snapshot = []
        snapshot_totals = {'revenue': 0, 'room_nights': 0, 'available': 0, 'bookings': 0}

        for i in range(12):
            m = today.month + i
            y = today.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            _, days = calendar.monthrange(y, m)
            month_start = date(y, m, 1)
            month_end = date(y, m, days)

            stats = Reservation.objects.filter(
                hotel=prop,
                arrival_date__gte=month_start,
                arrival_date__lte=month_end,
                status__in=Reservation.ACTIVE_STATUSES
            ).aggregate(
                room_nights=Sum('nights'),
                revenue=Sum('total_amount'),
                bookings=Count('id'),
            )

            rn = stats['room_nights'] or 0
            rev = float(stats['revenue'] or 0)
            bk = stats['bookings'] or 0
            available = total_rooms * days
            occ = round(rn / available * 100, 1) if available > 0 else 0
            adr_val = calculate_adr(rev, rn)

            monthly_snapshot.append({
                'month_name': month_start.strftime('%b'),
                'month_full': month_start.strftime('%B %Y'),
                'year': y,
                'month': m,
                'revenue': rev,
                'room_nights': rn,
                'available': available,
                'occupancy': occ,
                'adr': adr_val,
                'bookings': bk,
            })
            snapshot_totals['revenue'] += rev
            snapshot_totals['room_nights'] += rn
            snapshot_totals['available'] += available
            snapshot_totals['bookings'] += bk

        snapshot_totals['occupancy'] = round(
            snapshot_totals['room_nights'] / snapshot_totals['available'] * 100, 1
        ) if snapshot_totals['available'] > 0 else 0
        snapshot_totals['adr'] = calculate_adr(
            snapshot_totals['revenue'], snapshot_totals['room_nights']
        )

        # --- Per-month demand indices for projected occupancy ---
        try:
            from platform_data.services import MarketSignalService
            month_dates = [
                date(snap['year'], snap['month'], 1)
                for snap in monthly_snapshot
            ]
            demand_indices = MarketSignalService.get_monthly_demand_indices(
                prop, month_dates
            )
        except Exception:
            demand_indices = {}

        projected_occ = []
        stly_occ = []
        for snap in monthly_snapshot:
            y_stly = snap['year'] - 1
            m_stly = snap['month']
            _, days_stly = calendar.monthrange(y_stly, m_stly)
            stly_start = date(y_stly, m_stly, 1)
            stly_end = date(y_stly, m_stly, days_stly)

            stly_stats = Reservation.objects.filter(
                hotel=prop,
                arrival_date__gte=stly_start,
                arrival_date__lte=stly_end,
                status__in=Reservation.ACTIVE_STATUSES
            ).aggregate(rn=Sum('nights'))
            stly_rn = stly_stats['rn'] or 0
            stly_available = total_rooms * days_stly
            stly_o = round(stly_rn / stly_available * 100, 1) if stly_available > 0 else 0
            stly_occ.append(stly_o)

            key = date(snap['year'], snap['month'], 1)
            idx = demand_indices.get(key)
            if idx and idx['has_data'] and stly_o > 0:
                proj = round(stly_o * idx['factor'], 1)
                proj = max(proj, snap['occupancy'])  # Floor at current OTB
                proj = min(proj, 100.0)
            else:
                demand_factor = context['kpi_demand']['pct'] / 100 + 1 if context['kpi_demand']['has_data'] else 1.0
                proj = round(stly_o * demand_factor, 1)
                proj = min(proj, 100.0)
            projected_occ.append(proj)

            # Attach demand index for tooltip
            snap['demand_pct'] = idx['pct'] if idx and idx['has_data'] else None
            snap['demand_driver'] = idx['top_driver'] if idx and idx['has_data'] else ''

        context['monthly_snapshot'] = monthly_snapshot
        context['snapshot_totals'] = snapshot_totals
        context['snapshot_json'] = json.dumps(monthly_snapshot)
        context['stly_occ_json'] = json.dumps(stly_occ)
        context['projected_occ_json'] = json.dumps(projected_occ)
        context['demand_factor_pct'] = context['kpi_demand']['pct']
        context['today_year'] = today.year
        context['today_month'] = today.month

        return context

    # -----------------------------------------------------------------
    # KPI helpers
    # -----------------------------------------------------------------
    def _calc_occ_kpi(self, prop, today, days_ahead, total_rooms):
        """OTB occupancy for next N days, with STLY comparison."""
        window_end = today + timedelta(days=days_ahead)
        rn = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            arrival_date__lt=window_end,
            status__in=Reservation.FUTURE_STATUSES
        ).aggregate(t=Sum('nights'))['t'] or 0
        available = total_rooms * days_ahead
        occ = round(rn / available * 100, 1) if available > 0 else 0

        # STLY at same days-out
        stly_start = date(today.year - 1, today.month, today.day)
        stly_end = stly_start + timedelta(days=days_ahead)
        stly_rn = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=stly_start,
            arrival_date__lt=stly_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).aggregate(t=Sum('nights'))['t'] or 0
        stly_available = total_rooms * days_ahead
        stly_occ = round(stly_rn / stly_available * 100, 1) if stly_available > 0 else 0

        return {
            'occ': occ,
            'stly_occ': stly_occ,
            'delta': round(occ - stly_occ, 1),
        }

    def _calc_month_revenue_kpi(self, prop, today):
        """Current month revenue with STLY comparison."""
        _, days = calendar.monthrange(today.year, today.month)
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year, today.month, days)

        rev = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        rev = float(rev)

        # STLY
        stly_start = date(today.year - 1, today.month, 1)
        _, stly_days = calendar.monthrange(today.year - 1, today.month)
        stly_end = date(today.year - 1, today.month, stly_days)
        stly_rev = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=stly_start,
            arrival_date__lte=stly_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        stly_rev = float(stly_rev)

        delta_pct = round((rev - stly_rev) / stly_rev * 100, 1) if stly_rev > 0 else 0

        return {'revenue': rev, 'stly_revenue': stly_rev, 'delta_pct': delta_pct}

    def _calc_adr_kpi(self, prop, today):
        """Blended ADR for next 90 days, with STLY comparison."""
        window_end = today + timedelta(days=90)
        stats = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            arrival_date__lt=window_end,
            status__in=Reservation.FUTURE_STATUSES
        ).aggregate(rev=Sum('total_amount'), rn=Sum('nights'))
        rev = float(stats['rev'] or 0)
        rn = stats['rn'] or 0
        adr = calculate_adr(rev, rn)

        # STLY
        stly_start = date(today.year - 1, today.month, today.day)
        stly_end = stly_start + timedelta(days=90)
        stly_stats = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=stly_start,
            arrival_date__lt=stly_end,
            status__in=Reservation.ACTIVE_STATUSES
        ).aggregate(rev=Sum('total_amount'), rn=Sum('nights'))
        stly_rev = float(stly_stats['rev'] or 0)
        stly_rn = stly_stats['rn'] or 0
        stly_adr = calculate_adr(stly_rev, stly_rn)

        return {
            'adr': adr,
            'stly_adr': stly_adr,
            'delta': round(adr - stly_adr, 2),
        }

class MarketContextAjaxView(PropertyMixin, View):
    """AJAX endpoint: returns market context JSON for the property dashboard."""

    def get(self, request, *args, **kwargs):
        prop = self.get_property()
        country_code = prop.country_code

        try:
            from platform_data.services import MarketSignalService
            data = MarketSignalService.get_market_context(country_code)

            # Add property vs market comparison if we have data
            if data.get('has_data') and data.get('period'):
                period = date.fromisoformat(data['period'])
                data['comparison'] = MarketSignalService.get_property_market_comparison(
                    country_code, period, prop
                )

            # Property demand index
            try:
                demand_backward = MarketSignalService.get_property_demand_index(
                    prop, country_code, direction='backward'
                )
                demand_forward = MarketSignalService.get_property_demand_index(
                    prop, country_code, direction='forward'
                )
            except Exception:
                demand_backward = {'factor': 1.0, 'components': [], 'has_data': False}
                demand_forward = {'factor': 1.0, 'components': [], 'has_data': False}

            data['demand_index'] = {
                'backward': {
                    'factor': demand_backward['factor'],
                    'pct': round((demand_backward['factor'] - 1) * 100, 1),
                    'components': demand_backward.get('components', []),
                    'national_pct': round((demand_backward.get('national_factor', 1) - 1) * 100, 1),
                    'label': demand_backward.get('label', ''),
                    'has_data': demand_backward.get('has_data', False),
                },
                'forward': {
                    'factor': demand_forward['factor'],
                    'pct': round((demand_forward['factor'] - 1) * 100, 1),
                    'components': demand_forward.get('components', []),
                    'national_pct': round((demand_forward.get('national_factor', 1) - 1) * 100, 1),
                    'label': demand_forward.get('label', ''),
                    'has_data': demand_forward.get('has_data', False),
                },
            }
        except Exception as e:
            logger.exception("Market context error")
            data = {'has_data': False, 'error': str(e)}

        return JsonResponse(data)


# =============================================================================
# PRICING MATRIX - Room-Centric Design
# =============================================================================
# Structure:
#   Room Name
#   ├── Channel 1 (B&B Standard rate)
#   │   └── [Expand: Rate Plans & Modifiers]
#   ├── Channel 2 (B&B Standard rate)
#   │   └── [Expand: Rate Plans & Modifiers]
#   └── Channel 3 (B&B Standard rate)
#       └── [Expand: Rate Plans & Modifiers]
# =============================================================================

"""
Updated PricingMatrixView with expanded modifier rates.
Uses PricingService for calculations (compatible with your local codebase).
"""

from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView


