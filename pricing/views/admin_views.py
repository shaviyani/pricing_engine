"""
Admin views: Pricing management CRUD (Seasons, RoomTypes, RatePlans,
Channels, Modifiers, Overrides) and Organization/Property settings.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from django.db import transaction

from pricing.models import (
    Organization, Property, Season, RoomType, RatePlan, Channel,
    TravelAgent, RateModifier, SeasonModifierOverride,
    ModifierTemplate, PropertyModifier, ModifierRule,
)
from pricing.services import PricingService

from .mixins import PricingManagementMixin, PropertyMixin, SettingsMixin

logger = logging.getLogger(__name__)

class ManageBaseMixin(PricingManagementMixin):
    """Base mixin for all management section views."""
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import Season, RoomType, RatePlan, Channel, RateModifier
        
        hotel = self.get_hotel(self.request)
        context['hotel'] = hotel
        
        if hotel:
            context['org_code'] = hotel.organization.code
            context['prop_code'] = hotel.code
            context['org'] = hotel.organization
            context['organization'] = hotel.organization
            context['prop'] = hotel
            context['seasons'] = Season.objects.filter(hotel=hotel).order_by('start_date')
            context['room_types'] = RoomType.objects.filter(hotel=hotel).order_by('sort_order')
        
        context['active_section'] = getattr(self, 'active_section', 'landing')
        context['nav_active'] = 'manage'
        return context


class ManageLandingView(ManageBaseMixin, TemplateView):
    """Management landing page with 6 section cards."""
    template_name = 'pricing/manage/landing.html'
    active_section = 'landing'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import (
            RatePlan, Channel, RateModifier, DateRateOverride,
            FileImport, BookingSource
        )
        from django.db.models import Count, Sum
        
        hotel = context.get('hotel')
        org = context.get('organization')
        
        context['rate_plan_count'] = RatePlan.objects.filter(hotel=hotel).count() if hotel else 0
        context['channel_count'] = Channel.objects.filter(hotel=hotel).count() if hotel else 0
        context['modifier_count'] = RateModifier.objects.filter(channel__hotel=hotel).count() if hotel else 0
        context['property_count'] = org.properties.filter(is_active=True).count() if org else 0
        context['override_count'] = DateRateOverride.objects.filter(hotel=hotel, active=True).count() if hotel else 0
        context['import_count'] = FileImport.objects.filter(hotel=hotel).count() if hotel else 0
        context['source_count'] = BookingSource.objects.count()
        context['agent_count'] = TravelAgent.objects.filter(property=hotel).count() if hotel else 0

        return context


class ManageOrganizationView(ManageBaseMixin, TemplateView):
    """Organization settings: org details + property list."""
    template_name = 'pricing/manage/organization.html'
    active_section = 'organization'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Count, Sum
        
        org = context.get('organization')
        if org:
            properties = org.properties.filter(is_active=True).annotate(
                room_type_count=Count('room_types'),
                season_count=Count('seasons'),
                total_room_count=Sum('room_types__number_of_rooms')
            ).order_by('name')
            
            context['org_properties'] = [{
                'id': p.id, 'name': p.name, 'code': p.code,
                'location': p.location, 'reference_base_rate': p.reference_base_rate,
                'total_rooms': p.total_room_count or 0,
                'room_type_count': p.room_type_count, 'season_count': p.season_count,
            } for p in properties]
        
        return context


class ManagePropertyView(ManageBaseMixin, TemplateView):
    """Property settings: property details, seasons, room types."""
    template_name = 'pricing/manage/property.html'
    active_section = 'property'


class ManagePricingView(ManageBaseMixin, TemplateView):
    """Pricing config: rate plans, channels, modifiers, RT season mods."""
    template_name = 'pricing/manage/pricing.html'
    active_section = 'pricing'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import (
            RatePlan, Channel, RateModifier, SeasonModifierOverride,
            PricingMatrixVersion
        )
        
        hotel = context.get('hotel')
        version = PricingMatrixVersion.get_published(hotel) if hotel else None
        context['pricing_version'] = version
        
        vf = {'hotel': hotel}
        if version:
            vf['version'] = version
        
        context['rate_plans'] = RatePlan.objects.filter(**vf).order_by('sort_order')
        context['channels'] = Channel.objects.filter(**vf).prefetch_related('rate_modifiers').order_by('sort_order')
        context['rate_modifiers'] = RateModifier.objects.filter(
            channel__hotel=hotel
        ).select_related('channel').order_by('channel__sort_order', 'sort_order')
        if version:
            context['rate_modifiers'] = context['rate_modifiers'].filter(version=version)
        
        is_valid, total, message = Channel.validate_total_distribution(hotel=hotel, version=version)
        context['distribution_valid'] = is_valid
        context['distribution_total'] = total
        context['distribution_message'] = message
        
        if hotel:
            qs = SeasonModifierOverride.objects.filter(
                season__hotel=hotel
            ).select_related('modifier', 'modifier__channel', 'season').order_by(
                'season__start_date', 'modifier__channel__sort_order', 'modifier__sort_order'
            )
            if version:
                qs = qs.filter(modifier__version=version)
            context['season_overrides'] = qs
        
        return context


class ManageDynamicView(ManageBaseMixin, TemplateView):
    """Dynamic pricing rules and event uplifts."""
    template_name = 'pricing/manage/dynamic.html'
    active_section = 'dynamic'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import PricingMatrixVersion

        hotel = context.get('hotel')
        version = PricingMatrixVersion.get_published(hotel) if hotel else None
        context['pricing_version'] = version

        return context


class ManageOffersView(ManageBaseMixin, TemplateView):
    """Offers & overrides: date rate overrides + future offers."""
    template_name = 'pricing/manage/offers.html'
    active_section = 'offers'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import DateRateOverride
        
        hotel = context.get('hotel')
        if hotel:
            context['active_overrides'] = DateRateOverride.objects.filter(
                hotel=hotel, active=True
            ).order_by('-created_at')[:20]
        
        return context


class ManageImportView(ManageBaseMixin, TemplateView):
    """Data import: upload, history, booking sources."""
    template_name = 'pricing/manage/import.html'
    active_section = 'import'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import FileImport, BookingSource, Reservation
        from django.db.models import Count, Sum

        hotel = context.get('hotel')
        if hotel:
            context['file_imports'] = FileImport.objects.filter(hotel=hotel).order_by('-created_at')[:20]
            context['booking_sources'] = BookingSource.objects.all().select_related('channel').order_by('sort_order')
            context['import_stats'] = FileImport.objects.filter(hotel=hotel).aggregate(
                total_imports=Count('id'),
                total_rows=Sum('rows_total'),
                total_created=Sum('rows_created'),
                total_updated=Sum('rows_updated'),
            )
            context['reservation_count'] = Reservation.objects.filter(hotel=hotel).count()

        return context


class ManageVersionDetailView(ManageBaseMixin, TemplateView):
    """Detail view for a single pricing matrix version. Editable for drafts."""
    template_name = 'pricing/manage/version_detail.html'
    active_section = 'pricing'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import (
            PricingMatrixVersion, Season, RoomType, RatePlan, Channel,
            RateModifier, DynamicPricingRule, RoomTypeSeasonModifier,
        )
        from pricing.services.version_service import PricingVersionService
        from decimal import Decimal

        hotel = context.get('hotel')
        version_id = self.kwargs.get('version_id')
        version = get_object_or_404(
            PricingMatrixVersion, pk=version_id, hotel=hotel
        )

        svc = PricingVersionService(hotel)
        summary = svc.get_version_summary(version)
        is_editable = version.status == 'draft'

        v_seasons = Season.objects.filter(version=version).order_by('start_date')
        v_room_types = RoomType.objects.filter(version=version).order_by('sort_order', 'name')
        v_rate_plans = RatePlan.objects.filter(version=version).order_by('sort_order')
        v_channels = Channel.objects.filter(version=version).order_by('sort_order')

        v_rate_modifiers = RateModifier.objects.filter(
            version=version
        ).select_related('channel').order_by('channel__sort_order', 'sort_order')

        modifiers_by_channel = {}
        channel_modifiers = {}
        for mod in v_rate_modifiers:
            ch_name = mod.channel.name
            if ch_name not in modifiers_by_channel:
                modifiers_by_channel[ch_name] = []
            modifiers_by_channel[ch_name].append(mod)
            channel_modifiers.setdefault(mod.channel_id, []).append(mod)

        # Room type season modifiers
        rt_season_mods = RoomTypeSeasonModifier.objects.filter(
            room_type__version=version, season__version=version
        ).select_related('room_type', 'season').order_by('season__start_date', 'room_type__sort_order')

        # Dynamic pricing rules with nested bands and multipliers
        dp_rules = DynamicPricingRule.objects.filter(
            version=version
        ).select_related(
            'season', 'booking_window_config'
        ).prefetch_related(
            'bands__multipliers__window_band'
        ).order_by('season__start_date')

        dp_data = []
        for rule in dp_rules:
            window_bands = list(rule.booking_window_config.bands.order_by('min_days'))
            bands_with_mults = []
            for band in rule.bands.order_by('-min_occupancy'):
                mults_by_wb = {}
                for m in band.multipliers.all():
                    mults_by_wb[m.window_band_id] = m.multiplier
                ordered_mults = [mults_by_wb.get(wb.id, Decimal('1.00')) for wb in window_bands]
                bands_with_mults.append({
                    'band': band,
                    'multipliers': ordered_mults,
                })
            dp_data.append({
                'rule': rule,
                'season': rule.season,
                'window_bands': window_bands,
                'bands': bands_with_mults,
            })

        # =====================================================================
        # Pricing Matrix Calculation
        # =====================================================================
        pax = int(self.request.GET.get('pax', 2))
        rate_plan_id = self.request.GET.get('rate_plan_id')

        if rate_plan_id:
            selected_rate_plan = v_rate_plans.filter(id=rate_plan_id).first() or v_rate_plans.first()
        else:
            selected_rate_plan = v_rate_plans.first()

        meal_supplement = selected_rate_plan.meal_supplement if selected_rate_plan else Decimal('0.00')
        service_charge_percent = getattr(hotel, 'service_charge_percent', Decimal('10.00')) or Decimal('10.00')
        tax_percent = getattr(hotel, 'tax_percent', Decimal('16.00')) or Decimal('16.00')
        tax_on_service = getattr(hotel, 'tax_on_service_charge', True)

        def calc_rate(base_rate, season_index, meal_sup, num_pax,
                      channel_discount, modifier_discount,
                      rt_season_mod=Decimal('1.00')):
            effective_index = season_index * rt_season_mod
            seasonal_rate = base_rate * effective_index
            meal_total = meal_sup * num_pax
            bar_rate = seasonal_rate + meal_total

            ch_disc_amt = bar_rate * (channel_discount / Decimal('100'))
            channel_base = bar_rate - ch_disc_amt
            mod_disc_amt = channel_base * (modifier_discount / Decimal('100'))
            subtotal = channel_base - mod_disc_amt

            sc = subtotal * (service_charge_percent / Decimal('100'))
            taxable = (subtotal + sc) if tax_on_service else subtotal
            tax = taxable * (tax_percent / Decimal('100'))
            final = subtotal + sc + tax

            bar_sc = bar_rate * (service_charge_percent / Decimal('100'))
            bar_taxable = (bar_rate + bar_sc) if tax_on_service else bar_rate
            bar_tax = bar_taxable * (tax_percent / Decimal('100'))
            bar_final = bar_rate + bar_sc + bar_tax

            return {
                'bar_rate': float(bar_rate),
                'bar_final': float(bar_final.quantize(Decimal('0.01'))),
                'channel_base_rate': float(channel_base),
                'subtotal': float(subtotal),
                'final_rate': float(final.quantize(Decimal('0.01'))),
            }

        matrix = {}
        has_matrix = v_seasons.exists() and v_channels.exists() and v_room_types.exists()

        if has_matrix:
            for room in v_room_types:
                matrix[room.id] = {}
                for channel in v_channels:
                    matrix[room.id][channel.id] = {}
                    for season in v_seasons:
                        rt_mod = room.get_season_modifier(season)
                        base = room.get_effective_base_rate()

                        # Channel base (0% modifier)
                        cb = calc_rate(base, season.season_index, meal_supplement,
                                       pax, channel.base_discount_percent,
                                       Decimal('0'), rt_mod)

                        # Per-modifier rates
                        mod_rates = []
                        for mod in channel_modifiers.get(channel.id, []):
                            if mod.active:
                                disc = mod.get_discount_for_season(season)
                                mr = calc_rate(base, season.season_index, meal_supplement,
                                               pax, channel.base_discount_percent,
                                               disc, rt_mod)
                                mod_rates.append({
                                    'modifier_id': mod.id,
                                    'subtotal': mr['subtotal'],
                                    'final_rate': mr['final_rate'],
                                })

                        matrix[room.id][channel.id][season.id] = {
                            'bar_rate': cb['bar_rate'],
                            'bar_final': cb['bar_final'],
                            'channel_base_subtotal': cb['subtotal'],
                            'channel_base_rate': cb['final_rate'],
                            'modifier_rates': mod_rates,
                        }

        context.update({
            'version': version,
            'summary': summary,
            'is_editable': is_editable,
            'v_seasons': v_seasons,
            'v_room_types': v_room_types,
            'v_rate_plans': v_rate_plans,
            'v_channels': v_channels,
            'modifiers_by_channel': modifiers_by_channel,
            'channel_modifiers': channel_modifiers,
            'rt_season_mods': rt_season_mods,
            'dp_data': dp_data,
            'matrix': matrix,
            'has_matrix': has_matrix,
            'pax': pax,
            'selected_rate_plan': selected_rate_plan,
        })
        return context


# Keep old name as alias for backward compat
PricingManagementView = ManageLandingView


# =============================================================================
# PROPERTY SETTINGS
# =============================================================================

class PropertyUpdateView(PricingManagementMixin, View):
    """API: Update property settings (reference_base_rate, etc.)."""
    
    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        # Allowed fields for update
        allowed_fields = ['reference_base_rate', 'name', 'currency_symbol']
        
        updated_fields = []
        
        for field, value in data.items():
            if field not in allowed_fields:
                continue
            
            if field == 'reference_base_rate':
                new_rate = self.parse_decimal(value, None)
                if new_rate is None or new_rate <= 0:
                    return self.error_response('Reference base rate must be a positive number')
                hotel.reference_base_rate = new_rate
                updated_fields.append(field)
            
            elif field == 'name':
                name = str(value).strip()
                if not name:
                    return self.error_response('Property name cannot be empty')
                hotel.name = name
                updated_fields.append(field)
            
            elif field == 'currency_symbol':
                symbol = str(value).strip()
                if not symbol:
                    return self.error_response('Currency symbol cannot be empty')
                hotel.currency_symbol = symbol
                updated_fields.append(field)
        
        if not updated_fields:
            return self.error_response('No valid fields to update')
        
        hotel.save()
        
        return self.success_response(
            data={
                'reference_base_rate': str(hotel.reference_base_rate),
                'name': hotel.name,
                'currency_symbol': hotel.currency_symbol,
            },
            message=f'Property updated successfully'
        )


# =============================================================================
# SEASON MANAGEMENT
# =============================================================================

class SeasonListView(PricingManagementMixin, View):
    """API: List seasons for a property."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import Season
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        seasons = Season.objects.filter(hotel=hotel).order_by('start_date')
        
        data = [{
            'id': s.id,
            'name': s.name,
            'start_date': s.start_date.strftime('%Y-%m-%d'),
            'end_date': s.end_date.strftime('%Y-%m-%d'),
            'season_index': str(s.season_index),
            'expected_occupancy': str(s.expected_occupancy),
            'date_range_display': s.date_range_display(),
        } for s in seasons]
        
        return self.json_response({'seasons': data})


