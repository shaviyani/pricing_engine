"""
Pricing views: Matrix display, PDF export, Channel matrix,
Date Rate Override Calendar, and pricing AJAX endpoints.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from django.db import models, transaction
from dateutil.relativedelta import relativedelta
import calendar
import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.widgets.markers import makeMarker

from pricing.models import (
    Organization, Property, Season, RoomType, RatePlan, Channel,
    TravelAgent, RateModifier, SeasonModifierOverride, Reservation,
    DateRateOverride, DateRateOverridePeriod,
    PropertyModifier, ModifierRule,
    PricingMatrixVersion,
)
from pricing.services import PricingService

from .mixins import OrganizationMixin, PropertyMixin

logger = logging.getLogger(__name__)

class PricingMatrixView(PropertyMixin, TemplateView):
    """
    Pricing Matrix with expandable channel sections showing PropertyModifier breakdowns.

    Uses PricingService (unified modifier system) for all rate calculations.
    Each channel section expands to show BAR, channel base rate, and each
    applicable PropertyModifier's contribution.
    """
    template_name = 'pricing/pricing_pages/matrix.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'pricing'
        context['nav_sub'] = 'matrix'

        from pricing.models import (
            Property, Season, RoomType, Channel, RatePlan,
            PricingMatrixVersion
        )
        from decimal import ROUND_HALF_UP

        # View mode: 'season' (default) or 'channel'
        view_mode = self.request.GET.get('view', 'season')
        if view_mode not in ('season', 'channel'):
            view_mode = 'season'
        context['view_mode'] = view_mode

        # Get property from URL
        org_code = self.kwargs.get('org_code')
        prop_code = self.kwargs.get('prop_code')

        hotel = get_object_or_404(
            Property.objects.select_related('organization'),
            organization__code=org_code,
            code=prop_code,
            is_active=True
        )

        context['hotel'] = hotel
        context['org_code'] = org_code
        context['prop_code'] = prop_code

        # Get published version
        version = PricingMatrixVersion.get_published(hotel)
        context['pricing_version'] = version

        # Get filter parameters
        room_type_id = self.request.GET.get('room_type_id', 'all')
        rate_plan_id = self.request.GET.get('rate_plan_id')
        pax = int(self.request.GET.get('pax', 2))
        channel_id = self.request.GET.get('channel_id', 'all')

        # Get all entities (version-scoped)
        version_filter = {'hotel': hotel}
        if version:
            version_filter['version'] = version

        seasons = Season.objects.filter(**version_filter).order_by('start_date')
        room_types = RoomType.objects.filter(**version_filter).order_by('sort_order')
        channels = Channel.objects.filter(**version_filter).order_by('sort_order')
        rate_plans = RatePlan.objects.filter(**version_filter).order_by('sort_order')

        # Store all channels for the filter dropdown, then filter if specific channel selected
        all_channels = Channel.objects.filter(**version_filter).order_by('sort_order')
        selected_channel = None
        if channel_id != 'all':
            try:
                channels = channels.filter(id=int(channel_id))
                selected_channel = channels.first()
            except (ValueError, TypeError):
                pass

        context['seasons'] = seasons
        context['room_types'] = room_types
        context['channels'] = channels
        context['rate_plans'] = rate_plans
        context['all_channels'] = all_channels
        context['selected_channel'] = selected_channel
        context['pax'] = pax

        # Determine if showing all rooms or single room
        show_all_rooms = (room_type_id == 'all' or room_type_id == '')
        context['show_all_rooms'] = show_all_rooms

        # Get selected room type (for single room view)
        if not show_all_rooms:
            try:
                selected_room = room_types.filter(id=int(room_type_id)).first()
            except (ValueError, TypeError):
                selected_room = room_types.first()
        else:
            selected_room = None

        context['selected_room'] = selected_room

        # Get selected rate plan
        if rate_plan_id:
            selected_rate_plan = rate_plans.filter(id=rate_plan_id).first()
        else:
            selected_rate_plan = rate_plans.first()

        context['selected_rate_plan'] = selected_rate_plan

        if not seasons.exists() or not channels.exists() or not room_types.exists():
            context['has_data'] = False
            return context

        context['has_data'] = True

        meal_supplement = selected_rate_plan.meal_supplement if selected_rate_plan else Decimal('0.00')

        # =====================================================================
        # Unified pricing via PricingService (PropertyModifier system)
        # =====================================================================
        pricing_svc = PricingService(hotel, version=version)
        sc_pct = pricing_svc.service_charge_percent
        tax_pct = pricing_svc.tax_percent
        tax_on_sc = pricing_svc.tax_on_service_charge

        def _add_service_tax(subtotal):
            """Calculate service charge + tax on a subtotal."""
            svc = (subtotal * sc_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            tax_base = (subtotal + svc) if tax_on_sc else subtotal
            tax = (tax_base * tax_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return float((subtotal + svc + tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        # Build channel_modifiers dict: channel_id -> list of PropertyModifiers
        # that apply to that channel (for display in expandable section)
        channel_modifiers = {}
        for channel in channels:
            ctx = {'channel': channel, 'channel_id': channel.id}
            mods = [m for m in pricing_svc.get_applicable_modifiers(ctx)
                    if m.applies_to not in ('season', 'room_type')]
            channel_modifiers[channel.id] = mods

        context['channel_modifiers'] = channel_modifiers

        def calculate_modifier_rates(room, channel, season, meal_supplement, pax):
            """
            Calculate rates using PricingService.
            Returns dict compatible with template (bar_rate, channel_base_rate, modifier_rates).
            """
            base_rate = room.get_effective_base_rate()
            rt_season_mod = room.get_season_modifier(season)
            effective_index = season.season_index * rt_season_mod
            seasonal_rate = (base_rate * effective_index).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # BAR = seasonal rate + meals
            meal_total = meal_supplement * pax
            bar_subtotal = seasonal_rate + meal_total

            # Full calculation with all applicable modifiers via PricingService
            modifier_context = {
                'season': season, 'season_id': season.id,
                'room_type': room, 'room_type_id': room.id,
                'channel': channel, 'channel_id': channel.id,
            }
            all_modifiers = pricing_svc.get_applicable_modifiers(modifier_context)
            result = pricing_svc.calculate_rate(
                bar_rate=base_rate * effective_index,
                modifiers=all_modifiers,
                meal_plan_amount=meal_supplement,
                pax=pax,
            )

            # Channel base = rate with only season/room modifiers (no channel/promo/etc)
            base_modifiers = [m for m in all_modifiers if m.applies_to in ('season', 'room_type')]
            base_result = pricing_svc.calculate_rate(
                bar_rate=base_rate * effective_index,
                modifiers=base_modifiers,
                meal_plan_amount=meal_supplement,
                pax=pax,
            )

            # Per-modifier breakdown: show what rate would be with base + each individual modifier
            modifier_rates = []
            for mod in all_modifiers:
                if mod.applies_to in ('season', 'room_type'):
                    continue  # Already in base
                individual_mods = base_modifiers + [mod]
                ind_result = pricing_svc.calculate_rate(
                    bar_rate=base_rate * effective_index,
                    modifiers=individual_mods,
                    meal_plan_amount=meal_supplement,
                    pax=pax,
                )
                modifier_rates.append({
                    'modifier_id': mod.id,
                    'modifier_name': mod.name,
                    'modifier_type': mod.applies_to,
                    'discount_percent': float(abs(mod.get_adjustment()) * Decimal('100')),
                    'subtotal': float(ind_result['subtotal']),
                    'final_rate': float(ind_result['final_rate']),
                    'is_stacked': False,
                })

            return {
                'bar_rate': _add_service_tax(bar_subtotal),
                'bar_subtotal': float(bar_subtotal),
                'channel_base_rate': float(base_result['final_rate']),
                'channel_base_subtotal': float(base_result['subtotal']),
                'modifier_rates': modifier_rates,
            }

        if view_mode == 'channel':
            # =================================================================
            # Channel View: channel-centric matrix
            # =================================================================
            bb_rate_plan = rate_plans.filter(name__icontains='bed & breakfast').first()
            if not bb_rate_plan:
                bb_rate_plan = rate_plans.filter(name__icontains='b&b').first()
            if not bb_rate_plan:
                bb_rate_plan = rate_plans.filter(name__icontains='breakfast').first()
            if not bb_rate_plan:
                bb_rate_plan = rate_plans.first()
            context['bb_rate_plan'] = bb_rate_plan

            channel_matrix = {}
            for channel in channels:
                channel_matrix[channel.id] = {
                    'channel': channel,
                    'rooms': {},
                }
                for room in room_types:
                    room_data = {
                        'room': room,
                        'summary_rates': {},
                        'rate_plans': {},
                    }
                    for rate_plan in rate_plans:
                        rp_data = {
                            'rate_plan': rate_plan,
                            'bar_rates': {},
                            'channel_rate': {},
                        }
                        for season in seasons:
                            base_rate = room.get_effective_base_rate()
                            effective_index = float(season.season_index)
                            bar_subtotal = float(base_rate) * effective_index
                            rp_meal = float(rate_plan.meal_supplement) * pax

                            modifier_context = {
                                'season': season, 'season_id': season.id,
                                'room_type': room, 'room_type_id': room.id,
                                'channel': channel, 'channel_id': channel.id,
                            }
                            all_modifiers = pricing_svc.get_applicable_modifiers(modifier_context)
                            result = pricing_svc.calculate_rate(
                                bar_rate=bar_subtotal,
                                modifiers=all_modifiers,
                                meal_plan_amount=rp_meal,
                                pax=pax,
                            )
                            rp_data['channel_rate'][season.id] = float(result['final_rate'])

                            if season.id not in rp_data['bar_rates']:
                                base_mods = [m for m in all_modifiers if m.applies_to in ('season', 'room_type')]
                                bar_result = pricing_svc.calculate_rate(
                                    bar_rate=bar_subtotal,
                                    modifiers=base_mods,
                                    meal_plan_amount=rp_meal,
                                    pax=pax,
                                )
                                rp_data['bar_rates'][season.id] = float(bar_result['final_rate'])

                            if rate_plan == bb_rate_plan:
                                room_data['summary_rates'][season.id] = float(result['final_rate'])

                        room_data['rate_plans'][rate_plan.id] = rp_data
                    channel_matrix[channel.id]['rooms'][room.id] = room_data

            context['matrix'] = channel_matrix
            return context

        # =====================================================================
        # Season View (default): room/channel matrix with modifier breakdowns
        # =====================================================================
        if show_all_rooms:
            # Build matrix for ALL rooms: matrix[room_id][channel_id][season_id] = rate_data
            matrix = {}

            for room in room_types:
                matrix[room.id] = {}

                for channel in channels:
                    matrix[room.id][channel.id] = {}

                    for season in seasons:
                        rate_data = calculate_modifier_rates(
                            room, channel, season, meal_supplement, pax
                        )
                        matrix[room.id][channel.id][season.id] = rate_data
        else:
            # Build matrix for SINGLE room: matrix[channel_id][season_id] = rate_data
            matrix = {}

            for channel in channels:
                matrix[channel.id] = {}

                for season in seasons:
                    rate_data = calculate_modifier_rates(
                        selected_room, channel, season, meal_supplement, pax
                    )
                    matrix[channel.id][season.id] = rate_data

        context['matrix'] = matrix

        # All channels collapsed by default
        context['default_expanded_channel'] = None

        # =====================================================================
        # Room Type Season Modifiers - build lookup for template display
        # =====================================================================
        from pricing.models import RoomTypeSeasonModifier

        rt_season_mods = {}  # {room_id: {season_id: modifier_value}}
        all_mods = RoomTypeSeasonModifier.objects.filter(
            room_type__hotel=hotel
        ).select_related('room_type', 'season')

        for mod in all_mods:
            rt_season_mods.setdefault(mod.room_type_id, {})[mod.season_id] = float(mod.modifier)

        context['rt_season_mods'] = rt_season_mods

        # =====================================================================
        # "All Rooms" Comparison Table
        # Build a compact summary: per room type, key rates for each season
        # =====================================================================
        if show_all_rooms:
            comparison_data = []
            # Find "key" channels for comparison: first channel (usually OTA) and Direct
            key_channels = []
            for ch in channels:
                if ch.name.lower().startswith('direct') or ch.base_discount_percent == Decimal('0.00'):
                    key_channels.append(ch)
                elif not key_channels:
                    key_channels.append(ch)  # first channel as fallback
            # Ensure at least 1 and at most 3 key channels
            if len(key_channels) == 0 and channels.exists():
                key_channels = [channels.first()]
            key_channels = key_channels[:3]

            for room in room_types:
                room_row = {
                    'room': room,
                    'effective_rate': float(room.get_effective_base_rate()),
                    'premium_percent': float(room.get_premium_percent()),
                    'target_occupancy': float(room.target_occupancy),
                    'description': room.description,
                    'seasons': {},
                }
                for season in seasons:
                    rt_mod = room.get_season_modifier(season)
                    eff_idx = float(season.season_index * rt_mod)
                    season_rates = {
                        'effective_index': round(eff_idx, 2),
                        'rt_modifier': float(rt_mod),
                        'channels': {},
                    }
                    for ch in key_channels:
                        rate_data = matrix[room.id][ch.id][season.id]
                        season_rates['channels'][ch.id] = {
                            'channel_base_rate': rate_data['channel_base_rate'],
                        }
                    room_row['seasons'][season.id] = season_rates
                comparison_data.append(room_row)

            context['comparison_data'] = comparison_data
            context['comparison_channels'] = key_channels

            # Blended ADR per season
            blended_adr = {}
            for season in seasons:
                total_rooms = hotel.get_total_rooms()
                if total_rooms > 0:
                    weighted_sum = Decimal('0')
                    for room in room_types:
                        eff_rate = room.get_effective_base_rate()
                        rt_mod = room.get_season_modifier(season)
                        seasonal = eff_rate * season.season_index * rt_mod
                        weighted_sum += seasonal * room.number_of_rooms
                    blended_adr[season.id] = float((weighted_sum / total_rooms).quantize(Decimal('0.01')))
                else:
                    blended_adr[season.id] = 0
            context['blended_adr'] = blended_adr

        return context

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
            'rate_plans': RatePlan.objects.filter(hotel=prop).order_by('sort_order', 'name'),
            'channels': Channel.objects.filter(hotel=prop).order_by('sort_order', 'name'),
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
        from pricing.models.core import PropertyModifier
        from decimal import ROUND_HALF_UP

        prop = self.get_property()
        version = PricingMatrixVersion.get_published(prop)
        service = PricingService(prop, version)

        matrix = {}

        for room in rooms:
            matrix[room.id] = {
                'room': room,
                'channels': {}
            }

            for channel in channels:
                # Get PropertyModifiers for this channel
                pm_qs = PropertyModifier.objects.filter(
                    hotel=prop, channel=channel, is_active=True,
                )
                if version:
                    pm_qs = pm_qs.filter(Q(version=version) | Q(version__isnull=True))
                pm_list = list(pm_qs.order_by('stack_order'))

                # Separate base modifiers from additional ones
                base_mods = [m for m in pm_list if m.stack_order < 200]
                extra_mods = [m for m in pm_list if m.stack_order >= 200]

                # If no extra modifiers, use base as the only "modifier column"
                if not extra_mods:
                    modifier_sets = [('base', base_mods)]
                else:
                    modifier_sets = []
                    for em in extra_mods:
                        modifier_sets.append((em.name, base_mods + [em]))
                    # Also add a "base only" set if there are base modifiers
                    if base_mods:
                        modifier_sets.insert(0, ('Standard', base_mods))

                standard_set_name = modifier_sets[0][0] if modifier_sets else 'base'

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

                    for set_name, mod_set in modifier_sets:
                        # Create a pseudo-modifier object for template compatibility
                        class _ModProxy:
                            def __init__(self, name, mods):
                                self.name = name
                                self.id = mods[-1].id if mods else 0
                                self._mods = mods

                        proxy = _ModProxy(set_name, mod_set)
                        modifier_data = {
                            'modifier': proxy,
                            'seasons': {}
                        }

                        for season in seasons:
                            rt_mod = room.get_season_modifier(season)
                            effective_index = season.season_index * rt_mod
                            seasonal_rate = (room.get_effective_base_rate() * effective_index).quantize(
                                Decimal('0.01'), rounding=ROUND_HALF_UP)

                            result = service.calculate_rate(
                                bar_rate=seasonal_rate,
                                modifiers=mod_set,
                                meal_plan_amount=rate_plan.meal_supplement,
                                pax=2,
                            )

                            subtotal = result['subtotal']
                            # Apply $5 ceiling
                            final_rate = Decimal(str(math.ceil(float(subtotal) / 5) * 5))

                            bar_rate_val = float(seasonal_rate + rate_plan.meal_supplement * 2)

                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': {
                                    'bar_rate': bar_rate_val,
                                    'final_rate': float(final_rate),
                                    'channel_base_rate': float(result['adjusted_room_rate']),
                                    'seasonal_rate': float(seasonal_rate),
                                }
                            }

                            if season.id not in rate_plan_data['bar_rates']:
                                rate_plan_data['bar_rates'][season.id] = bar_rate_val

                            if rate_plan == bb_rate_plan and set_name == standard_set_name:
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
    template_name = 'pricing/pricing_pages/matrix_channel.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'pricing'
        context['nav_sub'] = 'channel_matrix'
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
        Build channel-centric pricing matrix using PricingService.

        Structure: matrix[channel_id] = {
            'channel': Channel object,
            'rooms': {
                room_id: {
                    'room': Room object,
                    'summary_rates': {season_id: rate},
                    'rate_plans': {
                        rate_plan_id: {
                            'rate_plan': RatePlan object,
                            'bar_rates': {season_id: rate},
                            'channel_rate': {season_id: rate},
                        }
                    }
                }
            }
        }
        """
        version = PricingMatrixVersion.get_published(prop)
        pricing_svc = PricingService(prop, version=version)

        matrix = {}

        for channel in channels:
            matrix[channel.id] = {
                'channel': channel,
                'rooms': {},
            }

            for room in rooms:
                room_data = {
                    'room': room,
                    'summary_rates': {},
                    'rate_plans': {},
                }

                for rate_plan in rate_plans:
                    rate_plan_data = {
                        'rate_plan': rate_plan,
                        'bar_rates': {},
                        'channel_rate': {},
                    }

                    for season in seasons:
                        base_rate = room.get_effective_base_rate()
                        effective_index = float(season.season_index)
                        bar_subtotal = float(base_rate) * effective_index
                        meal_supplement = float(rate_plan.meal_supplement) * 2

                        # Get applicable modifiers via PricingService
                        modifier_context = {
                            'season': season, 'season_id': season.id,
                            'room_type': room, 'room_type_id': room.id,
                            'channel': channel, 'channel_id': channel.id,
                        }
                        all_modifiers = pricing_svc.get_applicable_modifiers(modifier_context)

                        result = pricing_svc.calculate_rate(
                            bar_rate=bar_subtotal,
                            modifiers=all_modifiers,
                            meal_plan_amount=meal_supplement,
                            pax=2,
                        )

                        rate_plan_data['channel_rate'][season.id] = float(result['final_rate'])

                        # BAR rate (no channel/promo modifiers)
                        if season.id not in rate_plan_data['bar_rates']:
                            base_mods = [m for m in all_modifiers if m.applies_to in ('season', 'room_type')]
                            bar_result = pricing_svc.calculate_rate(
                                bar_rate=bar_subtotal,
                                modifiers=base_mods,
                                meal_plan_amount=meal_supplement,
                                pax=2,
                            )
                            rate_plan_data['bar_rates'][season.id] = float(bar_result['final_rate'])

                        # Summary rate for B&B
                        if rate_plan == bb_rate_plan:
                            room_data['summary_rates'][season.id] = float(result['final_rate'])

                    room_data['rate_plans'][rate_plan.id] = rate_plan_data

                matrix[channel.id]['rooms'][room.id] = room_data

        return matrix


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
        channels = Channel.objects.filter(hotel=prop)
        rate_plans = RatePlan.objects.filter(hotel=prop)

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

        # Calculate BAR (no discounts)
        from decimal import ROUND_HALF_UP
        rt_mod = parity_room.get_season_modifier(parity_season)
        effective_index = parity_season.season_index * rt_mod
        seasonal_rate = (parity_room.get_effective_base_rate() * effective_index).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        bar_rate = seasonal_rate + parity_rate_plan.meal_supplement * 2

        # Calculate parity for each channel
        version = PricingMatrixVersion.get_published(prop)
        service = PricingService(prop, version)
        parity_data = []
        for channel in channels:
            context = {
                'season': parity_season, 'season_id': parity_season.id,
                'room_type': parity_room, 'room_type_id': parity_room.id,
                'channel': channel, 'channel_id': channel.id,
            }
            modifiers = service.get_applicable_modifiers(context)
            result = service.calculate_rate(
                bar_rate=seasonal_rate,
                modifiers=modifiers,
                meal_plan_amount=parity_rate_plan.meal_supplement,
                pax=2,
            )
            channel_rate = result['subtotal']

            # Commission (not part of guest rate, but needed for net revenue)
            commission_amount = channel_rate * (channel.commission_percent / Decimal('100'))
            net_revenue = channel_rate - commission_amount

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
                'net_revenue': float(net_revenue.quantize(Decimal('0.01'))),
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


