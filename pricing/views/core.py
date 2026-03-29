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
    RateModifier, SeasonModifierOverride, Reservation, UserOrganizationRole,
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
    
    def _get_user_orgs(self, user):
        """Get organizations the user has access to."""
        if user.is_superuser:
            return Organization.objects.filter(is_active=True)
        user_org_ids = UserOrganizationRole.objects.filter(
            user=user, is_active=True
        ).values_list('organization_id', flat=True)
        return Organization.objects.filter(id__in=user_org_ids, is_active=True)

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
                # Verify user has access to this org
                user = request.user
                if user.is_superuser or UserOrganizationRole.objects.filter(
                    user=user, organization=prop.organization, is_active=True
                ).exists():
                    return redirect('pricing:property_dashboard',
                                    org_code=prop.organization.code,
                                    prop_code=prop.code)
                else:
                    request.session.pop('current_property_id', None)
                    request.session.pop('current_org_id', None)
            except Property.DoesNotExist:
                # Clear invalid session data
                request.session.pop('current_property_id', None)

        # Check organization count — filtered by user access
        orgs = self._get_user_orgs(request.user)
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

    Shows organizations the user has access to, with their properties.
    """
    template_name = 'pricing/core/organization_selector.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_superuser:
            context['organizations'] = Organization.objects.filter(
                is_active=True
            ).prefetch_related('properties')
        else:
            user_org_ids = UserOrganizationRole.objects.filter(
                user=user, is_active=True
            ).values_list('organization_id', flat=True)
            context['organizations'] = Organization.objects.filter(
                id__in=user_org_ids, is_active=True
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
        context['kpi_revpar'] = self._calc_revpar_kpi(prop, today, total_rooms)

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

        # --- Per-month cancel rates for chart ---
        cancel_rates_12m = []
        for snap in monthly_snapshot:
            m = snap['month']
            all_count = Reservation.objects.filter(
                hotel=prop, arrival_date__month=m
            ).count()
            cxl_count = Reservation.objects.filter(
                hotel=prop, arrival_date__month=m, status='cancelled'
            ).count()
            rate = round(cxl_count / all_count * 100, 1) if all_count > 0 else 0
            cancel_rates_12m.append(rate)
            snap['cancel_rate'] = rate

        context['monthly_snapshot'] = monthly_snapshot
        context['snapshot_totals'] = snapshot_totals
        context['snapshot_json'] = json.dumps(monthly_snapshot)
        context['stly_occ_json'] = json.dumps(stly_occ)
        context['projected_occ_json'] = json.dumps(projected_occ)
        context['cancel_rates_json'] = json.dumps(cancel_rates_12m)
        context['demand_factor_pct'] = context['kpi_demand']['pct']
        context['today_year'] = today.year
        context['today_month'] = today.month

        # --- Budget vs Actuals for current month ---
        try:
            from pricing.models import MonthlyBudget
            budget = MonthlyBudget.objects.filter(
                hotel=prop, year=today.year, month=today.month
            ).first()
            if budget and float(budget.revenue_target) > 0:
                actual_rev = context['kpi_month_rev']['revenue']
                target_rev = float(budget.revenue_target)
                context['budget_month'] = {
                    'has_budget': True,
                    'revenue_target': target_rev,
                    'revenue_pct': round(actual_rev / target_rev * 100, 1) if target_rev > 0 else 0,
                    'occupancy_target': float(budget.occupancy_target),
                    'adr_target': float(budget.adr_target),
                }
            else:
                context['budget_month'] = {'has_budget': False}
        except Exception:
            context['budget_month'] = {'has_budget': False}

        # --- Review rating (from CompetitiveSet) ---
        try:
            from pricing.models import CompetitiveSet
            own_rating = CompetitiveSet.objects.filter(
                hotel=prop, is_own_property=True
            ).values_list('rating', flat=True).first()
            context['review_rating'] = float(own_rating) if own_rating else None
            context['review_count'] = 89  # Placeholder until GuestReview model
        except Exception:
            context['review_rating'] = None
            context['review_count'] = 0

        # --- Market position summary ---
        try:
            from pricing.models import MarketPosition, CompetitiveSet
            mp = MarketPosition.objects.filter(hotel=prop).first()
            if mp:
                comp_count = CompetitiveSet.objects.filter(hotel=prop).count()
                latest_comp = CompetitiveSet.objects.filter(hotel=prop).order_by('-updated_at').first()
                survey_age = (today - latest_comp.updated_at.date()).days if latest_comp else None
                context['market_position'] = {
                    'has_data': True,
                    'bb_floor': float(mp.bb_floor),
                    'bb_ceiling': float(mp.bb_ceiling),
                    'market_avg': float(mp.market_avg_bb) if mp.market_avg_bb else None,
                    'strategy': mp.get_strategy_display(),
                    'comp_count': comp_count,
                    'survey_age': survey_age,
                }
            else:
                context['market_position'] = {'has_data': False}
        except Exception:
            context['market_position'] = {'has_data': False}

        # --- Cancellation forecast for next month ---
        next_month_num = today.month % 12 + 1
        next_month_year = today.year + (1 if next_month_num == 1 else 0)
        next_month_start = date(next_month_year, next_month_num, 1)
        _, next_month_days = calendar.monthrange(next_month_year, next_month_num)
        next_month_end = date(next_month_year, next_month_num, next_month_days)

        next_otb = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=next_month_start,
            arrival_date__lte=next_month_end,
            status__in=Reservation.ACTIVE_STATUSES,
        )
        otb_count = next_otb.count()

        hist_qs = Reservation.objects.filter(hotel=prop, arrival_date__month=next_month_num)
        hist_total = hist_qs.count()
        hist_cancelled = hist_qs.filter(status='cancelled').count()
        cxl_rate = round(hist_cancelled / hist_total * 100, 1) if hist_total >= 10 else 50.0

        predicted_cancels = round(otb_count * cxl_rate / 100)
        net_forecast = otb_count - predicted_cancels

        high_risk = round(otb_count * 0.18)
        medium_risk = round(otb_count * 0.40)
        low_risk = otb_count - high_risk - medium_risk

        context['cancel_forecast'] = {
            'has_data': otb_count > 0,
            'otb_count': otb_count,
            'cancel_rate': cxl_rate,
            'predicted_cancels': predicted_cancels,
            'net_forecast': net_forecast,
            'month_name': calendar.month_name[next_month_num],
            'high_risk': high_risk,
            'medium_risk': medium_risk,
            'low_risk': low_risk,
            'is_high_cancel': cxl_rate > 50,
        }

        # --- Alerts ---
        context['alerts'] = self._build_alerts(prop, today, context)

        # --- Setup checklist ---
        checklist = []
        has_seasons = qs['seasons'].exists()
        has_rooms = qs['rooms'].exists()
        has_rate_plans = qs['rate_plans'].exists()
        has_channels = qs['channels'].exists()
        has_reservations = Reservation.objects.filter(hotel=prop).exists()

        checklist.append({'label': 'Seasons configured', 'done': has_seasons, 'link_name': 'pricing:manage_pricing'})
        checklist.append({'label': 'Room types defined', 'done': has_rooms, 'link_name': 'pricing:manage_pricing'})
        checklist.append({'label': 'Rate plans created', 'done': has_rate_plans, 'link_name': 'pricing:manage_pricing'})
        checklist.append({'label': 'Channels set up', 'done': has_channels, 'link_name': 'pricing:manage_pricing'})
        checklist.append({'label': 'Reservations imported', 'done': has_reservations, 'link_name': 'pricing:manage_import'})

        context['setup_checklist'] = checklist
        context['setup_complete'] = all(c['done'] for c in checklist)

        return context

    # -----------------------------------------------------------------
    # Alerts builder
    # -----------------------------------------------------------------
    def _build_alerts(self, prop, today, context):
        """Build conditional alert list for dashboard. Max 4, severity-sorted."""
        from django.urls import reverse
        alerts = []
        org_code = prop.organization.code
        prop_code = prop.code
        kwargs = {'org_code': org_code, 'prop_code': prop_code}

        # 1. Budget tracking — behind budget with <15 days left
        budget = context.get('budget_month', {})
        if budget.get('has_budget') and budget.get('revenue_pct', 100) < 70:
            days_left = calendar.monthrange(today.year, today.month)[1] - today.day
            if days_left < 15:
                alerts.append({
                    'severity': 'error' if budget['revenue_pct'] < 50 else 'warning',
                    'message': f"Revenue at {budget['revenue_pct']:.0f}% of budget with {days_left} days left",
                    'action_label': 'View breakdown',
                    'action_url': reverse('pricing:booking_analysis_dashboard', kwargs=kwargs),
                })

        # 2. Expiring group allotments (within 14 days)
        try:
            from pricing.services import AllotmentService
            expiring = AllotmentService(prop).check_expiring_allotments(days_ahead=14)
            if expiring.exists():
                total_rooms_at_risk = sum(a.rooms_remaining for a in expiring)
                if total_rooms_at_risk > 0:
                    alerts.append({
                        'severity': 'warning',
                        'message': f"{expiring.count()} allotment{'s' if expiring.count() > 1 else ''} releasing soon — {total_rooms_at_risk} rooms at risk",
                        'action_label': 'Review groups',
                        'action_url': reverse('pricing:manage_groups', kwargs=kwargs),
                    })
        except Exception:
            pass

        # 3. Stale competitive set (>30 days since last survey)
        try:
            from pricing.models import CompetitiveSet
            latest_survey = CompetitiveSet.objects.filter(hotel=prop).order_by('-updated_at').first()
            if latest_survey:
                age = (today - latest_survey.updated_at.date()).days
                if age > 30:
                    alerts.append({
                        'severity': 'warning',
                        'message': f"Competitive set is {age} days old",
                        'action_label': 'Update rates',
                        'action_url': reverse('pricing:manage_competitive', kwargs=kwargs),
                    })
        except Exception:
            pass

        # 4. Low 90d occupancy
        kpi_90d = context.get('kpi_90d', {})
        if kpi_90d.get('occ', 100) < 40:
            alerts.append({
                'severity': 'warning',
                'message': f"90-day occupancy at {kpi_90d['occ']}% — consider promotional rates",
                'action_label': 'Adjust rates',
                'action_url': reverse('pricing:override_calendar', kwargs=kwargs),
            })

        severity_order = {'error': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda a: severity_order.get(a['severity'], 3))
        return alerts[:4]

    # -----------------------------------------------------------------
    # KPI helpers
    # -----------------------------------------------------------------
    def _calc_occ_kpi(self, prop, today, days_ahead, total_rooms):
        """OTB occupancy for next N days, with STLY comparison and net-of-cancellation."""
        window_end = today + timedelta(days=days_ahead)
        rn = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            arrival_date__lt=window_end,
            status__in=Reservation.FUTURE_STATUSES
        ).aggregate(t=Sum('nights'))['t'] or 0
        available = total_rooms * days_ahead
        occ = round(rn / available * 100, 1) if available > 0 else 0

        # Historical cancel rate for net OTB
        all_bookings = Reservation.objects.filter(
            hotel=prop, arrival_date__gte=today, arrival_date__lt=window_end
        ).count()
        cancelled = Reservation.objects.filter(
            hotel=prop, arrival_date__gte=today, arrival_date__lt=window_end,
            status='cancelled'
        ).count()
        cancel_rate = cancelled / all_bookings if all_bookings > 0 else 0
        # If no future cancellations yet, use overall historical rate
        if cancel_rate == 0:
            hist_total = Reservation.objects.filter(hotel=prop).count()
            hist_cxl = Reservation.objects.filter(hotel=prop, status='cancelled').count()
            cancel_rate = hist_cxl / hist_total if hist_total > 0 else 0
        net_rn = int(rn * (1 - cancel_rate))
        net_occ = round(net_rn / available * 100, 1) if available > 0 else 0

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
            'net_occ': net_occ,
            'cancel_rate': round(cancel_rate * 100, 1),
            'stly_occ': stly_occ,
            'delta': round(occ - stly_occ, 1),
        }

    def _calc_month_revenue_kpi(self, prop, today):
        """Current month gross & net revenue with STLY comparison."""
        _, days = calendar.monthrange(today.year, today.month)
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year, today.month, days)

        month_qs = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=Reservation.ACTIVE_STATUSES,
        )
        rev = float(month_qs.aggregate(t=Sum('total_amount'))['t'] or 0)

        # Estimate commission from channel mix
        commission = 0.0
        for r in month_qs.select_related('channel').values('total_amount', 'channel__commission_percent'):
            amt = float(r['total_amount'] or 0)
            pct = float(r['channel__commission_percent'] or 0)
            commission += amt * pct / 100
        net_rev = round(rev - commission, 2)

        # STLY
        stly_start = date(today.year - 1, today.month, 1)
        _, stly_days = calendar.monthrange(today.year - 1, today.month)
        stly_end = date(today.year - 1, today.month, stly_days)
        stly_rev = float(Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=stly_start,
            arrival_date__lte=stly_end,
            status__in=Reservation.ACTIVE_STATUSES,
        ).aggregate(t=Sum('total_amount'))['t'] or 0)

        delta_pct = round((rev - stly_rev) / stly_rev * 100, 1) if stly_rev > 0 else 0

        return {
            'revenue': rev,
            'net_revenue': net_rev,
            'commission': round(commission, 2),
            'stly_revenue': stly_rev,
            'delta_pct': delta_pct,
        }

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

    def _calc_revpar_kpi(self, prop, today, total_rooms):
        """RevPAR for next 90 days: revenue / available room-nights."""
        window_end = today + timedelta(days=90)
        stats = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=today,
            arrival_date__lt=window_end,
            status__in=Reservation.FUTURE_STATUSES,
        ).aggregate(rev=Sum('total_amount'))
        rev = float(stats['rev'] or 0)
        available = total_rooms * 90
        revpar = round(rev / available, 2) if available > 0 else 0

        # STLY
        stly_start = date(today.year - 1, today.month, today.day)
        stly_end = stly_start + timedelta(days=90)
        stly_stats = Reservation.objects.filter(
            hotel=prop,
            arrival_date__gte=stly_start,
            arrival_date__lt=stly_end,
            status__in=Reservation.ACTIVE_STATUSES,
        ).aggregate(rev=Sum('total_amount'))
        stly_rev = float(stly_stats['rev'] or 0)
        stly_revpar = round(stly_rev / available, 2) if available > 0 else 0

        return {
            'revpar': revpar,
            'stly_revpar': stly_revpar,
            'delta': round(revpar - stly_revpar, 2),
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