class SeasonCreateView(PricingManagementMixin, View):
    """API: Create a new season."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Season, PricingMatrixVersion

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        # Version support: use provided version_id or fall back to published
        vid = data.get('version_id')
        if vid:
            version = get_object_or_404(PricingMatrixVersion, pk=vid, hotel=hotel)
        else:
            version = PricingMatrixVersion.get_published(hotel)

        # Validate required fields
        name = data.get('name', '').strip()
        start_date = self.parse_date(data.get('start_date'))
        end_date = self.parse_date(data.get('end_date'))

        if not name:
            return self.error_response('Name is required')
        if not start_date or not end_date:
            return self.error_response('Valid start and end dates are required')
        if start_date > end_date:
            return self.error_response('Start date must be before end date')

        season_index = self.parse_decimal(data.get('season_index'), Decimal('1.00'))
        expected_occupancy = self.parse_decimal(data.get('expected_occupancy'), Decimal('70.00'))

        season = Season.objects.create(
            hotel=hotel,
            version=version,
            name=name,
            start_date=start_date,
            end_date=end_date,
            season_index=season_index,
            expected_occupancy=expected_occupancy,
        )
        
        return self.success_response(
            data={'id': season.id, 'name': season.name},
            message=f'Season "{season.name}" created successfully'
        )


class SeasonUpdateView(PricingManagementMixin, View):
    """API: Update an existing season."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Season
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        season_id = kwargs.get('pk')
        season = get_object_or_404(Season, pk=season_id, hotel=hotel)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        # Update fields if provided
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            season.name = name
        
        if 'start_date' in data:
            start_date = self.parse_date(data['start_date'])
            if not start_date:
                return self.error_response('Invalid start date')
            season.start_date = start_date
        
        if 'end_date' in data:
            end_date = self.parse_date(data['end_date'])
            if not end_date:
                return self.error_response('Invalid end date')
            season.end_date = end_date
        
        if season.start_date > season.end_date:
            return self.error_response('Start date must be before end date')
        
        if 'season_index' in data:
            season.season_index = self.parse_decimal(data['season_index'], season.season_index)
        
        if 'expected_occupancy' in data:
            season.expected_occupancy = self.parse_decimal(data['expected_occupancy'], season.expected_occupancy)
        
        season.save()
        
        return self.success_response(message=f'Season "{season.name}" updated successfully')


