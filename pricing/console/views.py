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
from django.db.models import Count, Sum, Max, F, Q
from decimal import Decimal, InvalidOperation
from datetime import datetime
import json


# =============================================================================
# BASE MIXIN
# =============================================================================

class PricingManagementMixin:
    """Base mixin for pricing management views."""
    
    def get_hotel(self, request):
        """Get current hotel from URL kwargs."""
        from pricing.models import Property
        org_code = self.kwargs.get('org_code')
        prop_code = self.kwargs.get('prop_code')
        
        if org_code and prop_code:
            return get_object_or_404(
                Property.objects.select_related('organization'),
                organization__code=org_code,
                code=prop_code,
                is_active=True
            )
        return None
    
    def json_response(self, data, status=200):
        """Return JSON response."""
        return JsonResponse(data, status=status)
    
    def error_response(self, message, status=400):
        """Return error JSON response."""
        return JsonResponse({'success': False, 'error': message}, status=status)
    
    def success_response(self, data=None, message=None):
        """Return success JSON response."""
        response = {'success': True}
        if message:
            response['message'] = message
        if data:
            response['data'] = data
        return JsonResponse(response)
    
    def parse_decimal(self, value, default=Decimal('0.00')):
        """Safely parse decimal from string."""
        if value is None or value == '':
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return default
    
    def parse_date(self, value):
        """Parse date from string (YYYY-MM-DD)."""
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None


# =============================================================================
# PRICING MANAGEMENT DASHBOARD
# =============================================================================

class PricingManagementView(PricingManagementMixin, TemplateView):
    """
    Main pricing management dashboard.
    Shows all pricing components with inline editing.
    """
    template_name = 'console/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import (
            Season, RoomType, RatePlan, Channel, 
            RateModifier, SeasonModifierOverride
        )
        
        hotel = self.get_hotel(self.request)
        context['hotel'] = hotel
        
        if hotel:
            context['org_code'] = hotel.organization.code
            context['prop_code'] = hotel.code
            
            # Property-specific data
            context['seasons'] = Season.objects.filter(hotel=hotel).order_by('start_date')
            context['room_types'] = RoomType.objects.filter(hotel=hotel).order_by('sort_order')
            
            # Season modifier overrides for this property's seasons
            context['season_overrides'] = SeasonModifierOverride.objects.filter(
                season__hotel=hotel
            ).select_related('modifier', 'modifier__channel', 'season').order_by(
                'season__start_date', 'modifier__channel__sort_order', 'modifier__sort_order'
            )
        
        # Shared data (same for all properties)
        context['rate_plans'] = RatePlan.objects.all().order_by('sort_order')
        context['channels'] = Channel.objects.all().prefetch_related('rate_modifiers').order_by('sort_order')
        context['rate_modifiers'] = RateModifier.objects.select_related('channel').order_by(
            'channel__sort_order', 'sort_order'
        )
        
        # Distribution validation
        is_valid, total, message = Channel.validate_total_distribution()
        context['distribution_valid'] = is_valid
        context['distribution_total'] = total
        context['distribution_message'] = message
        
        return context


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
        )
        
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
        
        if 'discount_percent' in data:
            modifier.discount_percent = self.parse_decimal(
                data['discount_percent'], modifier.discount_percent
            )
        
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
        
        return self.success_response(message=f'Modifier "{modifier.name}" updated successfully')


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