@require_POST
def update_room(request, org_code, prop_code, room_id):
    """
    AJAX endpoint to update room details.
    """
    try:
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        prop = get_object_or_404(Property, organization=org, code=prop_code, is_active=True)
        room = get_object_or_404(RoomType, id=room_id, hotel=prop)

        # Parse JSON body (JS sends application/json)
        if request.content_type and 'json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST

        if 'name' in data:
            room.name = data['name']
        if 'base_rate' in data:
            room.base_rate = Decimal(str(data['base_rate']))
        if 'room_index' in data:
            room.room_index = Decimal(str(data['room_index']))
        if 'room_adjustment' in data:
            room.room_adjustment = Decimal(str(data['room_adjustment']))
        if 'pricing_method' in data:
            room.pricing_method = data['pricing_method']
        if 'number_of_rooms' in data:
            room.number_of_rooms = int(data['number_of_rooms'])
        if 'sort_order' in data:
            room.sort_order = int(data['sort_order'])

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

        # Parse JSON body (JS sends application/json)
        if request.content_type and 'json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST

        if 'name' in data:
            season.name = data['name']
        if 'start_date' in data:
            season.start_date = data['start_date']
        if 'end_date' in data:
            season.end_date = data['end_date']
        if 'season_index' in data:
            season.season_index = Decimal(str(data['season_index']))
        if 'expected_occupancy' in data:
            season.expected_occupancy = Decimal(str(data['expected_occupancy']))

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