class SeasonDeleteView(PricingManagementMixin, View):
    """API: Delete a season."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Season
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        season_id = kwargs.get('pk')
        season = get_object_or_404(Season, pk=season_id, hotel=hotel)
        name = season.name
        season.delete()
        
        return self.success_response(message=f'Season "{name}" deleted successfully')


# =============================================================================
# ROOM TYPE MANAGEMENT
# =============================================================================

class RoomTypeListView(PricingManagementMixin, View):
    """API: List room types for a property."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import RoomType
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        room_types = RoomType.objects.filter(hotel=hotel).order_by('sort_order')
        
        data = [{
            'id': r.id,
            'name': r.name,
            'base_rate': str(r.base_rate),
            'room_index': str(r.room_index),
            'room_adjustment': str(r.room_adjustment),
            'pricing_method': r.pricing_method,
            'number_of_rooms': r.number_of_rooms,
            'sort_order': r.sort_order,
            'effective_rate': str(r.get_effective_base_rate()),
            'description': r.description,
            'target_occupancy': str(r.target_occupancy),
            'premium_percent': str(r.get_premium_percent()),
        } for r in room_types]
        
        return self.json_response({'room_types': data})


class RoomTypeCreateView(PricingManagementMixin, View):
    """API: Create a new room type."""

    def post(self, request, *args, **kwargs):
        from pricing.models import RoomType, PricingMatrixVersion

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        vid = data.get('version_id')
        if vid:
            version = get_object_or_404(PricingMatrixVersion, pk=vid, hotel=hotel)
        else:
            version = PricingMatrixVersion.get_published(hotel)

        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')

        # Get max sort order
        max_order = RoomType.objects.filter(hotel=hotel).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0

        room_type = RoomType.objects.create(
            hotel=hotel,
            version=version,
            name=name,
            base_rate=self.parse_decimal(data.get('base_rate'), hotel.reference_base_rate),
            room_index=self.parse_decimal(data.get('room_index'), Decimal('1.00')),
            room_adjustment=self.parse_decimal(data.get('room_adjustment'), Decimal('0.00')),
            pricing_method=data.get('pricing_method', 'index'),
            number_of_rooms=int(data.get('number_of_rooms', 1)),
            sort_order=int(data.get('sort_order', max_order + 1)),
            description=data.get('description', ''),
            target_occupancy=self.parse_decimal(data.get('target_occupancy'), Decimal('70.00')),
        )
        
        return self.success_response(
            data={'id': room_type.id, 'name': room_type.name},
            message=f'Room type "{room_type.name}" created successfully'
        )


class RoomTypeUpdateView(PricingManagementMixin, View):
    """API: Update a room type."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RoomType
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        room_id = kwargs.get('pk')
        room_type = get_object_or_404(RoomType, pk=room_id, hotel=hotel)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            room_type.name = name
        
        if 'base_rate' in data:
            room_type.base_rate = self.parse_decimal(data['base_rate'], room_type.base_rate)
        
        if 'room_index' in data:
            room_type.room_index = self.parse_decimal(data['room_index'], room_type.room_index)
        
        if 'room_adjustment' in data:
            room_type.room_adjustment = self.parse_decimal(data['room_adjustment'], room_type.room_adjustment)
        
        if 'pricing_method' in data:
            if data['pricing_method'] in ['direct', 'index', 'adjustment']:
                room_type.pricing_method = data['pricing_method']
        
        if 'number_of_rooms' in data:
            room_type.number_of_rooms = max(0, int(data.get('number_of_rooms', room_type.number_of_rooms)))
        
        if 'sort_order' in data:
            room_type.sort_order = int(data.get('sort_order', room_type.sort_order))
        
        if 'description' in data:
            room_type.description = data.get('description', '')
        
        if 'target_occupancy' in data:
            room_type.target_occupancy = self.parse_decimal(data['target_occupancy'], room_type.target_occupancy)
        
        room_type.save()
        
        return self.success_response(message=f'Room type "{room_type.name}" updated successfully')


class RoomTypeDeleteView(PricingManagementMixin, View):
    """API: Delete a room type."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RoomType
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        room_id = kwargs.get('pk')
        room_type = get_object_or_404(RoomType, pk=room_id, hotel=hotel)
        name = room_type.name
        room_type.delete()
        
        return self.success_response(message=f'Room type "{name}" deleted successfully')


class RoomTypeReorderView(PricingManagementMixin, View):
    """API: Reorder room types."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RoomType
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        order = data.get('order', [])  # List of room type IDs in new order
        
        with transaction.atomic():
            for idx, room_id in enumerate(order):
                RoomType.objects.filter(pk=room_id, hotel=hotel).update(sort_order=idx)
        
        return self.success_response(message='Room types reordered successfully')


# =============================================================================
# RATE PLAN MANAGEMENT (SHARED)
# =============================================================================

class RatePlanListView(PricingManagementMixin, View):
    """API: List all rate plans."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import RatePlan, PricingMatrixVersion
        
        hotel = self.get_hotel(request)
        version = PricingMatrixVersion.get_published(hotel) if hotel else None
        
        qs = RatePlan.objects.filter(hotel=hotel).order_by('sort_order') if hotel else RatePlan.objects.none()
        if version: qs = qs.filter(version=version)
        
        data = [{
            'id': r.id,
            'name': r.name,
            'meal_supplement': str(r.meal_supplement),
            'sort_order': r.sort_order,
        } for r in qs]
        
        return self.json_response({'rate_plans': data})


class RatePlanCreateView(PricingManagementMixin, View):
    """API: Create a new rate plan."""

    def post(self, request, *args, **kwargs):
        from pricing.models import RatePlan, PricingMatrixVersion

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found')

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        vid = data.get('version_id')
        if vid:
            version = get_object_or_404(PricingMatrixVersion, pk=vid, hotel=hotel)
        else:
            version = PricingMatrixVersion.get_published(hotel)

        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')

        max_order = RatePlan.objects.filter(hotel=hotel).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        rate_plan = RatePlan.objects.create(
            hotel=hotel,
            version=version,
            name=name,
            meal_supplement=self.parse_decimal(data.get('meal_supplement'), Decimal('0.00')),
            sort_order=int(data.get('sort_order', max_order + 1)),
        )
        
        return self.success_response(
            data={'id': rate_plan.id, 'name': rate_plan.name},
            message=f'Rate plan "{rate_plan.name}" created successfully'
        )


class RatePlanUpdateView(PricingManagementMixin, View):
    """API: Update a rate plan."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RatePlan
        
        plan_id = kwargs.get('pk')
        rate_plan = get_object_or_404(RatePlan, pk=plan_id)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            rate_plan.name = name
        
        if 'meal_supplement' in data:
            rate_plan.meal_supplement = self.parse_decimal(data['meal_supplement'], rate_plan.meal_supplement)
        
        if 'sort_order' in data:
            rate_plan.sort_order = int(data.get('sort_order', rate_plan.sort_order))
        
        rate_plan.save()
        
        return self.success_response(message=f'Rate plan "{rate_plan.name}" updated successfully')


class RatePlanDeleteView(PricingManagementMixin, View):
    """API: Delete a rate plan."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RatePlan
        
        plan_id = kwargs.get('pk')
        rate_plan = get_object_or_404(RatePlan, pk=plan_id)
        name = rate_plan.name
        rate_plan.delete()
        
        return self.success_response(message=f'Rate plan "{name}" deleted successfully')


# =============================================================================
# CHANNEL MANAGEMENT (SHARED)
# =============================================================================

