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
    RateModifier, SeasonModifierOverride,
    ModifierTemplate, PropertyModifier, ModifierRule,
)
from pricing.services import PricingService

from .mixins import PricingManagementMixin, SettingsMixin

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
        
        context['rate_plan_count'] = RatePlan.objects.count()
        context['channel_count'] = Channel.objects.count()
        context['modifier_count'] = RateModifier.objects.count()
        context['property_count'] = org.properties.filter(is_active=True).count() if org else 0
        context['override_count'] = DateRateOverride.objects.filter(hotel=hotel, active=True).count() if hotel else 0
        context['import_count'] = FileImport.objects.filter(hotel=hotel).count() if hotel else 0
        context['source_count'] = BookingSource.objects.count()
        
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
        from pricing.models import RatePlan, Channel, RateModifier, SeasonModifierOverride
        
        hotel = context.get('hotel')
        
        context['rate_plans'] = RatePlan.objects.all().order_by('sort_order')
        context['channels'] = Channel.objects.all().prefetch_related('rate_modifiers').order_by('sort_order')
        context['rate_modifiers'] = RateModifier.objects.select_related('channel').order_by(
            'channel__sort_order', 'sort_order'
        )
        
        is_valid, total, message = Channel.validate_total_distribution()
        context['distribution_valid'] = is_valid
        context['distribution_total'] = total
        context['distribution_message'] = message
        
        if hotel:
            context['season_overrides'] = SeasonModifierOverride.objects.filter(
                season__hotel=hotel
            ).select_related('modifier', 'modifier__channel', 'season').order_by(
                'season__start_date', 'modifier__channel__sort_order', 'modifier__sort_order'
            )
        
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
        from pricing.models import FileImport, BookingSource
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
        
        return context


class ManageReportsView(ManageBaseMixin, TemplateView):
    """Reports: PDF exports, review analysis (future)."""
    template_name = 'pricing/manage/reports.html'
    active_section = 'reports'


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
        from pricing.models import Season
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
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
        from pricing.models import RoomType
        
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')
        
        # Get max sort order
        max_order = RoomType.objects.filter(hotel=hotel).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        room_type = RoomType.objects.create(
            hotel=hotel,
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
        from pricing.models import RatePlan
        
        rate_plans = RatePlan.objects.all().order_by('sort_order')
        
        data = [{
            'id': r.id,
            'name': r.name,
            'meal_supplement': str(r.meal_supplement),
            'sort_order': r.sort_order,
        } for r in rate_plans]
        
        return self.json_response({'rate_plans': data})


class RatePlanCreateView(PricingManagementMixin, View):
    """API: Create a new rate plan."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import RatePlan
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')
        
        max_order = RatePlan.objects.aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        rate_plan = RatePlan.objects.create(
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
        from pricing.models import Channel
        
        channels = Channel.objects.all().prefetch_related('rate_modifiers').order_by('sort_order')
        
        data = [{
            'id': c.id,
            'name': c.name,
            'base_discount_percent': str(c.base_discount_percent),
            'commission_percent': str(c.commission_percent),
            'distribution_share_percent': str(c.distribution_share_percent),
            'sort_order': c.sort_order,
            'modifier_count': c.rate_modifiers.count(),
        } for c in channels]
        
        # Distribution validation
        is_valid, total, message = Channel.validate_total_distribution()
        
        return self.json_response({
            'channels': data,
            'distribution_valid': is_valid,
            'distribution_total': str(total),
            'distribution_message': message,
        })


class ChannelCreateView(PricingManagementMixin, View):
    """API: Create a new channel."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Channel
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        name = data.get('name', '').strip()
        if not name:
            return self.error_response('Name is required')
        
        max_order = Channel.objects.aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        channel = Channel.objects.create(
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
        
        # Check for duplicate name
        if RateModifier.objects.filter(channel=channel, name=name).exists():
            return self.error_response(f'Modifier "{name}" already exists for {channel.name}')
        
        max_order = RateModifier.objects.filter(channel=channel).aggregate(
            max_order=models.Max('sort_order')
        )['max_order'] or 0
        
        modifier = RateModifier.objects.create(
            channel=channel,
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
        modifiers = RateModifier.objects.all()
        
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

class OrganizationSettingsView(SettingsMixin, TemplateView):
    """
    Organization settings dashboard.
    Shows organization details and all properties with their settings.
    """
    template_name = 'pricing/admin/organization_settings.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        org = self.get_organization()
        
        # Get all properties with stats
        properties = org.properties.filter(is_active=True).annotate(
            room_type_count=Count('room_types'),
            season_count=Count('seasons'),
            total_room_count=Sum('room_types__number_of_rooms')
        ).order_by('name')
        
        # Add property-specific settings
        properties_data = []
        for prop in properties:
            properties_data.append({
                'id': prop.id,
                'name': prop.name,
                'code': prop.code,
                'location': prop.location,
                'reference_base_rate': prop.reference_base_rate,
                'currency_symbol': prop.currency_symbol,
                'total_rooms': prop.total_room_count or 0,
                'room_type_count': prop.room_type_count,
                'season_count': prop.season_count,
                'service_charge_percent': getattr(prop, 'service_charge_percent', Decimal('10.00')),
                'tax_percent': getattr(prop, 'tax_percent', Decimal('16.00')),
                'tax_on_service_charge': getattr(prop, 'tax_on_service_charge', True),
                'is_active': prop.is_active,
            })
        
        context.update({
            'org': org,
            'organization': org,
            'properties': properties_data,
            'property_count': len(properties_data),
            'total_rooms': sum(p['total_rooms'] for p in properties_data),
        })
        
        return context


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