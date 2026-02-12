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
    RateModifier, SeasonModifierOverride, Reservation,
    DateRateOverride, DateRateOverridePeriod,
    ModifierTemplate, PropertyModifier, ModifierRule,
)
from pricing.services import PricingService

from .mixins import OrganizationMixin, PropertyMixin

logger = logging.getLogger(__name__)

class PricingMatrixView(PropertyMixin, TemplateView):
    """
    Pricing Matrix with expandable channel sections showing individual modifier rates.
    
    Features:
    - Channel Base Rate (no modifier discount)
    - Each RateModifier's individual rate
    - Stacked modifiers shown at bottom
    - OTA expanded by default, others collapsed
    """
    template_name = 'pricing/pricing_pages/matrix.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.models import (
            Property, Season, RoomType, Channel, RatePlan, RateModifier
        )
        
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
        
        # Get filter parameters
        room_type_id = self.request.GET.get('room_type_id', 'all')
        rate_plan_id = self.request.GET.get('rate_plan_id')
        pax = int(self.request.GET.get('pax', 2))
        
        # Get all entities
        seasons = Season.objects.filter(hotel=hotel).order_by('start_date')
        room_types = RoomType.objects.filter(hotel=hotel).order_by('sort_order')
        channels = Channel.objects.all().order_by('sort_order')
        rate_plans = RatePlan.objects.all().order_by('sort_order')
        
        context['seasons'] = seasons
        context['room_types'] = room_types
        context['channels'] = channels
        context['rate_plans'] = rate_plans
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
        
        # Get hotel tax settings
        service_charge_percent = getattr(hotel, 'service_charge_percent', Decimal('10.00')) or Decimal('10.00')
        tax_percent = getattr(hotel, 'tax_percent', Decimal('16.00')) or Decimal('16.00')
        tax_on_service = getattr(hotel, 'tax_on_service_charge', True)
        
        # Build channel_modifiers dict: channel_id -> list of RateModifiers (non-stacked first, stacked last)
        channel_modifiers = {}
        for channel in channels:
            # Try to order by is_stacked if the field exists, otherwise just sort_order
            try:
                modifiers = RateModifier.objects.filter(
                    channel=channel,
                    active=True
                ).order_by('is_stacked', 'sort_order', 'name')
            except:
                modifiers = RateModifier.objects.filter(
                    channel=channel,
                    active=True
                ).order_by('sort_order', 'name')
            channel_modifiers[channel.id] = list(modifiers)
        
        context['channel_modifiers'] = channel_modifiers
        
        def calculate_rate_with_discounts(base_rate, season_index, meal_supplement, pax,
                                          channel_discount, modifier_discount,
                                          service_charge_percent, tax_percent, tax_on_service,
                                          room_type_season_modifier=Decimal('1.00')):
            """
            Calculate final rate with all components.
            
            Returns dict with bar_rate, channel_base_rate, final_rate, etc.
            """
            # Step 1: Effective season index = season_index × room_type_season_modifier
            effective_index = season_index * room_type_season_modifier
            
            # Step 2: Seasonal rate
            seasonal_rate = base_rate * effective_index
            
            # Step 2: Add meals = BAR (before any discounts)
            meal_total = meal_supplement * pax
            bar_rate = seasonal_rate + meal_total
            
            # Step 3: Apply channel discount
            channel_discount_amount = bar_rate * (channel_discount / Decimal('100'))
            channel_base_rate = bar_rate - channel_discount_amount
            
            # Step 4: Apply modifier discount (from channel base)
            modifier_discount_amount = channel_base_rate * (modifier_discount / Decimal('100'))
            subtotal = channel_base_rate - modifier_discount_amount
            
            # Step 5: Service charge
            service_charge = subtotal * (service_charge_percent / Decimal('100'))
            
            # Step 6: Tax
            if tax_on_service:
                taxable = subtotal + service_charge
            else:
                taxable = subtotal
            tax_amount = taxable * (tax_percent / Decimal('100'))
            
            # Step 7: Final rate (what guest pays)
            final_rate = subtotal + service_charge + tax_amount
            
            # Also calculate BAR with service+tax for comparison (no discounts applied)
            bar_service = bar_rate * (service_charge_percent / Decimal('100'))
            if tax_on_service:
                bar_taxable = bar_rate + bar_service
            else:
                bar_taxable = bar_rate
            bar_tax = bar_taxable * (tax_percent / Decimal('100'))
            bar_final = bar_rate + bar_service + bar_tax
            
            return {
                'seasonal_rate': float(seasonal_rate),
                'effective_index': float(effective_index),
                'room_type_season_modifier': float(room_type_season_modifier),
                'meal_total': float(meal_total),
                'bar_rate': float(bar_rate),  # BAR before service+tax
                'bar_final': float(bar_final.quantize(Decimal('0.01'))),  # BAR with service+tax
                'channel_discount_percent': float(channel_discount),
                'channel_discount_amount': float(channel_discount_amount),
                'channel_base_rate': float(channel_base_rate),  # After channel discount, before service+tax
                'modifier_discount_amount': float(modifier_discount_amount),
                'subtotal': float(subtotal),  # After all discounts, before service+tax
                'service_charge': float(service_charge),
                'tax_amount': float(tax_amount),
                'final_rate': float(final_rate.quantize(Decimal('0.01'))),  # What guest pays
            }
        
        def calculate_modifier_rates(room, channel, season, meal_supplement, pax):
            """
            Calculate rates for channel base and each individual modifier.
            """
            base_rate = room.get_effective_base_rate()
            rt_season_mod = room.get_season_modifier(season)
            
            # Calculate Channel Base Rate (no modifier discount)
            channel_base_result = calculate_rate_with_discounts(
                base_rate=base_rate,
                season_index=season.season_index,
                meal_supplement=meal_supplement,
                pax=pax,
                channel_discount=channel.base_discount_percent,
                modifier_discount=Decimal('0.00'),  # No modifier
                service_charge_percent=service_charge_percent,
                tax_percent=tax_percent,
                tax_on_service=tax_on_service,
                room_type_season_modifier=rt_season_mod
            )
            
            # Calculate rate for each individual modifier
            modifier_rates = []
            modifiers = channel_modifiers.get(channel.id, [])
            
            for modifier in modifiers:
                # Get season-specific discount
                season_discount = modifier.get_discount_for_season(season)
                
                mod_result = calculate_rate_with_discounts(
                    base_rate=base_rate,
                    season_index=season.season_index,
                    meal_supplement=meal_supplement,
                    pax=pax,
                    channel_discount=channel.base_discount_percent,
                    modifier_discount=season_discount,
                    service_charge_percent=service_charge_percent,
                    tax_percent=tax_percent,
                    tax_on_service=tax_on_service,
                    room_type_season_modifier=rt_season_mod
                )
                
                modifier_rates.append({
                    'modifier_id': modifier.id,
                    'modifier_name': modifier.name,
                    'modifier_type': modifier.modifier_type,
                    'discount_percent': float(season_discount),
                    'subtotal': mod_result['subtotal'],  # Before service+tax
                    'final_rate': mod_result['final_rate'],  # With service+tax
                    'is_stacked': getattr(modifier, 'is_stacked', False),
                })
            
            return {
                'bar_rate': channel_base_result['bar_final'],  # BAR with service+tax (for comparison)
                'bar_subtotal': channel_base_result['bar_rate'],  # BAR before service+tax
                'channel_base_rate': channel_base_result['final_rate'],  # Channel rate with service+tax (0% modifier)
                'channel_base_subtotal': channel_base_result['subtotal'],  # Channel rate before service+tax
                'modifier_rates': modifier_rates,
            }
        
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
                total_rooms = sum(r.number_of_rooms for r in room_types)
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
    template_name = 'pricing/pricing_pages/matrix_channel.html'
    
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