class ChannelListView(PricingManagementMixin, View):
    """API: List all channels."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import Channel, PricingMatrixVersion
        
        hotel = self.get_hotel(request)
        version = PricingMatrixVersion.get_published(hotel) if hotel else None
        
        qs = Channel.objects.filter(hotel=hotel).prefetch_related('rate_modifiers').order_by('sort_order') if hotel else Channel.objects.none()
        if version: qs = qs.filter(version=version)
        
        data = [{
            'id': c.id,
            'name': c.name,
            'base_discount_percent': str(c.base_discount_percent),
            'commission_percent': str(c.commission_percent),
            'distribution_share_percent': str(c.distribution_share_percent),
            'sort_order': c.sort_order,
            'modifier_count': c.rate_modifiers.count(),
        } for c in qs]
        
        # Distribution validation
        is_valid, total, message = Channel.validate_total_distribution(hotel=hotel, version=version)
        
        return self.json_response({
            'channels': data,
            'distribution_valid': is_valid,
            'distribution_total': str(total),
            'distribution_message': message,
        })


class ChannelCreateView(PricingManagementMixin, View):
    """API: Create a new channel."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Channel, PricingMatrixVersion

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found')

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        vid = data.get('version_id')
        if vid:
            version = get_object_or_404(PricingMatrixVersion, pk=vid, hotel=hotel)
        else:
            version = PricingMatrixVersion.get_published(hotel)
        
        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')
        
        max_order = Channel.objects.filter(hotel=hotel).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        channel = Channel.objects.create(
            hotel=hotel,
            version=version,
            name=name,
            base_discount_percent=self.parse_decimal(data.get('base_discount_percent'), Decimal('0.00')),
            commission_percent=self.parse_decimal(data.get('commission_percent'), Decimal('0.00')),
            distribution_share_percent=self.parse_decimal(data.get('distribution_share_percent'), Decimal('0.00')),
            sort_order=int(data.get('sort_order', max_order + 1)),
        )
        
        return self.success_response(
            data={'id': channel.id, 'name': channel.name},
            message=f'Channel "{channel.name}" created successfully'
        )


class ChannelUpdateView(PricingManagementMixin, View):
    """API: Update a channel."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Channel
        
        channel_id = kwargs.get('pk')
        channel = get_object_or_404(Channel, pk=channel_id)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            channel.name = name
        
        if 'base_discount_percent' in data:
            channel.base_discount_percent = self.parse_decimal(
                data['base_discount_percent'], channel.base_discount_percent
            )
        
        if 'commission_percent' in data:
            channel.commission_percent = self.parse_decimal(
                data['commission_percent'], channel.commission_percent
            )
        
        if 'distribution_share_percent' in data:
            channel.distribution_share_percent = self.parse_decimal(
                data['distribution_share_percent'], channel.distribution_share_percent
            )
        
        if 'sort_order' in data:
            channel.sort_order = int(data.get('sort_order', channel.sort_order))
        
        channel.save()
        
        return self.success_response(message=f'Channel "{channel.name}" updated successfully')


class ChannelDeleteView(PricingManagementMixin, View):
    """API: Delete a channel."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Channel
        
        channel_id = kwargs.get('pk')
        channel = get_object_or_404(Channel, pk=channel_id)
        name = channel.name
        channel.delete()
        
        return self.success_response(message=f'Channel "{name}" deleted successfully')


class ChannelNormalizeDistributionView(PricingManagementMixin, View):
    """API: Normalize channel distribution to 100%."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Channel
        
        Channel.normalize_distribution()
        
        return self.success_response(message='Channel distribution normalized to 100%')


class ChannelEqualDistributionView(PricingManagementMixin, View):
    """API: Set equal distribution across all channels."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Channel
        
        Channel.distribute_equally()
        
        return self.success_response(message='Channel distribution set to equal shares')


# =============================================================================
# RATE MODIFIER MANAGEMENT (SHARED)
# =============================================================================

class RateModifierListView(PricingManagementMixin, View):
    """API: List all rate modifiers."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import RateModifier
        
        channel_id = request.GET.get('channel_id')
        
        modifiers = RateModifier.objects.select_related('channel').order_by(
            'channel__sort_order', 'sort_order'
        )
        
        if channel_id:
            modifiers = modifiers.filter(channel_id=channel_id)
        
        data = [{
            'id': m.id,
            'channel_id': m.channel_id,
            'channel_name': m.channel.name,
            'name': m.name,
            'discount_percent': str(m.discount_percent),
            'modifier_type': m.modifier_type,
            'modifier_type_display': m.get_modifier_type_display(),
            'active': m.active,
            'sort_order': m.sort_order,
            'description': m.description,
            'total_discount': str(m.total_discount_from_bar()),
        } for m in modifiers]
        
        return self.json_response({'modifiers': data})


class RateModifierCreateView(PricingManagementMixin, View):
    """API: Create a new rate modifier."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RateModifier, Channel
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        name = data.get('name', '').strip()
        channel_id = data.get('channel_id')
        
        if not name:
            return self.error_response('Name is required')
        if not channel_id:
            return self.error_response('Channel is required')
        
        channel = get_object_or_404(Channel, pk=channel_id)

        # Resolve version
        from pricing.models import PricingMatrixVersion
        vid = data.get('version_id')
        if vid:
            version = get_object_or_404(PricingMatrixVersion, pk=vid, hotel=channel.hotel)
        else:
            version = PricingMatrixVersion.get_published(channel.hotel)

        # Check for duplicate name
        if RateModifier.objects.filter(channel=channel, name=name, version=version).exists():
            return self.error_response(f'Modifier "{name}" already exists for {channel.name}')

        max_order = RateModifier.objects.filter(channel=channel, version=version).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0

        modifier = RateModifier.objects.create(
            channel=channel,
            version=version,
            name=name,
            discount_percent=self.parse_decimal(data.get('discount_percent'), Decimal('0.00')),
            modifier_type=data.get('modifier_type', 'standard'),
            active=data.get('active', True),
            sort_order=int(data.get('sort_order', max_order + 1)),
            description=data.get('description', ''),
            stackable=data.get('stackable', False),
            is_stacked=data.get('is_stacked', False),
)

        
        # Handle stacked_from if this is a stacked modifier
        stacked_from_ids = data.get('stacked_from', [])
        if stacked_from_ids and modifier.is_stacked:
            from pricing.models import RateModifier as RM
            source_modifiers = RM.objects.filter(id__in=stacked_from_ids)
            modifier.stacked_from.set(source_modifiers)
        
        return self.success_response(
            data={'id': modifier.id, 'name': modifier.name},
            message=f'Modifier "{modifier.name}" created successfully'
        )


class RateModifierUpdateView(PricingManagementMixin, View):
    """API: Update a rate modifier."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RateModifier
        
        modifier_id = kwargs.get('pk')
        modifier = get_object_or_404(RateModifier, pk=modifier_id)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            # Check for duplicate
            if RateModifier.objects.filter(
                channel=modifier.channel, name=name
            ).exclude(pk=modifier_id).exists():
                return self.error_response(f'Modifier "{name}" already exists for {modifier.channel.name}')
            modifier.name = name
        
        discount_changed = False
        if 'discount_percent' in data:
            new_discount = self.parse_decimal(data['discount_percent'], modifier.discount_percent)
            if new_discount != modifier.discount_percent:
                discount_changed = True
            modifier.discount_percent = new_discount
        
        if 'modifier_type' in data:
            valid_types = [t[0] for t in RateModifier.MODIFIER_TYPES]
            if data['modifier_type'] in valid_types:
                modifier.modifier_type = data['modifier_type']
        
        if 'active' in data:
            modifier.active = bool(data['active'])
        
        if 'sort_order' in data:
            modifier.sort_order = int(data.get('sort_order', modifier.sort_order))
        
        if 'description' in data:
            modifier.description = data['description']
        
        modifier.save()
        
        # Recalculate stacked modifiers that use this modifier as a source
        updated_stacked = []
        if discount_changed:
            try:
                # Find all stacked modifiers that reference this modifier
                stacked_modifiers = RateModifier.objects.filter(
                    is_stacked=True,
                    stacked_from=modifier
                )
                
                for stacked in stacked_modifiers:
                    # Recalculate the combined discount from all source modifiers
                    source_modifiers = stacked.stacked_from.all()
                    total_discount = sum(m.discount_percent for m in source_modifiers)
                    
                    stacked.discount_percent = total_discount
                    stacked.save()
                    updated_stacked.append(stacked.name)
            except Exception as e:
                # If stacked_from field doesn't exist, skip silently
                pass
        
        message = f'Modifier "{modifier.name}" updated successfully'
        if updated_stacked:
            message += f'. Recalculated: {", ".join(updated_stacked)}'
        
        return self.success_response(message=message)


class RateModifierDeleteView(PricingManagementMixin, View):
    """API: Delete a rate modifier."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RateModifier
        
        modifier_id = kwargs.get('pk')
        modifier = get_object_or_404(RateModifier, pk=modifier_id)
        name = modifier.name
        modifier.delete()
        
        return self.success_response(message=f'Modifier "{name}" deleted successfully')


