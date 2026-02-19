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
    Property dashboard - main landing page for a property.
    
    Includes:
    - Quick stats (rooms, seasons, channels, rate plans)
    - Rate parity summary
    - Recent reservations
    - Revenue forecast (via AJAX)
    """
    template_name = 'pricing/core/property_dashboard.html'
    
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

        # Monthly Revenue & Occupancy Snapshot (next 12 months)
        today = date.today()
        total_rooms = sum(rt.number_of_rooms for rt in qs['rooms'])
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
                status__in=['confirmed', 'checked_in', 'checked_out']
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
            adr = round(rev / rn, 2) if rn > 0 else 0

            monthly_snapshot.append({
                'month_name': month_start.strftime('%b'),
                'month_full': month_start.strftime('%B %Y'),
                'year': y,
                'month': m,
                'revenue': rev,
                'room_nights': rn,
                'available': available,
                'occupancy': occ,
                'adr': adr,
                'bookings': bk,
            })
            snapshot_totals['revenue'] += rev
            snapshot_totals['room_nights'] += rn
            snapshot_totals['available'] += available
            snapshot_totals['bookings'] += bk

        snapshot_totals['occupancy'] = round(
            snapshot_totals['room_nights'] / snapshot_totals['available'] * 100, 1
        ) if snapshot_totals['available'] > 0 else 0
        snapshot_totals['adr'] = round(
            snapshot_totals['revenue'] / snapshot_totals['room_nights'], 2
        ) if snapshot_totals['room_nights'] > 0 else 0

        context['monthly_snapshot'] = monthly_snapshot
        context['snapshot_totals'] = snapshot_totals
        context['total_rooms'] = total_rooms
        context['snapshot_json'] = json.dumps(monthly_snapshot)
        context['today_year'] = today.year
        context['today_month'] = today.month

        return context
    


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