"""
Date Rate Override Calendar View
================================

Add this view to your pricing/views.py
"""

class DateRateOverrideCalendarView(PropertyMixin, TemplateView):
    """
    Calendar view showing date rate overrides across months.
    
    URL: /{org_code}/{prop_code}/override-calendar/
    
    Features:
    - Month navigation
    - Visual indicators for overrides
    - Click to see rate details
    - Color coding by override type (increase/decrease)
    """
    template_name = 'pricing/pricing_pages/date_override_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'pricing'
        context['nav_sub'] = 'override_calendar'

        from pricing.models import (
            Property, DateRateOverride, Season, RoomType, RatePlan, Channel
        )
        
        # Get current property from URL
        hotel = self.get_property()
        if not hotel:
            raise Http404("Property not found")
        
        context['hotel'] = hotel
        context['org_code'] = hotel.organization.code
        context['prop_code'] = hotel.code
        
        # Get year and month from URL or default to current
        today = date.today()
        year = int(self.request.GET.get('year', today.year))
        month = int(self.request.GET.get('month', today.month))
        
        # Validate month/year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        
        context['year'] = year
        context['month'] = month
        context['month_name'] = calendar.month_name[month]
        
        # Navigation
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1
        
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        
        context['prev_year'] = prev_year
        context['prev_month'] = prev_month
        context['next_year'] = next_year
        context['next_month'] = next_month
        
        # Build calendar data
        cal = calendar.Calendar(firstweekday=6)  # Sunday first
        month_days = cal.monthdayscalendar(year, month)
        
        # Get all overrides for this month
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        
        # Get overrides that overlap with this month (PROPERTY-SPECIFIC)
        overrides = DateRateOverride.objects.filter(
            hotel=hotel,
            active=True,
            periods__start_date__lte=last_day,
            periods__end_date__gte=first_day
        ).distinct().prefetch_related('periods')
        
        # Build date -> override mapping (highest priority wins)
        override_map = {}
        for override in overrides:
            for period in override.periods.all():
                current = max(period.start_date, first_day)
                end = min(period.end_date, last_day)
                while current <= end:
                    if current not in override_map or override.priority > override_map[current].priority:
                        override_map[current] = override
                    current += timedelta(days=1)
        
        # Get season for each day (PROPERTY-SPECIFIC)
        seasons = Season.objects.filter(
            hotel=hotel,
            start_date__lte=last_day,
            end_date__gte=first_day
        )
        
        season_map = {}
        for season in seasons:
            current = max(season.start_date, first_day)
            end = min(season.end_date, last_day)
            while current <= end:
                season_map[current] = season
                current += timedelta(days=1)
        
        # Build calendar weeks with data
        calendar_weeks = []
        for week in month_days:
            week_data = []
            for day_num in week:
                if day_num == 0:
                    week_data.append({
                        'day': None,
                        'date': None,
                        'is_today': False,
                        'override': None,
                        'season': None,
                    })
                else:
                    day_date = date(year, month, day_num)
                    override = override_map.get(day_date)
                    season = season_map.get(day_date)
                    
                    week_data.append({
                        'day': day_num,
                        'date': day_date,
                        'is_today': day_date == today,
                        'is_past': day_date < today,
                        'override': override,
                        'season': season,
                        'has_override': override is not None,
                        'override_type': override.override_type if override else None,
                        'is_increase': override and override.adjustment > 0,
                        'is_decrease': override and override.adjustment < 0,
                    })
            calendar_weeks.append(week_data)
        
        context['calendar_weeks'] = calendar_weeks
        context['weekdays'] = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        
        # Active overrides summary (PROPERTY-SPECIFIC)
        context['active_overrides'] = DateRateOverride.objects.filter(
            hotel=hotel,
            active=True
        ).prefetch_related('periods').order_by('-priority')
        
        # Stats for this month
        override_days = len(override_map)
        total_days = last_day_num
        context['override_stats'] = {
            'override_days': override_days,
            'total_days': total_days,
            'percentage': round(override_days / total_days * 100, 1) if total_days > 0 else 0,
        }
        
        # Reference data for rate preview (PROPERTY-SPECIFIC)
        context['room_types'] = RoomType.objects.filter(hotel=hotel)
        context['rate_plans'] = RatePlan.objects.filter(hotel=hotel)
        context['channels'] = Channel.objects.filter(hotel=hotel)
        
        return context