class RateModifierToggleView(PricingManagementMixin, View):
    """API: Toggle a modifier's active status."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RateModifier
        
        modifier_id = kwargs.get('pk')
        modifier = get_object_or_404(RateModifier, pk=modifier_id)
        
        modifier.active = not modifier.active
        modifier.save()
        
        status = 'activated' if modifier.active else 'deactivated'
        return self.success_response(
            data={'active': modifier.active},
            message=f'Modifier "{modifier.name}" {status}'
        )


# =============================================================================
# SEASON MODIFIER OVERRIDE MANAGEMENT
# =============================================================================

class SeasonModifierOverrideListView(PricingManagementMixin, View):
    """API: List season modifier overrides for a property."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import SeasonModifierOverride
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        season_id = request.GET.get('season_id')
        modifier_id = request.GET.get('modifier_id')
        
        overrides = SeasonModifierOverride.objects.filter(
            season__hotel=hotel
        ).select_related('modifier', 'modifier__channel', 'season')
        
        if season_id:
            overrides = overrides.filter(season_id=season_id)
        if modifier_id:
            overrides = overrides.filter(modifier_id=modifier_id)
        
        overrides = overrides.order_by('season__start_date', 'modifier__channel__sort_order', 'modifier__sort_order')
        
        data = [{
            'id': o.id,
            'season_id': o.season_id,
            'season_name': o.season.name,
            'modifier_id': o.modifier_id,
            'modifier_name': o.modifier.name,
            'channel_name': o.modifier.channel.name,
            'discount_percent': str(o.discount_percent),
            'base_discount': str(o.modifier.discount_percent),
            'is_customized': o.is_customized,
            'notes': o.notes,
        } for o in overrides]
        
        return self.json_response({'overrides': data})


class SeasonModifierOverrideUpdateView(PricingManagementMixin, View):
    """API: Update a season modifier override."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import SeasonModifierOverride
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        override_id = kwargs.get('pk')
        override = get_object_or_404(
            SeasonModifierOverride, 
            pk=override_id, 
            season__hotel=hotel
        )
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'discount_percent' in data:
            new_discount = self.parse_decimal(data['discount_percent'], override.discount_percent)
            override.discount_percent = new_discount
            # Auto-mark as customized if different from base
            override.is_customized = (new_discount != override.modifier.discount_percent)
        
        if 'notes' in data:
            override.notes = data['notes']
        
        override.save()
        
        return self.success_response(
            message=f'Override for {override.modifier.name} in {override.season.name} updated'
        )


class SeasonModifierOverrideResetView(PricingManagementMixin, View):
    """API: Reset a season modifier override to base value."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import SeasonModifierOverride
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        override_id = kwargs.get('pk')
        override = get_object_or_404(
            SeasonModifierOverride, 
            pk=override_id, 
            season__hotel=hotel
        )
        
        override.reset_to_base()
        
        return self.success_response(
            data={'discount_percent': str(override.discount_percent)},
            message=f'Reset {override.modifier.name} in {override.season.name} to base ({override.discount_percent}%)'
        )


class SeasonModifierOverrideBulkPopulateView(PricingManagementMixin, View):
    """API: Populate all missing season modifier overrides for a property."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Season, RateModifier, SeasonModifierOverride
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        seasons = Season.objects.filter(hotel=hotel)
        modifiers = RateModifier.objects.filter(channel__hotel=hotel)
        
        created_count = 0
        
        with transaction.atomic():
            for season in seasons:
                for modifier in modifiers:
                    override, created = SeasonModifierOverride.objects.get_or_create(
                        modifier=modifier,
                        season=season,
                        defaults={'discount_percent': modifier.discount_percent}
                    )
                    if created:
                        created_count += 1
        
        return self.success_response(
            message=f'Created {created_count} season modifier overrides'
        )

"""
Organization Settings Views
============================

Admin views for managing organization and property settings.

URL Structure:
    /<org_code>/settings/                    - Organization settings page
    /<org_code>/api/organization/update/     - Update organization
    /<org_code>/<prop_code>/api/property/update/ - Update property
    /<org_code>/api/properties/create/       - Create new property
    /<org_code>/api/properties/<pk>/delete/  - Delete property
