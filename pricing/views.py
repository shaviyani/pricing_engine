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
from django.http import HttpResponse

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View, ListView
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from io import BytesIO
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.widgets.markers import makeMarker
import calendar

from .models import (
    Organization, Property,
    Season, RoomType, RatePlan, Channel, RateModifier, SeasonModifierOverride,
    Reservation,
)
from .services import (
    BookingAnalysisService,
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

class PricingMatrixView(PropertyMixin, TemplateView):
    """
    Pricing matrix showing all rate combinations.
    
    Room-centric display structure:
    - Room as main collapsible row
    - Channels as sub-rows with B&B Standard rate summary
    - Rate Plans & Modifiers as expandable detail
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
        
        # Find B&B rate plan for summary display
        bb_rate_plan = self._find_bb_rate_plan(rate_plans)
        
        # Build room-centric matrix
        matrix = self._build_matrix(prop, seasons, rooms, rate_plans, channels, bb_rate_plan)
        
        context['seasons'] = seasons
        context['selected_season'] = selected_season
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        context['bb_rate_plan'] = bb_rate_plan
        
        return context
    
    def _find_bb_rate_plan(self, rate_plans):
        """Find the Bed & Breakfast rate plan."""
        bb_rate_plan = rate_plans.filter(name__icontains='bed & breakfast').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.filter(name__icontains='b&b').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.filter(name__icontains='breakfast').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.first()
        return bb_rate_plan
    
    def _find_standard_modifier(self, modifiers):
        """Find the Standard modifier (0% discount)."""
        standard_modifier = modifiers.filter(discount_percent=0).first()
        if not standard_modifier:
            standard_modifier = modifiers.filter(name__icontains='standard').first()
        if not standard_modifier:
            standard_modifier = modifiers.first()
        return standard_modifier
    
    def _build_matrix(self, prop, seasons, rooms, rate_plans, channels, bb_rate_plan):
        """
        Build room-centric pricing matrix.
        """
        matrix = {}
        
        for room in rooms:
            matrix[room.id] = {
                'room': room,
                'channels': {}
            }
            
            for channel in channels:
                # Get active modifiers for this channel
                modifiers = RateModifier.objects.filter(
                    channel=channel,
                    active=True
                ).order_by('sort_order')
                
                # Find Standard modifier for summary
                standard_modifier = self._find_standard_modifier(modifiers)
                
                channel_data = {
                    'channel': channel,
                    'summary_rates': {},
                    'rate_plans': {}
                }
                
                for rate_plan in rate_plans:
                    rate_plan_data = {
                        'rate_plan': rate_plan,
                        'bar_rates': {},
                        'modifiers': []
                    }
                    
                    # Calculate rates for each modifier across all seasons
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        for season in seasons:
                            season_discount = modifier.get_discount_for_season(season)
                            
                            # CHANGED: Use calculate_final_rate with ceiling
                            final_rate, breakdown = calculate_final_rate(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2,
                                apply_ceiling=True,
                                ceiling_increment=5
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                            
                            # Store BAR rate (from breakdown)
                            if season.id not in rate_plan_data['bar_rates']:
                                rate_plan_data['bar_rates'][season.id] = breakdown['bar_rate']
                            
                            # Capture B&B Standard rate for channel summary
                            if rate_plan == bb_rate_plan and modifier == standard_modifier:
                                channel_data['summary_rates'][season.id] = final_rate
                        
                        rate_plan_data['modifiers'].append(modifier_data)
                    
                    channel_data['rate_plans'][rate_plan.id] = rate_plan_data
                
                matrix[room.id]['channels'][channel.id] = channel_data
        
        return matrix

class PricingMatrixPDFView(PropertyMixin, View):
    """
    Export pricing matrix as PDF.
    
    URL: /org/{org_code}/{prop_code}/pricing/matrix/pdf/
    """
    
    def get(self, request, *args, **kwargs):
        # Get property using PropertyMixin pattern
        prop = self.get_property()
        org = prop.organization
        
        # Get property-scoped data
        qs = self.get_property_querysets(prop)
        seasons = list(qs['seasons'])
        rooms = list(qs['rooms'])
        rate_plans = list(qs['rate_plans'])
        channels = list(qs['channels'])
        
        if not all([seasons, rooms, rate_plans, channels]):
            return HttpResponse("No data available for PDF export", status=400)
        
        # Find B&B rate plan
        bb_rate_plan = self._find_bb_rate_plan(rate_plans)
        
        # Build matrix data
        matrix = self._build_matrix_data(seasons, rooms, rate_plans, channels, bb_rate_plan)
        
        # Generate PDF
        pdf_buffer = self._generate_pdf(prop, org, seasons, rooms, channels, rate_plans, matrix, bb_rate_plan)
        
        # Return PDF response
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        filename = f"pricing_matrix_{prop.code}_{timezone.now().strftime('%Y%m%d')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
    
    def get_property(self):
        """Get property from URL kwargs."""
        from pricing.models import Property
        org_code = self.kwargs.get('org_code')
        prop_code = self.kwargs.get('prop_code')
        return Property.objects.select_related('organization').get(
            organization__code=org_code,
            code=prop_code,
            is_active=True
        )
    
    def get_property_querysets(self, prop):
        """Get property-scoped querysets."""
        from pricing.models import Season, RoomType, RatePlan, Channel
        return {
            'seasons': Season.objects.filter(hotel=prop).order_by('start_date'),
            'rooms': RoomType.objects.filter(hotel=prop).order_by('sort_order', 'name'),
            'rate_plans': RatePlan.objects.all().order_by('sort_order', 'name'),
            'channels': Channel.objects.all().order_by('sort_order', 'name'),
        }
    
    def _find_bb_rate_plan(self, rate_plans):
        """Find the Bed & Breakfast rate plan."""
        for rp in rate_plans:
            if 'bed & breakfast' in rp.name.lower():
                return rp
            if 'b&b' in rp.name.lower():
                return rp
            if 'breakfast' in rp.name.lower():
                return rp
        return rate_plans[0] if rate_plans else None
    
    def _find_standard_modifier(self, modifiers):
        """Find the Standard modifier (0% discount)."""
        for mod in modifiers:
            if mod.discount_percent == 0:
                return mod
            if 'standard' in mod.name.lower():
                return mod
        return modifiers[0] if modifiers else None
    
    def _build_matrix_data(self, seasons, rooms, rate_plans, channels, bb_rate_plan):
        """Build matrix data structure for PDF."""
        from pricing.models import RateModifier
        from pricing.services import calculate_final_rate
        
        matrix = {}
        
        for room in rooms:
            matrix[room.id] = {
                'room': room,
                'channels': {}
            }
            
            for channel in channels:
                modifiers = list(RateModifier.objects.filter(
                    channel=channel,
                    active=True
                ).order_by('sort_order'))
                
                standard_modifier = self._find_standard_modifier(modifiers)
                
                channel_data = {
                    'channel': channel,
                    'summary_rates': {},
                    'rate_plans': {}
                }
                
                for rate_plan in rate_plans:
                    rate_plan_data = {
                        'rate_plan': rate_plan,
                        'bar_rates': {},
                        'modifiers': []
                    }
                    
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        for season in seasons:
                            season_discount = modifier.get_discount_for_season(season)
                            
                            # CHANGED: Use calculate_final_rate with ceiling
                            final_rate, breakdown = calculate_final_rate(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2,
                                apply_ceiling=True,
                                ceiling_increment=5
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                            
                            if season.id not in rate_plan_data['bar_rates']:
                                rate_plan_data['bar_rates'][season.id] = breakdown['bar_rate']
                            
                            if rate_plan == bb_rate_plan and modifier == standard_modifier:
                                channel_data['summary_rates'][season.id] = final_rate
                        
                        rate_plan_data['modifiers'].append(modifier_data)
                    
                    channel_data['rate_plans'][rate_plan.id] = rate_plan_data
                
                matrix[room.id]['channels'][channel.id] = channel_data
        
        return matrix
    
    def _generate_pdf(self, prop, org, seasons, rooms, channels, rate_plans, matrix, bb_rate_plan):
        """Generate the PDF document."""
        buffer = BytesIO()
        
        # Use landscape A4 for wider tables
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=15*mm,
            leftMargin=15*mm,
            topMargin=15*mm,
            bottomMargin=15*mm
        )
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=6,
            textColor=colors.HexColor('#1e3a5f')
        )
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            spaceAfter=12
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=12,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor('#2563eb')
        )
        
        story = []
        
        # Title
        story.append(Paragraph(f"Pricing Matrix - {prop.name}", title_style))
        story.append(Paragraph(
            f"{org.name} | Generated: {timezone.now().strftime('%B %d, %Y at %H:%M')}",
            subtitle_style
        ))
        story.append(Spacer(1, 6*mm))
        
        # Summary Table (B&B Standard rates by Room x Channel x Season)
        story.append(Paragraph("Summary: B&B Standard Rates", section_style))
        summary_table = self._build_summary_table(seasons, rooms, channels, matrix)
        story.append(summary_table)
        
        # Rate Parity Charts
        story.append(Spacer(1, 10*mm))
        story.append(Paragraph("Rate Parity Analysis", section_style))
        story.append(Paragraph(
            "Visual comparison of B&B Standard rates across channels",
            subtitle_style
        ))
        story.append(Spacer(1, 4*mm))
        
        for room in rooms:
            chart = self._build_parity_chart(room, seasons, channels, matrix)
            if chart:
                story.append(chart)
                story.append(Spacer(1, 6*mm))
        
        # Detailed breakdown per room
        for room in rooms:
            room_data = matrix.get(room.id)
            if not room_data:
                continue
            
            story.append(PageBreak())
            story.append(Paragraph(f"{room.name} - Detailed Rates", section_style))
            story.append(Paragraph(
                f"Base Rate: ${room.base_rate:.2f} | Rooms: {room.number_of_rooms}",
                subtitle_style
            ))
            
            first_channel = True
            for channel in channels:
                channel_data = room_data['channels'].get(channel.id)
                if not channel_data:
                    continue
                
                # Page break before each new channel (except first)
                if not first_channel:
                    story.append(PageBreak())
                    story.append(Paragraph(f"{room.name} - Detailed Rates (continued)", section_style))
                first_channel = False
                
                story.append(Spacer(1, 4*mm))
                channel_info = f"{channel.name}"
                if channel.base_discount_percent > 0:
                    channel_info += f" (-{channel.base_discount_percent}% discount)"
                if channel.commission_percent > 0:
                    channel_info += f" ({channel.commission_percent}% commission)"
                
                story.append(Paragraph(channel_info, styles['Heading3']))
                
                detail_table = self._build_detail_table(
                    seasons, rate_plans, channel_data, channel
                )
                story.append(detail_table)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        return buffer
    
    def _build_parity_chart(self, room, seasons, channels, matrix):
        """
        Build rate parity line chart for a single room type.
        Shows B&B Standard rates across channels for each season.
        """
        # Chart dimensions
        chart_width = 700
        chart_height = 200
        
        drawing = Drawing(chart_width, chart_height)
        
        room_data = matrix.get(room.id)
        if not room_data:
            return None
        
        # Create line chart
        chart = HorizontalLineChart()
        chart.x = 70
        chart.y = 45
        chart.width = chart_width - 140
        chart.height = chart_height - 90
        
        # Build data series - one per channel
        data = []
        channel_names = []
        
        for channel in channels:
            channel_data = room_data['channels'].get(channel.id)
            if not channel_data:
                continue
            
            channel_names.append(channel.name)
            series = []
            
            for season in seasons:
                rate = channel_data['summary_rates'].get(season.id)
                if rate:
                    series.append(float(rate))
                else:
                    series.append(0)
            
            data.append(series)
        
        if not data:
            return None
        
        chart.data = data
        
        # Category axis (seasons)
        chart.categoryAxis.categoryNames = [s.name for s in seasons]
        chart.categoryAxis.labels.fontName = 'Helvetica'
        chart.categoryAxis.labels.fontSize = 8
        
        # Value axis
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labels.fontName = 'Helvetica'
        chart.valueAxis.labels.fontSize = 8
        chart.valueAxis.labelTextFormat = '$%.0f'
        chart.valueAxis.gridStrokeColor = colors.HexColor('#e5e7eb')
        chart.valueAxis.gridStrokeWidth = 0.5
        chart.valueAxis.visibleGrid = 1
        
        # Line colors and styles
        line_colors = [
            colors.HexColor('#3b82f6'),  # Blue - OTA
            colors.HexColor('#10b981'),  # Green - Direct
            colors.HexColor('#f59e0b'),  # Amber - Agent
            colors.HexColor('#8b5cf6'),  # Purple
            colors.HexColor('#ef4444'),  # Red
        ]
        
        for i in range(len(channel_names)):
            color_idx = i % len(line_colors)
            chart.lines[i].strokeColor = line_colors[color_idx]
            chart.lines[i].strokeWidth = 2
            chart.lines[i].symbol = makeMarker('Circle')
            chart.lines[i].symbol.fillColor = line_colors[color_idx]
            chart.lines[i].symbol.strokeColor = colors.white
            chart.lines[i].symbol.strokeWidth = 1
            chart.lines[i].symbol.size = 6
        
        drawing.add(chart)
        
        # Add title
        title = String(
            chart_width / 2, 
            chart_height - 12,
            f'{room.name} - B&B Standard Rate Parity',
            fontSize=10,
            fontName='Helvetica-Bold',
            textAnchor='middle'
        )
        drawing.add(title)
        
        # Add legend (horizontal at bottom)
        legend = Legend()
        legend.x = chart.x + 80
        legend.y = 8
        legend.dx = 8
        legend.dy = 8
        legend.fontName = 'Helvetica'
        legend.fontSize = 8
        legend.boxAnchor = 'sw'
        legend.columnMaximum = 1
        legend.strokeWidth = 0
        legend.deltax = 90
        legend.alignment = 'right'
        
        legend_items = []
        for i, channel_name in enumerate(channel_names):
            color_idx = i % len(line_colors)
            legend_items.append((line_colors[color_idx], channel_name))
        
        legend.colorNamePairs = legend_items
        drawing.add(legend)
        
        return drawing
    
    def _build_summary_table(self, seasons, rooms, channels, matrix):
        """Build summary table with B&B Standard rates."""
        # Header row with season name, date range, and multiplier
        header = ['Room / Channel']
        for s in seasons:
            # Format: "Peak\nJan 01 - Mar 31\n×1.30"
            date_range = f"{s.start_date.strftime('%b %d')} - {s.end_date.strftime('%b %d')}"
            header.append(f"{s.name}\n{date_range}\n×{s.season_index}")
        
        data = [header]
        
        for room in rooms:
            room_data = matrix.get(room.id)
            if not room_data:
                continue
            
            # Room header row
            room_row = [Paragraph(f"<b>{room.name}</b>", getSampleStyleSheet()['Normal'])]
            room_row.extend([''] * len(seasons))
            data.append(room_row)
            
            # Channel rows
            for channel in channels:
                channel_data = room_data['channels'].get(channel.id)
                if not channel_data:
                    continue
                
                row = [f"  {channel.name}"]
                for season in seasons:
                    rate = channel_data['summary_rates'].get(season.id)
                    if rate:
                        row.append(f"${rate:.2f}")
                    else:
                        row.append('-')
                data.append(row)
        
        # Calculate column widths to fill page width
        page_width = landscape(A4)[0]  # 842 points
        total_margins = 30 * mm  # 15mm left + 15mm right
        available_width = page_width - total_margins
        
        first_col_width = 140  # Room/Channel names
        remaining_width = available_width - first_col_width
        season_col_width = remaining_width / len(seasons) if seasons else 90
        
        col_widths = [first_col_width] + [season_col_width] * len(seasons)
        table = Table(data, colWidths=col_widths)
        
        # Style
        style = TableStyle([
            # Header - with extra padding for multi-line content
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('LEADING', (0, 0), (-1, 0), 10),  # Line spacing for multi-line header
            
            # Body
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ])
        
        # Highlight room header rows
        row_idx = 1
        for room in rooms:
            style.add('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#e0e7ff'))
            style.add('FONTNAME', (0, row_idx), (0, row_idx), 'Helvetica-Bold')
            row_idx += 1 + len(channels)
        
        table.setStyle(style)
        return table
    
    def _build_detail_table(self, seasons, rate_plans, channel_data, channel):
        """Build detailed rate table for a room/channel combination."""
        # Header
        header = ['Rate Plan / Modifier'] + [s.name for s in seasons]
        data = [header]
        
        for rate_plan_id, rp_data in channel_data['rate_plans'].items():
            rate_plan = rp_data['rate_plan']
            
            # Rate plan header
            rp_name = rate_plan.name
            if rate_plan.meal_supplement > 0:
                rp_name += f" (+${rate_plan.meal_supplement:.2f}/person)"
            
            rp_row = [Paragraph(f"<b>{rp_name}</b>", getSampleStyleSheet()['Normal'])]
            rp_row.extend([''] * len(seasons))
            data.append(rp_row)
            
            # BAR row
            bar_row = ['  BAR']
            for season in seasons:
                bar = rp_data['bar_rates'].get(season.id)
                if bar:
                    bar_row.append(f"${bar:.2f}")
                else:
                    bar_row.append('-')
            data.append(bar_row)
            
            # Modifier rows
            for mod_data in rp_data['modifiers']:
                modifier = mod_data['modifier']
                mod_name = f"  {modifier.name}"
                if modifier.discount_percent > 0:
                    mod_name += f" (-{modifier.discount_percent}%)"
                
                mod_row = [mod_name]
                for season in seasons:
                    season_data = mod_data['seasons'].get(season.id)
                    if season_data:
                        rate = season_data['rate']
                        if channel.commission_percent > 0:
                            net = season_data['breakdown'].get('net_revenue', rate)
                            mod_row.append(f"${rate:.2f}\n(Net: ${net:.2f})")
                        else:
                            mod_row.append(f"${rate:.2f}")
                    else:
                        mod_row.append('-')
                data.append(mod_row)
        
        # Calculate column widths to fill page width
        page_width = landscape(A4)[0]  # 842 points
        total_margins = 30 * mm  # 15mm left + 15mm right
        available_width = page_width - total_margins
        
        first_col_width = 160  # Rate Plan / Modifier names
        remaining_width = available_width - first_col_width
        season_col_width = remaining_width / len(seasons) if seasons else 90
        
        col_widths = [first_col_width] + [season_col_width] * len(seasons)
        table = Table(data, colWidths=col_widths)
        
        # Style
        style = TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Body
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ])
        
        # Find and style rate plan header rows
        row_idx = 1
        for rate_plan_id, rp_data in channel_data['rate_plans'].items():
            style.add('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#dbeafe'))
            num_modifiers = len(rp_data['modifiers'])
            row_idx += 2 + num_modifiers  # header + BAR + modifiers
        
        table.setStyle(style)
        return table
    
    
class PricingMatrixChannelView(PropertyMixin, TemplateView):
    """
    Channel-centric pricing matrix.
    
    Structure:
    - Channel as main collapsible row
    - Rooms as sub-rows with B&B Standard rate
    - Rate Plans & Modifiers as expandable detail
    """
    template_name = 'pricing/matrix_channel.html'
    
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
        
        # Find B&B rate plan for summary display
        bb_rate_plan = self._find_bb_rate_plan(rate_plans)
        
        # Build channel-centric matrix
        matrix = self._build_channel_matrix(prop, seasons, rooms, rate_plans, channels, bb_rate_plan)
        
        context['seasons'] = seasons
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        context['bb_rate_plan'] = bb_rate_plan
        
        return context
    
    def _find_bb_rate_plan(self, rate_plans):
        """Find the Bed & Breakfast rate plan."""
        bb_rate_plan = rate_plans.filter(name__icontains='bed & breakfast').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.filter(name__icontains='b&b').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.filter(name__icontains='breakfast').first()
        if not bb_rate_plan:
            bb_rate_plan = rate_plans.first()
        return bb_rate_plan
    
    def _find_standard_modifier(self, modifiers):
        """Find the Standard modifier (0% discount)."""
        standard_modifier = modifiers.filter(discount_percent=0).first()
        if not standard_modifier:
            standard_modifier = modifiers.filter(name__icontains='standard').first()
        if not standard_modifier:
            standard_modifier = modifiers.first()
        return standard_modifier
    
    def _build_channel_matrix(self, prop, seasons, rooms, rate_plans, channels, bb_rate_plan):
        """
        Build channel-centric pricing matrix.
        
        Structure: matrix[channel_id] = {
            'channel': Channel object,
            'rooms': {
                room_id: {
                    'room': Room object,
                    'summary_rates': {season_id: rate},  # B&B Standard
                    'rate_plans': {
                        rate_plan_id: {
                            'rate_plan': RatePlan object,
                            'bar_rates': {season_id: rate},
                            'modifiers': [{
                                'modifier': RateModifier,
                                'seasons': {season_id: {'rate', 'breakdown'}}
                            }]
                        }
                    }
                }
            }
        }
        """
        from pricing.services import calculate_final_rate
        
        matrix = {}
        
        for channel in channels:
            # Get active modifiers for this channel
            modifiers = RateModifier.objects.filter(
                channel=channel,
                active=True
            ).order_by('sort_order')
            
            # Find Standard modifier for summary
            standard_modifier = self._find_standard_modifier(modifiers)
            
            matrix[channel.id] = {
                'channel': channel,
                'rooms': {}
            }
            
            for room in rooms:
                room_data = {
                    'room': room,
                    'summary_rates': {},  # B&B Standard rates per season
                    'rate_plans': {}
                }
                
                for rate_plan in rate_plans:
                    rate_plan_data = {
                        'rate_plan': rate_plan,
                        'bar_rates': {},
                        'modifiers': []
                    }
                    
                    # Calculate rates for each modifier across all seasons
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        for season in seasons:
                            season_discount = modifier.get_discount_for_season(season)
                            
                            final_rate, breakdown = calculate_final_rate(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2,
                                apply_ceiling=True,
                                ceiling_increment=5
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                            
                            # Store BAR rate (from breakdown)
                            if season.id not in rate_plan_data['bar_rates']:
                                rate_plan_data['bar_rates'][season.id] = breakdown['bar_rate']
                            
                            # Capture B&B Standard rate for room summary
                            if rate_plan == bb_rate_plan and modifier == standard_modifier:
                                room_data['summary_rates'][season.id] = final_rate
                        
                        rate_plan_data['modifiers'].append(modifier_data)
                    
                    room_data['rate_plans'][rate_plan.id] = rate_plan_data
                
                matrix[channel.id]['rooms'][room.id] = room_data
        
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