@require_GET
def date_rate_detail_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to get ALL rates for a specific date.
    
    URL: /{org_code}/{prop_code}/api/date-rate-detail/?date=2026-02-04
    
    Returns all room type × rate plan × channel combinations with calculated rates.
    """
    from pricing.models import (
        Property, Season, RoomType, RatePlan, Channel, DateRateOverride
    )
    from pricing.services import get_override_for_date, apply_override_to_bar
    from datetime import date
    
    # Get property
    hotel = get_object_or_404(
        Property.objects.select_related('organization'),
        organization__code=org_code,
        code=prop_code,
        is_active=True
    )
    
    # Parse date
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': 'Date required'}, status=400)
    
    try:
        check_date = date.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    season = Season.objects.filter(
    start_date__lte=check_date,
    end_date__gte=check_date
    ).first()

    # OR if Season has hotel field:
    season = Season.objects.filter(
        hotel=hotel,
        start_date__lte=check_date,
        end_date__gte=check_date
    ).first()

    # If still None, try without hotel filter:
    if not season:
        season = Season.objects.filter(
            start_date__lte=check_date,
            end_date__gte=check_date
        ).first()
    
    # Get override for this date
    override = get_override_for_date(hotel, check_date) if 'get_override_for_date' in dir() else None
    
    # Try to get override manually if function not available
    if override is None:
        try:
            override = DateRateOverride.objects.filter(
                hotel=hotel,
                active=True,
                periods__start_date__lte=check_date,
                periods__end_date__gte=check_date
            ).order_by('-priority').first()
        except:
            override = None
    
    # Get all room types, rate plans, channels for this property
    room_types = RoomType.objects.filter(hotel=hotel)
    rate_plans = RatePlan.objects.filter(hotel=hotel)
    channels = Channel.objects.filter(hotel=hotel)
    
    # Build rates for all combinations
    rates_data = []
    
    for room_type in room_types:
        room_rates = {
            'room_type_id': room_type.id,
            'room_type_name': room_type.name,
            'rates': []
        }
        
        for rate_plan in rate_plans:
            for channel in channels:
                # Calculate rate
                if season:
                    season_index = season.season_index
                else:
                    season_index = Decimal('1.00')
                
                # Calculate base BAR
                room_base = room_type.get_effective_base_rate()
                seasonal_rate = room_base * season_index
                meal_cost = rate_plan.meal_supplement * 2  # Default 2 pax
                base_bar = seasonal_rate + meal_cost
                
                # Apply override to BAR if exists
                if override:
                    if override.override_type == 'amount':
                        adjusted_bar = base_bar + override.adjustment
                    else:  # percentage
                        multiplier = Decimal('1.00') + (override.adjustment / Decimal('100.00'))
                        adjusted_bar = base_bar * multiplier
                    
                    if adjusted_bar < Decimal('0.00'):
                        adjusted_bar = Decimal('0.00')
                    
                    override_applied = True
                else:
                    adjusted_bar = base_bar
                    override_applied = False
                
                # Apply channel discount
                discount_multiplier = Decimal('1.00') - (channel.base_discount_percent / Decimal('100.00'))
                final_rate = adjusted_bar * discount_multiplier
                
                # Round to 2 decimal places
                base_bar = base_bar.quantize(Decimal('0.01'))
                adjusted_bar = adjusted_bar.quantize(Decimal('0.01'))
                final_rate = final_rate.quantize(Decimal('0.01'))
                
                room_rates['rates'].append({
                    'rate_plan_id': rate_plan.id,
                    'rate_plan_name': rate_plan.name,
                    'channel_id': channel.id,
                    'channel_name': channel.name,
                    'base_bar': str(base_bar),
                    'bar_rate': str(adjusted_bar),
                    'final_rate': str(final_rate),
                    'override_applied': override_applied,
                })
        
        rates_data.append(room_rates)
    
    # Build response
    response_data = {
        'date': date_str,
        'date_display': check_date.strftime('%A, %B %d, %Y'),
        'property': {
            'id': hotel.id,
            'name': hotel.name,
            'code': hotel.code,
        },
        'season': {
            'id': season.id,
            'name': season.name,
            'index': str(season.season_index),
        } if season else None,
        'override': {
            'id': override.id,
            'name': override.name,
            'type': override.override_type,
            'adjustment': override.get_adjustment_display(),
            'adjustment_value': str(override.adjustment),
            'priority': override.priority,
        } if override else None,
        'rates': rates_data,
    }
    
    return JsonResponse(response_data)


"""
Calendar Rates AJAX Endpoint - With Room Filter and Occupancy
=============================================================

Add this to your pricing/views.py
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.shortcuts import get_object_or_404
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
import calendar as cal_module