"""

from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Sum, Count
from decimal import Decimal, InvalidOperation
import json


# =============================================================================
# BASE MIXIN
# =============================================================================

# =============================================================================
# ORGANIZATION API
# =============================================================================

class OrganizationUpdateView(SettingsMixin, View):
    """Update organization details."""
    
    def post(self, request, *args, **kwargs):
        try:
            org = self.get_organization()
            data = json.loads(request.body)
            
            # Updatable fields
            if 'name' in data:
                name = data['name'].strip()
                if not name:
                    return self.error_response('Organization name is required')
                org.name = name
            
            if 'default_currency' in data:
                org.default_currency = data['default_currency'].upper()[:3]
            
            if 'currency_symbol' in data:
                org.currency_symbol = data['currency_symbol'][:5]
            
            org.save()
            
            return self.success_response(
                data={
                    'id': org.id,
                    'name': org.name,
                    'code': org.code,
                    'default_currency': org.default_currency,
                    'currency_symbol': org.currency_symbol,
                },
                message='Organization updated successfully'
            )
            
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        except Exception as e:
            return self.error_response(str(e))


# =============================================================================
# PROPERTY API
# =============================================================================

class PropertyUpdateView(SettingsMixin, View):
    """Update property details."""
    
    def post(self, request, *args, **kwargs):
        try:
            prop = self.get_property()
            data = json.loads(request.body)
            
            # Basic info
            if 'name' in data:
                name = data['name'].strip()
                if not name:
                    return self.error_response('Property name is required')
                prop.name = name
            
            if 'location' in data:
                prop.location = data['location'].strip()
            
            if 'currency_symbol' in data:
                prop.currency_symbol = data['currency_symbol'][:5]
            
            if 'reference_base_rate' in data:
                prop.reference_base_rate = self.parse_decimal(data['reference_base_rate'], Decimal('100.00'))
            
            # Tax & Service Charge settings
            if 'service_charge_percent' in data:
                prop.service_charge_percent = self.parse_decimal(data['service_charge_percent'], Decimal('10.00'))
            
            if 'tax_percent' in data:
                prop.tax_percent = self.parse_decimal(data['tax_percent'], Decimal('16.00'))
            
            if 'tax_on_service_charge' in data:
                prop.tax_on_service_charge = bool(data['tax_on_service_charge'])
            
            prop.save()
            
            return self.success_response(
                data={
                    'id': prop.id,
                    'name': prop.name,
                    'code': prop.code,
                    'location': prop.location,
                    'reference_base_rate': str(prop.reference_base_rate),
                    'currency_symbol': prop.currency_symbol,
                    'service_charge_percent': str(getattr(prop, 'service_charge_percent', '10.00')),
                    'tax_percent': str(getattr(prop, 'tax_percent', '16.00')),
                    'tax_on_service_charge': getattr(prop, 'tax_on_service_charge', True),
                },
                message='Property updated successfully'
            )
            
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        except Exception as e:
            return self.error_response(str(e))


class PropertyCreateView(SettingsMixin, View):
    """Create a new property."""
    
    def post(self, request, *args, **kwargs):
        try:
            from pricing.models import Property
            
            org = self.get_organization()
            data = json.loads(request.body)
            
            name = data.get('name', '').strip()
            code = data.get('code', '').strip().lower()
            
            if not name:
                return self.error_response('Property name is required')
            
            if not code:
                # Auto-generate code from name
                import re
                code = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            
            # Check for duplicate code
            if Property.objects.filter(organization=org, code=code).exists():
                return self.error_response(f'Property code "{code}" already exists')
            
            prop = Property.objects.create(
                organization=org,
                name=name,
                code=code,
                location=data.get('location', ''),
                reference_base_rate=self.parse_decimal(data.get('reference_base_rate'), Decimal('100.00')),
                currency_symbol=data.get('currency_symbol', '$'),
            )
            
            return self.success_response(
                data={
                    'id': prop.id,
                    'name': prop.name,
                    'code': prop.code,
                    'location': prop.location,
                },
                message='Property created successfully'
            )
            
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        except Exception as e:
            return self.error_response(str(e))


class PropertyDeleteView(SettingsMixin, View):
    """Soft-delete a property (set is_active=False)."""
    
    def post(self, request, *args, **kwargs):
        try:
            from pricing.models import Property
            
            org = self.get_organization()
            pk = self.kwargs.get('pk')
            
            prop = get_object_or_404(Property, pk=pk, organization=org)
            
            # Soft delete
            prop.is_active = False
            prop.save()
            
            return self.success_response(message=f'Property "{prop.name}" has been deactivated')
            
        except Exception as e:
            return self.error_response(str(e))



# =============================================================================
# ROOM TYPE SEASON MODIFIERS
# =============================================================================

class RoomTypeSeasonModifierListView(PricingManagementMixin, View):
    """Get all room type season modifiers for this property as a grid."""
    
    def get(self, request, *args, **kwargs):
        prop = self.get_property()
        from pricing.models import RoomTypeSeasonModifier, Season, RoomType
        
        seasons = Season.objects.filter(hotel=prop).order_by('start_date')
        room_types = RoomType.objects.filter(hotel=prop).order_by('sort_order')
        
        # Build grid: {room_id: {season_id: modifier_value}}
        existing = {}
        for mod in RoomTypeSeasonModifier.objects.filter(room_type__hotel=prop):
            existing.setdefault(mod.room_type_id, {})[mod.season_id] = {
                'id': mod.id,
                'modifier': float(mod.modifier),
                'notes': mod.notes,
                'effective_index': float(mod.get_effective_index()),
            }
        
        grid = []
        for room in room_types:
            row = {
                'room_type_id': room.id,
                'room_type_name': room.name,
                'effective_rate': float(room.get_effective_base_rate()),
                'premium_percent': float(room.get_premium_percent()),
                'target_occupancy': float(room.target_occupancy),
                'description': room.description,
                'seasons': {},
            }
            for season in seasons:
                if room.id in existing and season.id in existing[room.id]:
                    row['seasons'][season.id] = existing[room.id][season.id]
                else:
                    row['seasons'][season.id] = {
                        'id': None,
                        'modifier': 1.0,
                        'notes': '',
                        'effective_index': float(season.season_index),
                    }
            grid.append(row)
        
        season_list = [{'id': s.id, 'name': s.name, 'index': float(s.season_index)} for s in seasons]
        
        return JsonResponse({
            'success': True,
            'seasons': season_list,
            'grid': grid,
        })


class RoomTypeSeasonModifierUpdateView(PricingManagementMixin, View):
    """Create or update a room type season modifier."""
    
    def post(self, request, *args, **kwargs):
        try:
            prop = self.get_property()
            data = json.loads(request.body)
            
            from pricing.models import RoomTypeSeasonModifier, RoomType, Season
            
            room_type_id = data.get('room_type_id')
            season_id = data.get('season_id')
            modifier_value = self.parse_decimal(data.get('modifier', '1.00'))
            notes = data.get('notes', '')
            
            room_type = RoomType.objects.get(id=room_type_id, hotel=prop)
            season = Season.objects.get(id=season_id, hotel=prop)
            
            obj, created = RoomTypeSeasonModifier.objects.update_or_create(
                room_type=room_type,
                season=season,
                defaults={
                    'modifier': modifier_value,
                    'notes': notes,
                }
            )
            
            return self.success_response(
                message=f'{"Created" if created else "Updated"} modifier for {room_type.name} × {season.name}',
                data={
                    'id': obj.id,
                    'modifier': float(obj.modifier),
                    'effective_index': float(obj.get_effective_index()),
                    'notes': obj.notes,
                }
            )
        except Exception as e:
            return self.error_response(str(e))


class RoomTypeSeasonModifierBulkUpdateView(PricingManagementMixin, View):
    """Bulk update all room type season modifiers at once."""
    
    def post(self, request, *args, **kwargs):
        try:
            prop = self.get_property()
            data = json.loads(request.body)
            
            from pricing.models import RoomTypeSeasonModifier, RoomType, Season
            
            updates = data.get('updates', [])
            count = 0
            
            for item in updates:
                room_type_id = item.get('room_type_id')
                season_id = item.get('season_id')
                modifier_value = self.parse_decimal(item.get('modifier', '1.00'))
                notes = item.get('notes', '')
                
                room_type = RoomType.objects.get(id=room_type_id, hotel=prop)
                season = Season.objects.get(id=season_id, hotel=prop)
                
                RoomTypeSeasonModifier.objects.update_or_create(
                    room_type=room_type,
                    season=season,
                    defaults={
                        'modifier': modifier_value,
                        'notes': notes,
                    }
                )
                count += 1
            
            return self.success_response(
                message=f'Updated {count} room type season modifiers'
            )
        except Exception as e:
            return self.error_response(str(e))


class RoomTypeSeasonModifierResetView(PricingManagementMixin, View):
    """Reset a room type season modifier to 1.00 (delete the record)."""
    
    def post(self, request, *args, **kwargs):
        try:
            prop = self.get_property()
            data = json.loads(request.body)
            
            from pricing.models import RoomTypeSeasonModifier, RoomType, Season
            
            room_type_id = data.get('room_type_id')
            season_id = data.get('season_id')
            
            deleted, _ = RoomTypeSeasonModifier.objects.filter(
                room_type_id=room_type_id,
                room_type__hotel=prop,
                season_id=season_id,
            ).delete()
            
            return self.success_response(
                message='Modifier reset to 1.00' if deleted else 'No modifier to reset'
            )
        except Exception as e:
            return self.error_response(str(e))


# =============================================================================
# IMPORT TEMPLATE API VIEWS
# =============================================================================

class ImportUploadView(PricingManagementMixin, View):
    """POST: Upload a file and get headers + preview."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return self.error_response('No file uploaded')

        import tempfile, os

        # Save to temp
        suffix = os.path.splitext(uploaded_file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            from pricing.services.analytics_service import ImportTemplateService

            svc = ImportTemplateService(hotel)
            result = svc.read_headers(tmp_path)

            if 'error' in result:
                return self.error_response(result['error'])

            # Store temp path in session for later import execution
            request.session['import_tmp_path'] = tmp_path
            request.session['import_filename'] = uploaded_file.name

            # Auto-detect mapping
            auto = svc.auto_map(result['headers'])

            # Try to match a saved template
            template_match = svc.detect_template(result['headers'], hotel)

            # Get field definitions for the UI
            fields = svc.get_field_definitions('reservation')

            return self.success_response(data={
                'filename': uploaded_file.name,
                'headers': result['headers'],
                'preview': result['preview'],
                'row_count': result['row_count'],
                'file_type': result['file_type'],
                'skip_rows': result['skip_rows'],
                'auto_detected': auto['detected'],
                'unmatched_headers': auto['unmatched'],
                'template_match': template_match,
                'field_definitions': fields,
            })
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return self.error_response(str(e))


class ImportExecuteView(PricingManagementMixin, View):
    """POST: Execute import with provided column mapping."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        import os

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        column_map = data.get('column_map', {})
        value_transforms = data.get('value_transforms', {})
        template_id = data.get('template_id')
        import_type = data.get('import_type', 'reservation')

        # Get the temp file from session
        tmp_path = request.session.get('import_tmp_path')
        if not tmp_path or not os.path.exists(tmp_path):
            return self.error_response('No file uploaded. Please upload a file first.')

        # Validate required fields mapped
        required = {'confirmation_no', 'arrival_date', 'departure_date'}
        mapped_fields = set(k for k, v in column_map.items() if v)
        missing = required - mapped_fields
        if missing:
            return self.error_response(f'Required fields not mapped: {", ".join(sorted(missing))}')

        # Load template if specified
        template = None
        if template_id:
            from pricing.models import ImportTemplate
            try:
                template = ImportTemplate.objects.get(pk=template_id, is_active=True)
            except ImportTemplate.DoesNotExist:
                pass

        try:
            from pricing.services.analytics_service import ImportTemplateService

            svc = ImportTemplateService(hotel)
            result = svc.execute_import(
                file_path=tmp_path,
                column_map=column_map,
                hotel=hotel,
                template=template,
                value_transforms=value_transforms,
                import_type=import_type,
            )

            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            request.session.pop('import_tmp_path', None)
            request.session.pop('import_filename', None)

            return self.success_response(
                data=result,
                message=f"Import complete: {result.get('rows_created', 0)} created, "
                        f"{result.get('rows_updated', 0)} updated, "
                        f"{result.get('rows_skipped', 0)} skipped"
            )
        except Exception as e:
            return self.error_response(str(e))


class ImportTemplateListView(PricingManagementMixin, View):
    """GET: List saved import templates for this property."""

    def get(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        from pricing.models import ImportTemplate

        templates = ImportTemplate.objects.filter(
            Q(hotel=hotel) | Q(organization=hotel.organization, hotel__isnull=True),
            is_active=True,
        ).order_by('-use_count', 'name')

        data = []
        for t in templates:
            data.append({
                'id': t.id,
                'name': t.name,
                'import_type': t.import_type,
                'import_type_display': t.get_import_type_display(),
                'column_map': t.column_map,
                'value_transforms': t.value_transforms,
                'settings': t.settings,
                'source_headers': t.source_headers,
                'is_default': t.is_default,
                'use_count': t.use_count,
                'last_used_at': t.last_used_at.isoformat() if t.last_used_at else None,
                'scope': 'property' if t.hotel else 'organization',
            })

        return self.success_response(data={'templates': data})


class ImportTemplateSaveView(PricingManagementMixin, View):
    """POST: Save a new import template."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        from pricing.models import ImportTemplate

        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Template name is required')

        import_type = data.get('import_type', 'reservation')
        column_map = data.get('column_map', {})
        value_transforms = data.get('value_transforms', {})
        source_headers = data.get('source_headers', [])
        settings = data.get('settings', {})
        scope = data.get('scope', 'property')

        template = ImportTemplate.objects.create(
            hotel=hotel if scope == 'property' else None,
            organization=hotel.organization if scope == 'organization' else None,
            name=name,
            import_type=import_type,
            column_map=column_map,
            value_transforms=value_transforms,
            source_headers=source_headers,
            settings=settings,
        )

        return self.success_response(
            data={'id': template.id, 'name': template.name},
            message=f'Template "{name}" saved'
        )


class ImportTemplateUpdateView(PricingManagementMixin, View):
    """POST: Update an existing import template."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = self.kwargs.get('pk')

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        from pricing.models import ImportTemplate

        template = ImportTemplate.objects.filter(
            Q(hotel=hotel) | Q(organization=hotel.organization),
            pk=pk, is_active=True,
        ).first()

        if not template:
            return self.error_response('Template not found', 404)

        if 'name' in data:
            template.name = data['name'].strip()
        if 'column_map' in data:
            template.column_map = data['column_map']
        if 'value_transforms' in data:
            template.value_transforms = data['value_transforms']
        if 'source_headers' in data:
            template.source_headers = data['source_headers']
        if 'settings' in data:
            template.settings = data['settings']
        if 'is_default' in data:
            template.is_default = bool(data['is_default'])

        template.save()

        return self.success_response(message=f'Template "{template.name}" updated')


class ImportTemplateDeleteView(PricingManagementMixin, View):
    """POST: Soft-delete an import template."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = self.kwargs.get('pk')

        from pricing.models import ImportTemplate

        template = ImportTemplate.objects.filter(
            Q(hotel=hotel) | Q(organization=hotel.organization),
            pk=pk, is_active=True,
        ).first()

        if not template:
            return self.error_response('Template not found', 404)

        template.is_active = False
        template.save()

        return self.success_response(message=f'Template "{template.name}" deleted')


class ReservationListView(PricingManagementMixin, View):
    """GET: List reservations with pagination, search, and filters."""

    def get(self, request, *args, **kwargs):
        from pricing.models import Reservation
        import math

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        qs = Reservation.objects.filter(hotel=hotel).select_related(
            'guest', 'booking_source', 'room_type', 'rate_plan'
        )

        # Search
        search = request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(confirmation_no__icontains=search) |
                Q(guest__name__icontains=search) |
                Q(room_type_name__icontains=search)
            )

        # Status filter
        status = request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        # Date range filter (arrival_date)
        date_from = self.parse_date(request.GET.get('date_from'))
        date_to = self.parse_date(request.GET.get('date_to'))
        if date_from:
            qs = qs.filter(arrival_date__gte=date_from)
        if date_to:
            qs = qs.filter(arrival_date__lte=date_to)

        # Ordering
        qs = qs.order_by('-arrival_date', '-booking_date')

        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 25)), 100)
        total_count = qs.count()
        total_pages = max(1, math.ceil(total_count / page_size))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        reservations = []
        for r in qs[offset:offset + page_size]:
            reservations.append({
                'id': r.id,
                'confirmation_no': r.confirmation_no,
                'booking_date': str(r.booking_date) if r.booking_date else '',
                'arrival_date': str(r.arrival_date) if r.arrival_date else '',
                'departure_date': str(r.departure_date) if r.departure_date else '',
                'nights': r.nights,
                'adults': r.adults,
                'children': r.children,
                'room_type_name': r.room_type_name or (r.room_type.name if r.room_type else ''),
                'rate_plan_name': r.rate_plan_name or (r.rate_plan.name if r.rate_plan else ''),
                'total_amount': str(r.total_amount),
                'adr': str(r.adr),
                'status': r.status,
                'guest_name': r.guest.name if r.guest else '',
                'source_name': r.booking_source.name if r.booking_source and r.booking_source.name != 'Unknown' else '',
                'cancellation_date': str(r.cancellation_date) if r.cancellation_date else '',
            })

        return self.success_response(data={
            'reservations': reservations,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_count': total_count,
        })


