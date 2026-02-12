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
                occupancy=2,
                apply_ceiling=True,
                ceiling_increment=5
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
                    occupancy=2,
                    apply_ceiling=True,
                    ceiling_increment=5
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