@require_GET
def calendar_rates_ajax(request, org_code, prop_code):
    """
    AJAX endpoint to get rates and occupancy for each date in a month.
    
    Parameters:
        year: int
        month: int (1-12)
        channel_id: int
        rate_plan_id: int
        room_type_id: int (optional) - if not provided, returns lowest rate among all rooms
    """
    from pricing.models import (
        Property, Season, RoomType, RatePlan, Channel, Reservation
    )
    
    # Get property
    hotel = get_object_or_404(
        Property.objects.select_related('organization'),
        organization__code=org_code,
        code=prop_code,
        is_active=True
    )
    
    # Get parameters
    try:
        year = int(request.GET.get('year', date.today().year))
        month = int(request.GET.get('month', date.today().month))
        channel_id = request.GET.get('channel_id')
        rate_plan_id = request.GET.get('rate_plan_id')
        room_type_id = request.GET.get('room_type_id')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid parameters'}, status=400)
    
    # Get channel
    if channel_id:
        channel = Channel.objects.filter(id=channel_id, hotel=hotel).first()
    else:
        channel = Channel.objects.filter(hotel=hotel, name__icontains='OTA').first() or Channel.objects.filter(hotel=hotel).first()
    
    # Get rate plan
    if rate_plan_id:
        rate_plan = RatePlan.objects.filter(id=rate_plan_id, hotel=hotel).first()
    else:
        rate_plan = RatePlan.objects.filter(hotel=hotel, name__icontains='Breakfast').first() or RatePlan.objects.filter(hotel=hotel).first()
    
    if not channel or not rate_plan:
        return JsonResponse({'error': 'Channel or Rate Plan not found'}, status=404)
    
    # Get room types
    if room_type_id:
        room_types = list(RoomType.objects.filter(hotel=hotel, id=room_type_id))
        selected_room = room_types[0] if room_types else None
    else:
        room_types = list(RoomType.objects.filter(hotel=hotel))
        selected_room = None
    
    if not room_types:
        return JsonResponse({'error': 'No room types found'}, status=404)
    
    # Calculate total rooms for occupancy
    total_rooms = hotel.get_total_rooms()
    
    # Get month date range
    _, last_day = cal_module.monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)
    
    # Get overrides if model exists
    override_map = {}
    try:
        from pricing.models import DateRateOverride
        overrides = DateRateOverride.objects.filter(
            hotel=hotel,
            active=True,
            periods__start_date__lte=last_date,
            periods__end_date__gte=first_date
        ).distinct().prefetch_related('periods')
        
        for override in overrides:
            for period in override.periods.all():
                current = max(period.start_date, first_date)
                end = min(period.end_date, last_date)
                while current <= end:
                    if current not in override_map or override.priority > override_map[current].priority:
                        override_map[current] = override
                    current += timedelta(days=1)
    except:
        pass
    
    # Calculate occupancy for each date
    from pricing.utils import build_daily_occupancy_map
    try:
        occupancy_map = build_daily_occupancy_map(hotel, first_date, last_date)
    except Exception as e:
        occupancy_map = {}
        print(f"Occupancy calculation error: {e}")
    
    # Calculate rates for each date
    rates_data = {}
    current_date = first_date
    
    while current_date <= last_date:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Get season for this date
        season = Season.objects.filter(
            hotel=hotel,
            start_date__lte=current_date,
            end_date__gte=current_date
        ).first()
        
        season_index = season.season_index if season else Decimal('1.00')
        
        # Get override for this date
        override = override_map.get(current_date)
        
        # Calculate rate for each room type, find lowest
        lowest_rate = None
        lowest_room = None
        
        for room_type in room_types:
            room_base = room_type.get_effective_base_rate()
            seasonal_rate = room_base * season_index
            meal_cost = rate_plan.meal_supplement * Decimal('2')
            base_bar = seasonal_rate + meal_cost
            
            if override:
                if override.override_type == 'amount':
                    adjusted_bar = base_bar + override.adjustment
                else:
                    multiplier = Decimal('1.00') + (override.adjustment / Decimal('100.00'))
                    adjusted_bar = base_bar * multiplier
                
                if adjusted_bar < Decimal('0.00'):
                    adjusted_bar = Decimal('0.00')
            else:
                adjusted_bar = base_bar
            
            discount_multiplier = Decimal('1.00') - (channel.base_discount_percent / Decimal('100.00'))
            final_rate = adjusted_bar * discount_multiplier
            final_rate = final_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            if lowest_rate is None or final_rate < lowest_rate:
                lowest_rate = final_rate
                lowest_room = room_type.name
        
        # Calculate occupancy for this date
        rooms_occupied = occupancy_map.get(current_date, 0)
        rooms_available = total_rooms - rooms_occupied
        occupancy_percent = (rooms_occupied / total_rooms * 100) if total_rooms > 0 else 0
        
        rates_data[date_str] = {
            'rate': str(lowest_rate) if lowest_rate else None,
            'room': lowest_room,
            'season': season.name if season else None,
            'season_index': str(season_index),
            'has_override': override is not None,
            'override_name': override.name if override else None,
            'override_adjustment': override.get_adjustment_display() if override else None,
            'is_increase': override.adjustment > 0 if override else False,
            # Occupancy data
            'occupancy': {
                'percent': round(occupancy_percent, 1),
                'rooms_occupied': rooms_occupied,
                'rooms_available': rooms_available,
                'total_rooms': total_rooms,
            }
        }
        
        current_date += timedelta(days=1)
    
    return JsonResponse({
        'year': year,
        'month': month,
        'channel': {'id': channel.id, 'name': channel.name},
        'rate_plan': {'id': rate_plan.id, 'name': rate_plan.name},
        'room_type': {'id': selected_room.id, 'name': selected_room.name} if selected_room else None,
        'total_rooms': total_rooms,
        'rates': rates_data,
    })
    
    
    #Management Views
"""
Pricing Management Views
========================

CRUD views for managing pricing matrix components:
- Seasons (property-specific)
- Room Types (property-specific)
- Rate Plans (shared)
- Channels (shared)
- Rate Modifiers (shared, linked to channels)
- Season Modifier Overrides (links shared modifiers to property seasons)

Usage:
    Add these views to your pricing/views.py
    Add URL patterns to pricing/urls.py
"""

from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Count, Sum
from decimal import Decimal, InvalidOperation
from datetime import datetime
import json


# =============================================================================
# RATE LOOKUP (Operational - Front Desk / Sales)
# =============================================================================

class RateLookupView(PropertyMixin, TemplateView):
    """
    Read-only rate card for a specific date.

    Shows all room types × channels × rate plans with final rates
    including dynamic pricing, seasonal adjustments, and taxes.

    URL: /org/{org_code}/{prop_code}/rates/
    """
    template_name = 'pricing/rates/lookup.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'rates'
        context['nav_sub'] = 'rate_lookup'
        prop = context['property']

        # Get target date from query param or default to today
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = date.today()
        else:
            target_date = date.today()

        context['target_date'] = target_date

        service = PricingService(prop)
        rate_card = service.get_rate_card(target_date)

        context['rate_card'] = rate_card
        context['rate_card_json'] = json.dumps(rate_card)

        return context


class RateLookupAPIView(PropertyMixin, View):
    """
    AJAX endpoint for rate card data.

    GET /org/{org_code}/{prop_code}/api/rate-card/?date=2026-03-15
    """

    def get(self, request, *args, **kwargs):
        prop = self.get_property()

        date_str = request.GET.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
        else:
            target_date = date.today()

        service = PricingService(prop)
        rate_card = service.get_rate_card(target_date)

        return JsonResponse({'success': True, 'data': rate_card})