class ReservationUpdateView(PricingManagementMixin, View):
    """POST: Update reservation fields."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Reservation

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = kwargs.get('pk')
        res = get_object_or_404(Reservation, pk=pk, hotel=hotel)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        if 'confirmation_no' in data:
            val = str(data['confirmation_no']).strip()
            if not val:
                return self.error_response('Confirmation number cannot be empty')
            res.confirmation_no = val

        if 'booking_date' in data:
            d = self.parse_date(data['booking_date'])
            if not d:
                return self.error_response('Invalid booking date')
            res.booking_date = d

        if 'arrival_date' in data:
            d = self.parse_date(data['arrival_date'])
            if not d:
                return self.error_response('Invalid arrival date')
            res.arrival_date = d

        if 'departure_date' in data:
            d = self.parse_date(data['departure_date'])
            if not d:
                return self.error_response('Invalid departure date')
            res.departure_date = d

        if 'nights' in data:
            try:
                res.nights = max(1, int(data['nights']))
            except (ValueError, TypeError):
                return self.error_response('Invalid nights value')

        if 'adults' in data:
            try:
                res.adults = max(0, int(data['adults']))
            except (ValueError, TypeError):
                return self.error_response('Invalid adults value')

        if 'children' in data:
            try:
                res.children = max(0, int(data['children']))
            except (ValueError, TypeError):
                return self.error_response('Invalid children value')

        if 'room_type_name' in data:
            res.room_type_name = str(data['room_type_name']).strip()

        if 'rate_plan_name' in data:
            res.rate_plan_name = str(data['rate_plan_name']).strip()

        if 'total_amount' in data:
            res.total_amount = self.parse_decimal(data['total_amount'], res.total_amount)

        if 'status' in data:
            valid = ['confirmed', 'cancelled', 'checked_in', 'checked_out', 'no_show']
            if data['status'] in valid:
                res.status = data['status']

        if 'cancellation_date' in data:
            val = data['cancellation_date']
            if val:
                d = self.parse_date(val)
                res.cancellation_date = d
            else:
                res.cancellation_date = None

        if 'notes' in data:
            res.notes = str(data['notes']).strip()

        # save() auto-recalculates adr and lead_time_days
        res.save()

        return self.success_response(message='Reservation updated')


class ReservationDeleteView(PricingManagementMixin, View):
    """POST: Delete a reservation."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Reservation

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = kwargs.get('pk')
        res = get_object_or_404(Reservation, pk=pk, hotel=hotel)
        conf = res.confirmation_no
        res.delete()

        return self.success_response(message=f'Reservation {conf} deleted')