from pricing.models import Reservation


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
        context['rate_plans'] = RatePlan.objects.all()
        context['channels'] = Channel.objects.all()
        
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
    from pricing.services import calculate_final_rate_with_modifier, get_override_for_date, apply_override_to_bar
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
    rate_plans = RatePlan.objects.all()
    channels = Channel.objects.all()
    
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
        channel = Channel.objects.filter(id=channel_id).first()
    else:
        channel = Channel.objects.filter(name__icontains='OTA').first() or Channel.objects.first()
    
    # Get rate plan
    if rate_plan_id:
        rate_plan = RatePlan.objects.filter(id=rate_plan_id).first()
    else:
        rate_plan = RatePlan.objects.filter(name__icontains='Breakfast').first() or RatePlan.objects.first()
    
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
    total_rooms = sum(rt.number_of_rooms for rt in RoomType.objects.filter(hotel=hotel))
    
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
    # A room night is occupied on a date if: arrival_date <= date < departure_date
    occupancy_map = {}
    
    try:
        # Get all confirmed reservations that overlap with this month
        reservations = Reservation.objects.filter(
            hotel=hotel,
            status__in=['confirmed', 'checked_in', 'checked_out'],
            arrival_date__lte=last_date,
            departure_date__gt=first_date
        ).values('arrival_date', 'departure_date', 'nights')
        
        # Count room nights for each date
        for res in reservations:
            # For each night of the stay
            current = res['arrival_date']
            while current < res['departure_date']:
                if first_date <= current <= last_date:
                    if current not in occupancy_map:
                        occupancy_map[current] = 0
                    occupancy_map[current] += 1
                current += timedelta(days=1)
    except Exception as e:
        # If Reservation model doesn't exist or error, continue without occupancy
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