class ItineraryQuoteAPIView(PropertyMixin, View):
    """
    AJAX endpoint for multi-night itinerary quote.

    GET /org/{org_code}/{prop_code}/api/itinerary-quote/
        ?checkin=2026-02-17&checkout=2026-02-20&room_type=1&channel=1&rate_plan=1&pax=2
    """

    def get(self, request, *args, **kwargs):
        prop = self.get_property()

        # Parse and validate inputs
        checkin_str = request.GET.get('checkin')
        checkout_str = request.GET.get('checkout')
        room_type_id = request.GET.get('room_type')
        channel_id = request.GET.get('channel')
        rate_plan_id = request.GET.get('rate_plan')
        pax = int(request.GET.get('pax', 2))

        if not all([checkin_str, checkout_str, room_type_id, channel_id, rate_plan_id]):
            return JsonResponse({'error': 'Missing required parameters.'}, status=400)

        try:
            checkin = datetime.strptime(checkin_str, '%Y-%m-%d').date()
            checkout = datetime.strptime(checkout_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        if checkout <= checkin:
            return JsonResponse({'error': 'Check-out must be after check-in.'}, status=400)

        num_nights = (checkout - checkin).days
        if num_nights > 30:
            return JsonResponse({'error': 'Maximum 30 nights per quote.'}, status=400)

        room_type_id = int(room_type_id)
        channel_id = int(channel_id)
        rate_plan_id = int(rate_plan_id)

        service = PricingService(prop)
        nights = []
        totals = {
            'room_total': 0, 'meal_total': 0, 'sc_total': 0,
            'tax_total': 0, 'grand_total': 0,
        }
        room_type_name = ''
        channel_name = ''
        rate_plan_name = ''

        current = checkin
        while current < checkout:
            card = service.get_rate_card(current, pax=pax)

            # Find matching room type
            room_data = None
            for rt in card['room_types']:
                if rt['room_type_id'] == room_type_id:
                    room_data = rt
                    room_type_name = rt['room_type_name']
                    break

            if not room_data:
                return JsonResponse({
                    'error': f'Room type {room_type_id} not found.'
                }, status=400)

            # Find matching channel
            ch_data = None
            for ch in room_data['channels']:
                if ch['channel_id'] == channel_id:
                    ch_data = ch
                    channel_name = ch['channel_name']
                    break

            if not ch_data:
                return JsonResponse({
                    'error': f'Channel {channel_id} not found.'
                }, status=400)

            # Find matching rate plan
            rp_data = None
            for rp in ch_data['rate_plans']:
                if rp['rate_plan_id'] == rate_plan_id:
                    rp_data = rp
                    rate_plan_name = rp['rate_plan_name']
                    break

            if not rp_data:
                return JsonResponse({
                    'error': f'Rate plan {rate_plan_id} not found.'
                }, status=400)

            night_info = {
                'date': current.isoformat(),
                'date_display': current.strftime('%a, %b %d'),
                'season': card['season']['name'] if card['season'] else 'No season',
                'dp_multiplier': card['dynamic_pricing']['combined_multiplier'],
                'room_rate': rp_data['room_rate'],
                'meal': rp_data['meal_total'],
                'service_charge': rp_data['service_charge'],
                'tax': rp_data['tax'],
                'final_rate': rp_data['final_rate'],
            }
            nights.append(night_info)

            totals['room_total'] += rp_data['room_rate']
            totals['meal_total'] += rp_data['meal_total']
            totals['sc_total'] += rp_data['service_charge']
            totals['tax_total'] += rp_data['tax']
            totals['grand_total'] += rp_data['final_rate']

            current += timedelta(days=1)

        # Round totals
        for k in totals:
            totals[k] = round(totals[k], 2)

        totals['nights'] = num_nights

        return JsonResponse({
            'success': True,
            'data': {
                'checkin': checkin.isoformat(),
                'checkout': checkout.isoformat(),
                'room_type_name': room_type_name,
                'channel_name': channel_name,
                'rate_plan_name': rate_plan_name,
                'pax': pax,
                'nights': nights,
                'totals': totals,
                'currency': prop.currency_symbol,
                'service_charge_percent': float(prop.service_charge_percent),
                'tax_percent': float(prop.tax_percent),
            }
        })


class AgentRatesView(PropertyMixin, TemplateView):
    """
    Agent rate card for the full year, organized by season.

    Shows all room types × rate plans with agent-specific rates per season,
    terms & conditions, last update date, and an itinerary builder.

    URL: /org/{org_code}/{prop_code}/agent-rates/
    """
    template_name = 'pricing/rates/agent_rates.html'

    def get_context_data(self, **kwargs):
        from decimal import ROUND_HALF_UP

        context = super().get_context_data(**kwargs)
        context['nav_active'] = 'rates'
        context['nav_sub'] = 'agent_rates'
        prop = context['property']

        qs = self.get_property_querysets(prop)
        all_seasons = list(qs['seasons'])
        rooms = list(qs['rooms'])
        rate_plans = list(qs['rate_plans'])
        channels = qs['channels']
        version = qs['version']

        # Determine selected year and filter seasons that overlap with it
        today = date.today()
        available_years = sorted({
            y for s in all_seasons
            for y in range(s.start_date.year, s.end_date.year + 1)
        })
        # Always include current and next year
        for y in [today.year, today.year + 1]:
            if y not in available_years:
                available_years.append(y)
        available_years = sorted(available_years)

        selected_year = self.request.GET.get('year')
        try:
            selected_year = int(selected_year)
            if selected_year not in available_years:
                selected_year = today.year
        except (TypeError, ValueError):
            selected_year = today.year

        seasons = [
            s for s in all_seasons
            if s.start_date.year == selected_year or s.end_date.year == selected_year
        ]

        # Find agent channel
        agent_channel = channels.filter(name__icontains='agent').first()
        if not agent_channel:
            agent_channel = channels.order_by('-commission_percent').first()

        if not agent_channel or not rooms:
            context['has_data'] = False
            missing = []
            if not rooms:
                missing.append('room types')
            if not agent_channel:
                missing.append('channels')
            context['missing_config'] = ' and '.join(missing)
            context['available_years'] = available_years
            context['current_year'] = selected_year
            return context

        context['has_data'] = True

        # Use unified pricing service
        service = PricingService(prop, version)

        # Build rate matrix: room → rate_plan → season → rate
        matrix = []
        for room in rooms:
            room_plans = []
            for rp in rate_plans:
                season_rates = []
                for season in seasons:
                    rt_mod = room.get_season_modifier(season)
                    effective_index = season.season_index * rt_mod
                    seasonal_rate = (room.get_effective_base_rate() * effective_index).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP)

                    context_dict = {
                        'season': season, 'season_id': season.id,
                        'room_type': room, 'room_type_id': room.id,
                        'channel': agent_channel, 'channel_id': agent_channel.id,
                    }
                    mods = service.get_applicable_modifiers(context_dict)
                    result = service.calculate_rate(
                        bar_rate=seasonal_rate,
                        modifiers=mods,
                        meal_plan_amount=rp.meal_supplement,
                        pax=2,
                    )

                    # Apply $5 ceiling
                    subtotal = result['subtotal']
                    final_rate = Decimal(str(math.ceil(float(subtotal) / 5) * 5))

                    season_rates.append({
                        'season_id': season.id,
                        'final_rate': float(final_rate),
                    })
                room_plans.append({
                    'rate_plan_id': rp.id,
                    'rate_plan_name': rp.name,
                    'meal_supplement': float(rp.meal_supplement),
                    'season_rates': season_rates,
                })
            matrix.append({
                'room_type_id': room.id,
                'room_type_name': room.name,
                'number_of_rooms': room.number_of_rooms,
                'base_rate': float(room.get_effective_base_rate()),
                'rate_plans': room_plans,
            })

        # Last updated
        last_updated = None
        if version:
            last_updated = version.updated_at if hasattr(version, 'updated_at') else version.created_at if hasattr(version, 'created_at') else None
        if not last_updated:
            last_updated = timezone.now()

        context['agent_channel'] = agent_channel
        context['seasons'] = seasons
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['matrix'] = matrix
        context['matrix_json'] = json.dumps(matrix)
        context['seasons_json'] = json.dumps([{
            'id': s.id, 'name': s.name, 'type': s.season_type,
            'start_date': s.start_date.isoformat(), 'end_date': s.end_date.isoformat(),
        } for s in seasons])
        context['rate_plans_json'] = json.dumps([{
            'id': rp.id, 'name': rp.name, 'meal_supplement': float(rp.meal_supplement),
        } for rp in rate_plans])
        context['last_updated'] = last_updated
        context['current_year'] = selected_year
        context['available_years'] = available_years

        return context