class ReservationBulkDeleteView(PricingManagementMixin, View):
    """POST: Delete multiple reservations by ID list."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Reservation

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        ids = data.get('ids', [])
        if not ids or not isinstance(ids, list):
            return self.error_response('No reservation IDs provided')

        qs = Reservation.objects.filter(hotel=hotel, pk__in=ids)
        count = qs.count()
        qs.delete()

        return self.success_response(
            data={'deleted_count': count},
            message=f'{count} reservation{"s" if count != 1 else ""} deleted'
        )


class RoomTypeMappingListView(PricingManagementMixin, View):
    """GET: List distinct room_type_name values with their mapping status."""

    def get(self, request, *args, **kwargs):
        from pricing.models import Reservation, RoomType
        from django.db.models import Count

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        mappings_qs = Reservation.objects.filter(hotel=hotel).values(
            'room_type_name', 'room_type', 'room_type__name'
        ).annotate(count=Count('id')).order_by('-count')

        mappings = []
        for m in mappings_qs:
            mappings.append({
                'room_type_name': m['room_type_name'] or '',
                'count': m['count'],
                'mapped_to_id': m['room_type'],
                'mapped_to_name': m['room_type__name'] or None,
            })

        room_types = [
            {'id': rt.id, 'name': rt.name}
            for rt in RoomType.objects.filter(hotel=hotel).order_by('sort_order')
        ]
        unmapped_count = Reservation.objects.filter(hotel=hotel, room_type__isnull=True).count()

        return self.success_response(data={
            'mappings': mappings,
            'room_types': room_types,
            'unmapped_count': unmapped_count,
        })


class RoomTypeMappingUpdateView(PricingManagementMixin, View):
    """POST: Bulk-update room_type FK for all reservations matching a room_type_name."""

    def post(self, request, *args, **kwargs):
        from pricing.models import Reservation, RoomType

        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        room_type_name = data.get('room_type_name', '')
        room_type_id = data.get('room_type_id')

        if not room_type_name:
            return self.error_response('room_type_name is required')

        qs = Reservation.objects.filter(hotel=hotel, room_type_name=room_type_name)
        count = qs.count()

        if room_type_id:
            room_type = RoomType.objects.filter(pk=room_type_id, hotel=hotel).first()
            if not room_type:
                return self.error_response('Room type not found', 404)
            qs.update(room_type=room_type)
            return self.success_response(
                message=f'{count} reservations mapped to "{room_type.name}"'
            )
        else:
            qs.update(room_type=None)
            return self.success_response(
                message=f'{count} reservations unmapped'
            )


# =============================================================================
# TRAVEL AGENTS MANAGEMENT
# =============================================================================

class ManageAgentsView(ManageBaseMixin, TemplateView):
    """Management page for travel agents and their unique URLs."""
    template_name = 'pricing/manage/agents.html'
    active_section = 'agents'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hotel = context.get('hotel')
        if hotel:
            agents = TravelAgent.objects.filter(
                property=hotel
            ).select_related('channel').order_by('name')
            context['agents'] = agents
            context['channels'] = Channel.objects.filter(hotel=hotel).order_by('name')
        return context


class TravelAgentListView(PricingManagementMixin, View):
    """API: List all travel agents for this property."""

    def get(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found')

        agents = TravelAgent.objects.filter(
            property=hotel
        ).select_related('channel').order_by('name')

        data = [{
            'id': a.id,
            'name': a.name,
            'email': a.email,
            'channel_id': a.channel_id,
            'channel_name': a.channel.name if a.channel else 'Default',
            'token': a.token,
            'url': a.get_absolute_url(),
            'is_active': a.is_active,
            'notes': a.notes,
            'created_at': a.created_at.strftime('%Y-%m-%d'),
        } for a in agents]

        return self.json_response({'agents': data})


class TravelAgentCreateView(PricingManagementMixin, View):
    """API: Create a new travel agent."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found')

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Agent name is required')

        channel_id = data.get('channel_id')
        channel = None
        if channel_id:
            channel = Channel.objects.filter(pk=channel_id, hotel=hotel).first()

        agent = TravelAgent.objects.create(
            property=hotel,
            channel=channel,
            name=name,
            email=data.get('email', '').strip(),
            notes=data.get('notes', '').strip(),
        )

        return self.success_response(
            data={
                'id': agent.id,
                'name': agent.name,
                'token': agent.token,
                'url': agent.get_absolute_url(),
            },
            message=f'Agent "{agent.name}" created successfully'
        )


class TravelAgentUpdateView(PricingManagementMixin, View):
    """API: Update a travel agent."""

    def post(self, request, *args, **kwargs):
        agent_id = kwargs.get('pk')
        agent = get_object_or_404(TravelAgent, pk=agent_id)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')

        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return self.error_response('Name cannot be empty')
            agent.name = name

        if 'email' in data:
            agent.email = data['email'].strip()

        if 'notes' in data:
            agent.notes = data['notes'].strip()

        if 'is_active' in data:
            agent.is_active = bool(data['is_active'])

        if 'channel_id' in data:
            channel_id = data['channel_id']
            if channel_id:
                channel = Channel.objects.filter(pk=channel_id, hotel=agent.property).first()
                agent.channel = channel
            else:
                agent.channel = None

        agent.save()

        return self.success_response(
            message=f'Agent "{agent.name}" updated successfully'
        )


class TravelAgentDeleteView(PricingManagementMixin, View):
    """API: Delete a travel agent."""

    def post(self, request, *args, **kwargs):
        agent_id = kwargs.get('pk')
        agent = get_object_or_404(TravelAgent, pk=agent_id)
        name = agent.name
        agent.delete()

        return self.success_response(
            message=f'Agent "{name}" deleted successfully'
        )


class ManageCompetitiveView(ManageBaseMixin, TemplateView):
    """Management page for competitive set and market position."""
    template_name = 'pricing/manage/competitive.html'
    active_section = 'competitive'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import CompetitiveSet, MarketPosition
        hotel = context.get('hotel')
        if hotel:
            context['competitors'] = CompetitiveSet.objects.filter(
                hotel=hotel
            ).order_by('-bb_rate')
            try:
                context['market_position'] = MarketPosition.objects.get(hotel=hotel)
            except MarketPosition.DoesNotExist:
                context['market_position'] = None
            context['position_choices'] = CompetitiveSet.POSITION_CHOICES
            context['strategy_choices'] = MarketPosition.POSITION_STRATEGY
        return context


class CompetitiveSetUploadView(PropertyMixin, View):
    """Handle CSV/Excel upload for competitive set."""

    def post(self, request, *args, **kwargs):
        prop = self.get_property()
        file = request.FILES.get('file')

        if not file:
            return JsonResponse({'success': False, 'error': 'No file uploaded'})

        import tempfile, os
        ext = os.path.splitext(file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            from pricing.services import CompetitiveImportService
            svc = CompetitiveImportService(property=prop)
            result = svc.import_file(tmp_path)
            return JsonResponse({'success': True, 'data': result})
        finally:
            os.unlink(tmp_path)


class CompetitorCreateView(PricingManagementMixin, View):
    """API: Create a competitor."""

    def post(self, request, *args, **kwargs):
        from pricing.models import CompetitiveSet
        hotel = self.get_hotel(request)
        data = json.loads(request.body)

        name = data.get('competitor_name', '').strip()
        if not name:
            return self.error_response('Competitor name is required')

        if CompetitiveSet.objects.filter(hotel=hotel, competitor_name=name).exists():
            return self.error_response(f'Competitor "{name}" already exists')

        CompetitiveSet.objects.create(
            hotel=hotel,
            competitor_name=name,
            bb_rate=data.get('bb_rate') or None,
            hb_rate=data.get('hb_rate') or None,
            fb_rate=data.get('fb_rate') or None,
            rating=data.get('rating') or None,
            total_rooms=data.get('total_rooms') or 0,
            position=data.get('position', 'mid'),
            notes=data.get('notes', ''),
            source=data.get('source', 'Manual'),
        )
        return self.success_response(message=f'Competitor "{name}" added')


class CompetitorUpdateView(PricingManagementMixin, View):
    """API: Update a competitor field."""

    def post(self, request, *args, **kwargs):
        from pricing.models import CompetitiveSet
        comp_id = kwargs.get('pk')
        comp = get_object_or_404(CompetitiveSet, pk=comp_id)
        data = json.loads(request.body)

        allowed = ['competitor_name', 'bb_rate', 'hb_rate', 'fb_rate', 'rating',
                    'total_rooms', 'position', 'notes', 'source', 'is_active']

        for field, value in data.items():
            if field in allowed:
                if field in ('bb_rate', 'hb_rate', 'fb_rate', 'rating'):
                    value = Decimal(str(value)) if value not in ('', None) else None
                elif field == 'total_rooms':
                    value = int(value) if value not in ('', None) else 0
                elif field == 'is_active':
                    value = bool(value)
                setattr(comp, field, value)

        comp.save()
        return self.success_response(message='Competitor updated')


class CompetitorDeleteView(PricingManagementMixin, View):
    """API: Delete a competitor."""

    def post(self, request, *args, **kwargs):
        from pricing.models import CompetitiveSet
        comp_id = kwargs.get('pk')
        comp = get_object_or_404(CompetitiveSet, pk=comp_id)
        name = comp.competitor_name
        comp.delete()
        return self.success_response(message=f'Competitor "{name}" deleted')


class MarketPositionUpdateView(PricingManagementMixin, View):
    """API: Update market position settings."""

    def post(self, request, *args, **kwargs):
        from pricing.models import MarketPosition
        hotel = self.get_hotel(request)
        mp, _ = MarketPosition.objects.get_or_create(hotel=hotel)
        data = json.loads(request.body)

        allowed = ['strategy', 'bb_floor', 'bb_ceiling', 'hb_supplement',
                    'fb_supplement', 'notes']

        for field, value in data.items():
            if field in allowed:
                if field in ('bb_floor', 'bb_ceiling', 'hb_supplement', 'fb_supplement'):
                    value = Decimal(str(value)) if value not in ('', None) else Decimal('0')
                setattr(mp, field, value)

        mp.save()
        return self.success_response(message='Market position updated')


class MarketPositionRecalculateView(PricingManagementMixin, View):
    """API: Recalculate market position from competitors."""

    def post(self, request, *args, **kwargs):
        from pricing.models import MarketPosition
        hotel = self.get_hotel(request)
        mp, _ = MarketPosition.objects.get_or_create(hotel=hotel)
        stats = mp.recalculate_from_competitors()
        return self.success_response(
            message='Market position recalculated',
            data={
                'avg_bb': float(stats['avg_bb'] or 0),
                'median_bb': float(stats['median_bb'] or 0),
                'min_bb': float(stats['min_bb'] or 0),
                'max_bb': float(stats['max_bb'] or 0),
                'count': stats['count'],
                'bb_floor': float(mp.bb_floor),
                'bb_ceiling': float(mp.bb_ceiling),
            }
        )