class AgentRateCardView(TemplateView):
    """
    Public agent rate card accessed via unique token URL.

    URL: /agent/<token>/

    Looks up TravelAgent by token, resolves property and channel,
    then builds the same rate matrix as AgentRatesView.
    """
    template_name = 'pricing/rates/agent_rate_card.html'

    def get_context_data(self, **kwargs):
        from decimal import ROUND_HALF_UP

        context = super().get_context_data(**kwargs)
        token = self.kwargs.get('token')

        agent = get_object_or_404(
            TravelAgent.objects.select_related('property', 'property__organization', 'channel'),
            token=token,
            is_active=True,
        )

        prop = agent.property
        org = prop.organization
        context['agent'] = agent
        context['property'] = prop
        context['prop'] = prop
        context['organization'] = org
        context['org'] = org

        # Get published version
        version = PricingMatrixVersion.get_published(prop)

        # Version-scoped querysets
        version_filter = {'hotel': prop}
        if version:
            version_filter['version'] = version

        all_seasons = list(Season.objects.filter(**version_filter).order_by('start_date'))
        rooms = list(RoomType.objects.filter(**version_filter).order_by('sort_order'))
        rate_plans = list(RatePlan.objects.filter(**version_filter).order_by('sort_order'))

        # Year filter
        today = date.today()
        available_years = sorted({
            y for s in all_seasons
            for y in range(s.start_date.year, s.end_date.year + 1)
        })
        for y in [today.year, today.year + 1]:
            if y not in available_years:
                available_years.append(y)
        available_years = sorted(available_years)

        selected_year = self.request.GET.get('year')
        try:
            selected_year = int(selected_year)
            if selected_year not in available_years:
                selected_year = today.year
        except (TypeError, ValueError):
            selected_year = today.year

        seasons = [
            s for s in all_seasons
            if s.start_date.year == selected_year or s.end_date.year == selected_year
        ]

        # Resolve channel
        agent_channel = agent.get_channel()

        if not agent_channel or not rooms:
            context['has_data'] = False
            return context

        context['has_data'] = True

        # Use unified pricing service
        service = PricingService(prop, version)

        # Build rate matrix
        matrix = []
        for room in rooms:
            room_plans = []
            for rp in rate_plans:
                season_rates = []
                for season in seasons:
                    rt_mod = room.get_season_modifier(season)
                    effective_index = season.season_index * rt_mod
                    seasonal_rate = (room.get_effective_base_rate() * effective_index).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP)

                    context_dict = {
                        'season': season, 'season_id': season.id,
                        'room_type': room, 'room_type_id': room.id,
                        'channel': agent_channel, 'channel_id': agent_channel.id,
                    }
                    mods = service.get_applicable_modifiers(context_dict)
                    result = service.calculate_rate(
                        bar_rate=seasonal_rate,
                        modifiers=mods,
                        meal_plan_amount=rp.meal_supplement,
                        pax=2,
                    )

                    # Apply $5 ceiling
                    subtotal = result['subtotal']
                    final_rate = Decimal(str(math.ceil(float(subtotal) / 5) * 5))

                    season_rates.append({
                        'season_id': season.id,
                        'final_rate': float(final_rate),
                    })
                room_plans.append({
                    'rate_plan_id': rp.id,
                    'rate_plan_name': rp.name,
                    'meal_supplement': float(rp.meal_supplement),
                    'season_rates': season_rates,
                })
            matrix.append({
                'room_type_id': room.id,
                'room_type_name': room.name,
                'number_of_rooms': room.number_of_rooms,
                'base_rate': float(room.get_effective_base_rate()),
                'rate_plans': room_plans,
            })

        # Last updated
        last_updated = None
        if version:
            last_updated = version.updated_at if hasattr(version, 'updated_at') else version.created_at if hasattr(version, 'created_at') else None
        if not last_updated:
            last_updated = timezone.now()

        context['agent_channel'] = agent_channel
        context['seasons'] = seasons
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['matrix'] = matrix
        context['matrix_json'] = json.dumps(matrix)
        context['seasons_json'] = json.dumps([{
            'id': s.id, 'name': s.name, 'type': s.season_type,
            'start_date': s.start_date.isoformat(), 'end_date': s.end_date.isoformat(),
        } for s in seasons])
        context['rate_plans_json'] = json.dumps([{
            'id': rp.id, 'name': rp.name, 'meal_supplement': float(rp.meal_supplement),
        } for rp in rate_plans])
        context['last_updated'] = last_updated
        context['current_year'] = selected_year
        context['available_years'] = available_years
        context['agent_token'] = agent.token

        return context


class AgentRateCardPDFView(View):
    """
    PDF download for agent rate card.

    Works for both internal (/org/{org}/{prop}/agent-rates/pdf/)
    and public token URLs (/agent/{token}/pdf/).
    """

    def get(self, request, *args, **kwargs):
        from decimal import ROUND_HALF_UP

        token = kwargs.get('token')
        if token:
            agent = get_object_or_404(
                TravelAgent.objects.select_related(
                    'property', 'property__organization', 'channel'
                ),
                token=token, is_active=True,
            )
            prop = agent.property
            org = prop.organization
            agent_channel = agent.get_channel()
            agent_name = agent.name
        else:
            prop = self._get_property(kwargs)
            org = prop.organization
            agent = None
            agent_name = None
            qs_channels = Channel.objects.filter(hotel=prop)
            agent_channel = qs_channels.filter(name__icontains='agent').first()
            if not agent_channel:
                agent_channel = qs_channels.order_by('-commission_percent').first()

        if not agent_channel:
            return HttpResponse("No channel configured.", status=400)

        # Get data
        version = PricingMatrixVersion.get_published(prop)
        version_filter = {'hotel': prop}
        if version:
            version_filter['version'] = version

        today = date.today()
        selected_year = request.GET.get('year')
        try:
            selected_year = int(selected_year)
        except (TypeError, ValueError):
            selected_year = today.year

        all_seasons = list(Season.objects.filter(**version_filter).order_by('start_date'))
        seasons = [
            s for s in all_seasons
            if s.start_date.year == selected_year or s.end_date.year == selected_year
        ]
        rooms = list(RoomType.objects.filter(**version_filter).order_by('sort_order'))
        rate_plans = list(RatePlan.objects.filter(**version_filter).order_by('sort_order'))

        # Filter rate plans by selected toggle
        plans_param = request.GET.get('plans', '')
        if plans_param:
            try:
                active_plan_ids = {int(x) for x in plans_param.split(',') if x.strip()}
                rate_plans = [rp for rp in rate_plans if rp.id in active_plan_ids]
            except (ValueError, TypeError):
                pass

        if not seasons or not rooms:
            return HttpResponse("No pricing data available.", status=400)

        # Use unified pricing service
        service = PricingService(prop, version)

        # Build matrix
        matrix = []
        for room in rooms:
            room_plans = []
            for rp in rate_plans:
                season_rates = []
                for season in seasons:
                    rt_mod = room.get_season_modifier(season)
                    effective_index = season.season_index * rt_mod
                    seasonal_rate = (room.get_effective_base_rate() * effective_index).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP)

                    context_dict = {
                        'season': season, 'season_id': season.id,
                        'room_type': room, 'room_type_id': room.id,
                        'channel': agent_channel, 'channel_id': agent_channel.id,
                    }
                    mods = service.get_applicable_modifiers(context_dict)
                    result = service.calculate_rate(
                        bar_rate=seasonal_rate,
                        modifiers=mods,
                        meal_plan_amount=rp.meal_supplement,
                        pax=2,
                    )

                    # Apply $5 ceiling
                    subtotal = result['subtotal']
                    final_rate = Decimal(str(math.ceil(float(subtotal) / 5) * 5))

                    season_rates.append(float(final_rate))
                room_plans.append({
                    'name': rp.name,
                    'meal_supplement': float(rp.meal_supplement),
                    'season_rates': season_rates,
                })
            matrix.append({
                'room_name': room.name,
                'num_rooms': room.number_of_rooms,
                'plans': room_plans,
            })

        # Generate PDF
        pdf_buffer = self._generate_pdf(
            prop, org, agent_name, agent_channel, seasons,
            matrix, rate_plans, selected_year,
        )

        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        slug = prop.code
        filename = f"rate_card_{slug}_{selected_year}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _get_property(self, kwargs):
        from pricing.models import Property
        return Property.objects.select_related('organization').get(
            organization__code=kwargs['org_code'],
            code=kwargs['prop_code'],
            is_active=True,
        )

    def _generate_pdf(self, prop, org, agent_name, channel, seasons, matrix, rate_plans, year):
        buffer = BytesIO()

        num_seasons = len(seasons)
        use_landscape = num_seasons > 4
        page = landscape(A4) if use_landscape else A4

        doc = SimpleDocTemplate(
            buffer, pagesize=page,
            rightMargin=15*mm, leftMargin=15*mm,
            topMargin=15*mm, bottomMargin=15*mm,
        )

        styles = getSampleStyleSheet()
        story = []

        dark = colors.HexColor('#1e3a5f')
        blue = colors.HexColor('#2563eb')
        light_bg = colors.HexColor('#f8fafc')
        border_color = colors.HexColor('#e2e8f0')
        text_dark = colors.HexColor('#1e293b')
        text_muted = colors.HexColor('#64748b')

        title_style = ParagraphStyle(
            'RCTitle', parent=styles['Heading1'],
            fontSize=20, textColor=colors.white, spaceAfter=2,
        )
        sub_style = ParagraphStyle(
            'RCSub', parent=styles['Normal'],
            fontSize=10, textColor=colors.Color(1, 1, 1, 0.8), spaceAfter=0,
        )
        section_style = ParagraphStyle(
            'RCSection', parent=styles['Heading2'],
            fontSize=12, spaceBefore=14, spaceAfter=6,
            textColor=blue,
        )
        normal_style = ParagraphStyle(
            'RCNormal', parent=styles['Normal'],
            fontSize=9, textColor=text_muted,
        )
        terms_style = ParagraphStyle(
            'RCTerms', parent=styles['Normal'],
            fontSize=8, textColor=text_muted, leading=13,
        )

        # ── Header block ──
        page_w = page[0] - 30*mm
        header_data = [
            [
                Paragraph(f"<b>{prop.name}</b>", title_style),
                Paragraph(f"<b>Rate Card {year}</b>", ParagraphStyle(
                    'RCRight', parent=styles['Normal'],
                    fontSize=16, textColor=colors.white, alignment=TA_RIGHT,
                )),
            ],
            [
                Paragraph(getattr(prop, 'location', '') or org.name, sub_style),
                Paragraph(
                    f"Prepared for {agent_name}" if agent_name else f"{channel.name}",
                    ParagraphStyle(
                        'RCSub2', parent=styles['Normal'],
                        fontSize=9, textColor=colors.Color(1, 1, 1, 0.7),
                        alignment=TA_RIGHT,
                    ),
                ),
            ],
        ]
        header_table = Table(header_data, colWidths=[page_w * 0.6, page_w * 0.4])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), dark),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 16),
            ('RIGHTPADDING', (0, 0), (-1, -1), 16),
            ('TOPPADDING', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 14),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 8*mm))

        # ── Channel & date info ──
        meta = f"{channel.name}  |  Last updated: {timezone.now().strftime('%b %d, %Y')}"
        story.append(Paragraph(meta, normal_style))
        story.append(Spacer(1, 4*mm))

        # ── Rate Table ──
        currency = getattr(prop, 'currency_symbol', '$') or '$'

        # Header row
        hdr_style = ParagraphStyle(
            'TH', parent=styles['Normal'],
            fontSize=8, textColor=text_muted, alignment=TA_CENTER,
        )
        hdr_left = ParagraphStyle(
            'THLeft', parent=styles['Normal'],
            fontSize=8, textColor=text_muted,
        )

        header_row = [Paragraph('<b>Room Type / Meal Plan</b>', hdr_left)]
        for s in seasons:
            label = f"<b>{s.start_date.strftime('%b %d')} — {s.end_date.strftime('%b %d')}</b>"
            header_row.append(Paragraph(label, hdr_style))

        table_data = [header_row]

        rate_style = ParagraphStyle(
            'Rate', parent=styles['Normal'],
            fontSize=10, textColor=text_dark, alignment=TA_RIGHT,
        )
        room_style = ParagraphStyle(
            'Room', parent=styles['Normal'],
            fontSize=10, textColor=colors.HexColor('#1e40af'),
        )
        plan_style = ParagraphStyle(
            'Plan', parent=styles['Normal'],
            fontSize=9, textColor=colors.HexColor('#475569'),
        )

        for room in matrix:
            # Room header row
            room_label = f"<b>{room['room_name']}</b> <font size=7 color='#64748b'>({room['num_rooms']} rooms)</font>"
            room_row = [Paragraph(room_label, room_style)] + [''] * num_seasons
            table_data.append(room_row)

            for plan in room['plans']:
                plan_label = plan['name']
                if plan['meal_supplement'] > 0:
                    plan_label += f"  <font size=7 color='#94a3b8'>(+{currency}{plan['meal_supplement']:.0f}/pp)</font>"
                plan_row = [Paragraph(f"    {plan_label}", plan_style)]
                for rate in plan['season_rates']:
                    plan_row.append(Paragraph(f"<b>{currency}{rate:.0f}</b>", rate_style))
                table_data.append(plan_row)

        # Column widths
        first_col = page_w * 0.30
        season_col = (page_w - first_col) / max(num_seasons, 1)
        col_widths = [first_col] + [season_col] * num_seasons

        rate_table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Table styling
        ts = [
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), light_bg),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, border_color),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ]

        # Highlight room header rows
        row_idx = 1
        for room in matrix:
            ts.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#f0f9ff')))
            ts.append(('LINEBELOW', (0, row_idx), (-1, row_idx), 1, colors.HexColor('#bfdbfe')))
            row_idx += 1 + len(room['plans'])

        rate_table.setStyle(TableStyle(ts))
        story.append(rate_table)
        story.append(Spacer(1, 8*mm))

        # ── Terms & Conditions ──
        story.append(Paragraph("<b>Terms & Conditions</b>", section_style))

        sc_pct = getattr(prop, 'service_charge_percent', 10)
        tax_pct = getattr(prop, 'tax_percent', 12)

        terms = [
            f"All rates are in <b>{currency}</b> per room per night based on double occupancy.",
            f"Rates include {sc_pct}% service charge and {tax_pct}% GST where applicable.",
            "Rates are subject to availability at the time of booking.",
            "Seasonal rates apply as indicated — validity dates shown in the table above.",
            "Check-in: 14:00 | Check-out: 12:00 (noon).",
            "Cancellation: Free cancellation up to 14 days before arrival. Late cancellations subject to one night's charge.",
            "No-show: Full stay will be charged.",
            "Children under 12 sharing parents' room: complimentary (without extra bed).",
            "Extra bed: subject to availability and additional charges.",
            "All guests on tourist visa will be required to pay <b>$6 Green Tax</b> per person per night.",
        ]
        for t in terms:
            story.append(Paragraph(f"•  {t}", terms_style))
            story.append(Spacer(1, 1*mm))

        # ── Footer ──
        story.append(Spacer(1, 6*mm))
        footer_text = (
            f"All rates include {sc_pct}% service charge + {tax_pct}% GST  |  "
            f"Generated: {timezone.now().strftime('%b %d, %Y %H:%M')}"
        )
        story.append(Paragraph(footer_text, normal_style))

        doc.build(story)
        buffer.seek(0)
        return buffer
