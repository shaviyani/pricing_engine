"""
View mixins: OrganizationMixin, PropertyMixin, PricingManagementMixin, SettingsMixin.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, View
from django.http import JsonResponse

from pricing.models import Organization, Property, Season, RoomType, RatePlan, Channel, PricingMatrixVersion, UserOrganizationRole

logger = logging.getLogger(__name__)

class OrganizationMixin:
    """
    Mixin to get organization from URL kwargs.
    Enforces that the logged-in user has a role in the organization.
    Superusers bypass the check.

    Adds to context:
        - organization: Organization instance
        - org: Shorthand alias
        - user_org_role: UserOrganizationRole instance (or None for superusers)
    """

    _cached_org = None
    _cached_user_role = None

    def get_organization(self):
        """Get organization by code from URL, with access check."""
        if self._cached_org:
            return self._cached_org
        org_code = self.kwargs.get('org_code')
        org = get_object_or_404(
            Organization.objects.filter(is_active=True),
            code=org_code
        )
        # Superusers bypass org access check
        user = self.request.user
        if not user.is_superuser:
            role = UserOrganizationRole.objects.filter(
                user=user, organization=org, is_active=True
            ).first()
            if not role:
                raise PermissionDenied("You do not have access to this organization.")
            self._cached_user_role = role
        self._cached_org = org
        return org

    def get_user_org_role(self):
        """Return the cached UserOrganizationRole for the current user/org."""
        if not self._cached_org:
            self.get_organization()
        return self._cached_user_role

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['organization'] = self.get_organization()
        context['org'] = context['organization']
        context['user_org_role'] = self.get_user_org_role()
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
        
        # Version info
        published = PricingMatrixVersion.get_published(prop)
        draft = PricingMatrixVersion.get_draft(prop)
        context['published_version'] = published
        context['draft_version'] = draft
        context['active_version'] = draft or published  # Draft takes priority for editing
        
        # Store in session for redirect convenience
        self.request.session['current_property_id'] = prop.id
        self.request.session['current_org_id'] = context['organization'].id

        context['nav_active'] = ''
        return context
    
    def get_property_querysets(self, prop, version=None):
        """
        Get common querysets filtered by property and version.
        
        All pricing models are now property-scoped AND versioned.
        If version is None, uses published version.
        """
        if version is None:
            version = PricingMatrixVersion.get_published(prop)
        
        base_filter = {'hotel': prop}
        if version:
            base_filter['version'] = version
        
        return {
            'seasons': Season.objects.filter(**base_filter).order_by('start_date'),
            'rooms': RoomType.objects.filter(**base_filter).order_by('sort_order'),
            'rate_plans': RatePlan.objects.filter(**base_filter).order_by('sort_order'),
            'channels': Channel.objects.filter(**base_filter).order_by('sort_order'),
            'version': version,
        }


class PricingManagementMixin:
    """Base mixin for pricing management views."""
    
    def get_hotel(self, request):
        """Get current hotel from URL kwargs, with org access check."""
        from pricing.models import Property
        org_code = self.kwargs.get('org_code')
        prop_code = self.kwargs.get('prop_code')

        if org_code and prop_code:
            prop = get_object_or_404(
                Property.objects.select_related('organization'),
                organization__code=org_code,
                code=prop_code,
                is_active=True
            )
            user = request.user
            if not user.is_superuser:
                has_role = UserOrganizationRole.objects.filter(
                    user=user, organization=prop.organization, is_active=True
                ).exists()
                if not has_role:
                    raise PermissionDenied("You do not have access to this organization.")
            return prop
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
# CRUD MIXIN (DRYs up Create / Update / Delete API views)
# =============================================================================

class ModelCrudMixin(PricingManagementMixin, View):
    """
    Declarative CRUD mixin for JSON API views.

    Subclasses set class attributes to configure behavior:

        model_class = Season                  # Django model
        model_label = 'Season'                # Human-readable name
        hotel_field = 'hotel'                 # FK field name pointing to Property
        lookup_field = 'pk'                   # URL kwarg used for update/delete

    For full CRUD, also set:

        list_key = 'seasons'                  # Key in JSON list response
        list_order = ['start_date']           # QuerySet ordering
        version_scoped = True                 # Filter by published version
        auto_sort_order = True                # Auto-increment sort_order on create

        fields = {
            'name':         {'type': 'str',     'required': True},
            'start_date':   {'type': 'date',    'required': True},
            'season_index': {'type': 'decimal', 'default': '1.00'},
            'number':       {'type': 'int',     'default': 1},
            'is_active':    {'type': 'bool',    'default': True},
        }

    Field types: str, decimal, date, int, bool.
    Fields marked required=True are validated on create.
    On update, only provided fields are applied (partial update).

    Override hooks for custom logic:
        serialize_item(obj)     — customize list serialization
        post_create(instance)   — after create hook
        validate_create(data, hotel) — extra validation, return error_response or None
        validate_update(data, instance) — extra validation, return error_response or None
    """

    model_class = None
    model_label = ''
    hotel_field = 'hotel'
    lookup_field = 'pk'

    # List configuration
    list_key = ''
    list_order = ['id']
    list_select_related = []
    list_prefetch_related = []
    version_scoped = False
    auto_sort_order = False

    # Field definitions
    fields = {}

    # -- helpers --------------------------------------------------------

    def _parse_body(self, request):
        """Parse JSON body; returns (data_dict, error_response)."""
        try:
            return json.loads(request.body), None
        except json.JSONDecodeError:
            return None, self.error_response('Invalid JSON')

    def _get_instance(self, hotel):
        """Fetch a model instance by lookup_field, scoped to hotel."""
        pk = self.kwargs.get(self.lookup_field)
        return get_object_or_404(
            self.model_class, pk=pk, **{self.hotel_field: hotel}
        )

    def _resolve_version(self, data, hotel):
        """Resolve PricingMatrixVersion from data or fallback to published."""
        vid = data.get('version_id')
        if vid:
            return get_object_or_404(PricingMatrixVersion, pk=vid, hotel=hotel)
        return PricingMatrixVersion.get_published(hotel)

    def _parse_field(self, field_name, value, field_config, current=None):
        """Parse a field value based on its type config."""
        ftype = field_config.get('type', 'str')
        default = field_config.get('default')
        if current is not None and default is None:
            default = current

        if ftype == 'str':
            return (value or '').strip() if value is not None else (default or '')
        elif ftype == 'decimal':
            return self.parse_decimal(value, Decimal(str(default)) if default is not None else Decimal('0.00'))
        elif ftype == 'date':
            return self.parse_date(value)
        elif ftype == 'int':
            try:
                return int(value) if value is not None else (default or 0)
            except (ValueError, TypeError):
                return default or 0
        elif ftype == 'bool':
            return bool(value) if value is not None else (default if default is not None else True)
        return value

    def _serialize_value(self, val):
        """Serialize a single value for JSON output."""
        if val is None:
            return None
        if hasattr(val, 'strftime'):
            return val.strftime('%Y-%m-%d')
        if isinstance(val, Decimal):
            return str(val)
        return val

    # -- List -----------------------------------------------------------

    def serialize_item(self, obj):
        """Serialize a model instance for list response. Override for custom fields."""
        result = {'id': obj.id}
        for field_name in self.fields:
            val = getattr(obj, field_name, None)
            result[field_name] = self._serialize_value(val)
        return result

    def get_queryset(self, hotel):
        """Get base queryset filtered by hotel."""
        qs = self.model_class.objects.filter(**{self.hotel_field: hotel})
        if self.version_scoped:
            version = PricingMatrixVersion.get_published(hotel)
            if version:
                qs = qs.filter(version=version)
        if self.list_select_related:
            qs = qs.select_related(*self.list_select_related)
        if self.list_prefetch_related:
            qs = qs.prefetch_related(*self.list_prefetch_related)
        return qs.order_by(*self.list_order)

    def list_items(self, request, *args, **kwargs):
        """Generic list handler. Wire ``get = list_items`` in subclass."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        qs = self.get_queryset(hotel)
        data = [self.serialize_item(obj) for obj in qs]
        return self.json_response({self.list_key: data})

    # -- Create ---------------------------------------------------------

    def validate_create(self, data, hotel):
        """Override to add custom create validation. Return error_response or None."""
        return None

    def post_create(self, instance):
        """Override for post-create logic."""
        pass

    def create_instance(self, request, *args, **kwargs):
        """Generic create handler. Wire ``post = create_instance`` in subclass."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        data, err = self._parse_body(request)
        if err:
            return err

        # Validate required fields
        for field_name, config in self.fields.items():
            if config.get('required') and not data.get(field_name, ''):
                label = field_name.replace('_', ' ').title()
                return self.error_response(f'{label} is required')

        # Custom validation
        err = self.validate_create(data, hotel)
        if err:
            return err

        # Build create kwargs
        create_kwargs = {self.hotel_field: hotel}

        if self.version_scoped:
            create_kwargs['version'] = self._resolve_version(data, hotel)

        if self.auto_sort_order and 'sort_order' not in data:
            from django.db import models as db_models
            max_order = self.model_class.objects.filter(
                **{self.hotel_field: hotel}
            ).aggregate(m=db_models.Max('sort_order'))['m'] or 0
            create_kwargs['sort_order'] = max_order + 1

        for field_name, config in self.fields.items():
            if field_name in data or config.get('default') is not None:
                create_kwargs[field_name] = self._parse_field(
                    field_name, data.get(field_name), config
                )

        instance = self.model_class.objects.create(**create_kwargs)
        self.post_create(instance)

        return self.success_response(
            data={'id': instance.id, 'name': str(instance)},
            message=f'{self.model_label} "{instance}" created successfully'
        )

    # -- Update ---------------------------------------------------------

    def validate_update(self, data, instance):
        """Override to add custom update validation. Return error_response or None."""
        return None

    def update_instance(self, request, *args, **kwargs):
        """Generic update handler. Wire ``post = update_instance`` in subclass."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        instance = self._get_instance(hotel)
        data, err = self._parse_body(request)
        if err:
            return err

        # Custom validation
        err = self.validate_update(data, instance)
        if err:
            return err

        for field_name, config in self.fields.items():
            if field_name in data:
                value = data[field_name]
                # Required field cannot be empty
                if config.get('required') and config.get('type') == 'str':
                    parsed = (value or '').strip()
                    if not parsed:
                        label = field_name.replace('_', ' ').title()
                        return self.error_response(f'{label} cannot be empty')
                current = getattr(instance, field_name, None)
                setattr(instance, field_name, self._parse_field(
                    field_name, value, config, current=current
                ))

        instance.save()
        return self.success_response(
            message=f'{self.model_label} "{instance}" updated successfully'
        )

    # -- Delete (works out-of-the-box) ----------------------------------

    def delete_instance(self, request, *args, **kwargs):
        """Generic delete handler. Wire ``post = delete_instance`` in subclass."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        instance = self._get_instance(hotel)
        name = str(instance)
        instance.delete()
        return self.success_response(
            message=f'{self.model_label} "{name}" deleted successfully'
        )

    # -- Dispatch (consolidated single-URL routing) ---------------------

    def dispatch(self, request, *args, **kwargs):
        """Route based on HTTP method and pk presence for consolidated URLs."""
        pk = kwargs.get(self.lookup_field)
        if request.method == 'GET':
            return self.list_items(request, *args, **kwargs)
        elif request.method == 'POST':
            if pk:
                return self.update_instance(request, *args, **kwargs)
            return self.create_instance(request, *args, **kwargs)
        elif request.method == 'PUT':
            return self.update_instance(request, *args, **kwargs)
        elif request.method == 'DELETE':
            return self.delete_instance(request, *args, **kwargs)
        return JsonResponse({'error': 'Method not allowed'}, status=405)


# =============================================================================
# CRUD CONFIGS — Declarative configurations for standard CRUD entities
# =============================================================================

class _SeasonCrud(ModelCrudMixin):
    """CRUD config for Season entity."""
    model_class = Season
    model_label = 'Season'
    list_key = 'seasons'
    list_order = ['start_date']
    version_scoped = True
    fields = {
        'name': {'type': 'str', 'required': True},
        'start_date': {'type': 'date', 'required': True},
        'end_date': {'type': 'date', 'required': True},
        'season_index': {'type': 'decimal', 'default': '1.00'},
        'expected_occupancy': {'type': 'decimal', 'default': '70.00'},
    }

    def serialize_item(self, obj):
        result = super().serialize_item(obj)
        result['date_range_display'] = obj.date_range_display()
        return result

    def validate_create(self, data, hotel):
        start = self.parse_date(data.get('start_date'))
        end = self.parse_date(data.get('end_date'))
        if not start or not end:
            return self.error_response('Valid start and end dates are required')
        if start > end:
            return self.error_response('Start date must be before end date')

    def validate_update(self, data, instance):
        start = self.parse_date(data.get('start_date')) if 'start_date' in data else instance.start_date
        end = self.parse_date(data.get('end_date')) if 'end_date' in data else instance.end_date
        if start and end and start > end:
            return self.error_response('Start date must be before end date')


class _RatePlanCrud(ModelCrudMixin):
    """CRUD config for RatePlan entity."""
    model_class = RatePlan
    model_label = 'Rate plan'
    list_key = 'rate_plans'
    list_order = ['sort_order']
    version_scoped = True
    auto_sort_order = True
    fields = {
        'name': {'type': 'str', 'required': True},
        'meal_supplement': {'type': 'decimal', 'default': '0.00'},
        'sort_order': {'type': 'int', 'default': 0},
    }


class _ChannelCrud(ModelCrudMixin):
    """CRUD config for Channel entity (create/update/delete only; list has custom logic)."""
    model_class = Channel
    model_label = 'Channel'
    list_key = 'channels'
    list_order = ['sort_order']
    version_scoped = True
    auto_sort_order = True
    fields = {
        'name': {'type': 'str', 'required': True},
        'base_discount_percent': {'type': 'decimal', 'default': '0.00'},
        'commission_percent': {'type': 'decimal', 'default': '0.00'},
        'distribution_share_percent': {'type': 'decimal', 'default': '0.00'},
        'sort_order': {'type': 'int', 'default': 0},
    }


class _RoomTypeCrud(ModelCrudMixin):
    """CRUD config for RoomType entity."""
    model_class = RoomType
    model_label = 'Room type'
    list_key = 'room_types'
    list_order = ['sort_order']
    version_scoped = True
    auto_sort_order = True
    fields = {
        'name': {'type': 'str', 'required': True},
        'base_rate': {'type': 'decimal', 'default': '0.00'},
        'room_index': {'type': 'decimal', 'default': '1.00'},
        'room_adjustment': {'type': 'decimal', 'default': '0.00'},
        'pricing_method': {'type': 'str', 'default': 'index'},
        'number_of_rooms': {'type': 'int', 'default': 1},
        'sort_order': {'type': 'int', 'default': 0},
        'description': {'type': 'str', 'default': ''},
        'target_occupancy': {'type': 'decimal', 'default': '70.00'},
    }

    def serialize_item(self, obj):
        result = super().serialize_item(obj)
        result['effective_rate'] = str(obj.get_effective_base_rate())
        result['premium_percent'] = str(obj.get_premium_percent())
        return result

    def create_instance(self, request, *args, **kwargs):
        """Override to use hotel.reference_base_rate as default for base_rate."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        data, err = self._parse_body(request)
        if err:
            return err

        # Set default base_rate from hotel if not provided
        if 'base_rate' not in data or not data['base_rate']:
            data['base_rate'] = str(hotel.reference_base_rate)

        # Re-inject body for parent method
        import io
        request._stream = io.BytesIO(json.dumps(data).encode())
        request._body = json.dumps(data).encode()

        return super().create_instance(request, *args, **kwargs)

    def validate_update(self, data, instance):
        """Validate pricing_method is one of the allowed values."""
        if 'pricing_method' in data:
            if data['pricing_method'] not in ('direct', 'index', 'adjustment'):
                return self.error_response('Invalid pricing method')
        if 'number_of_rooms' in data:
            try:
                val = int(data['number_of_rooms'])
                if val < 0:
                    data['number_of_rooms'] = 0
            except (ValueError, TypeError):
                data['number_of_rooms'] = instance.number_of_rooms


class _TravelAgentCrud(ModelCrudMixin):
    """CRUD config for TravelAgent entity."""
    model_label = 'Agent'
    hotel_field = 'property'
    list_key = 'agents'
    list_order = ['name']
    list_select_related = ['channel']
    fields = {
        'name': {'type': 'str', 'required': True},
        'email': {'type': 'str', 'default': ''},
        'notes': {'type': 'str', 'default': ''},
        'is_active': {'type': 'bool', 'default': True},
    }

    @property
    def model_class(self):
        from pricing.models import TravelAgent
        return TravelAgent

    def serialize_item(self, obj):
        return {
            'id': obj.id,
            'name': obj.name,
            'email': obj.email,
            'channel_id': obj.channel_id,
            'channel_name': obj.channel.name if obj.channel else 'Default',
            'token': obj.token,
            'url': obj.get_absolute_url(),
            'is_active': obj.is_active,
            'notes': obj.notes,
            'created_at': obj.created_at.strftime('%Y-%m-%d'),
        }

    def create_instance(self, request, *args, **kwargs):
        """Override to handle channel_id FK lookup."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        data, err = self._parse_body(request)
        if err:
            return err

        name = (data.get('name') or '').strip()
        if not name:
            return self.error_response('Agent name is required')

        channel_id = data.get('channel_id')
        channel = None
        if channel_id:
            channel = Channel.objects.filter(pk=channel_id, hotel=hotel).first()

        from pricing.models import TravelAgent
        agent = TravelAgent.objects.create(
            property=hotel,
            channel=channel,
            name=name,
            email=(data.get('email') or '').strip(),
            notes=(data.get('notes') or '').strip(),
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

    def update_instance(self, request, *args, **kwargs):
        """Override to handle channel_id FK lookup on update."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        instance = self._get_instance(hotel)
        data, err = self._parse_body(request)
        if err:
            return err

        if 'name' in data:
            name = (data['name'] or '').strip()
            if not name:
                return self.error_response('Name cannot be empty')
            instance.name = name

        if 'email' in data:
            instance.email = (data['email'] or '').strip()

        if 'notes' in data:
            instance.notes = (data['notes'] or '').strip()

        if 'is_active' in data:
            instance.is_active = bool(data['is_active'])

        if 'channel_id' in data:
            channel_id = data['channel_id']
            if channel_id:
                channel = Channel.objects.filter(pk=channel_id, hotel=instance.property).first()
                instance.channel = channel
            else:
                instance.channel = None

        instance.save()
        return self.success_response(
            message=f'Agent "{instance.name}" updated successfully'
        )


class _CompetitorCrud(ModelCrudMixin):
    """CRUD config for CompetitiveSet (Competitor) entity."""
    model_label = 'Competitor'
    list_key = 'competitors'
    list_order = ['-bb_rate']
    fields = {
        'competitor_name': {'type': 'str', 'required': True},
        'bb_rate': {'type': 'decimal'},
        'hb_rate': {'type': 'decimal'},
        'fb_rate': {'type': 'decimal'},
        'rating': {'type': 'decimal'},
        'total_rooms': {'type': 'int', 'default': 0},
        'position': {'type': 'str', 'default': 'mid'},
        'notes': {'type': 'str', 'default': ''},
        'source': {'type': 'str', 'default': 'Manual'},
        'is_active': {'type': 'bool', 'default': True},
    }

    @property
    def model_class(self):
        from pricing.models import CompetitiveSet
        return CompetitiveSet

    def create_instance(self, request, *args, **kwargs):
        """Override for duplicate-name validation and nullable rate fields."""
        from pricing.models import CompetitiveSet
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        data, err = self._parse_body(request)
        if err:
            return err

        name = (data.get('competitor_name') or '').strip()
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

    def update_instance(self, request, *args, **kwargs):
        """Override for allowed-field whitelist and nullable decimals."""
        from pricing.models import CompetitiveSet
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = self.kwargs.get(self.lookup_field)
        comp = get_object_or_404(CompetitiveSet, pk=pk)
        data, err = self._parse_body(request)
        if err:
            return err

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


class _ImportTemplateCrud(ModelCrudMixin):
    """CRUD config for ImportTemplate entity."""
    model_label = 'Template'
    list_key = 'templates'
    list_order = ['-use_count', 'name']
    fields = {
        'name': {'type': 'str', 'required': True},
    }

    @property
    def model_class(self):
        from pricing.models import ImportTemplate
        return ImportTemplate

    def get_queryset(self, hotel):
        """Templates can be property-scoped or org-scoped."""
        from pricing.models import ImportTemplate
        from django.db.models import Q
        return ImportTemplate.objects.filter(
            Q(hotel=hotel) | Q(organization=hotel.organization, hotel__isnull=True),
            is_active=True,
        ).order_by(*self.list_order)

    def serialize_item(self, obj):
        return {
            'id': obj.id,
            'name': obj.name,
            'import_type': obj.import_type,
            'import_type_display': obj.get_import_type_display(),
            'column_map': obj.column_map,
            'value_transforms': obj.value_transforms,
            'settings': obj.settings,
            'source_headers': obj.source_headers,
            'is_default': obj.is_default,
            'use_count': obj.use_count,
            'last_used_at': obj.last_used_at.isoformat() if obj.last_used_at else None,
            'scope': 'property' if obj.hotel else 'organization',
        }

    def list_items(self, request, *args, **kwargs):
        """Return templates wrapped in success_response to match original API."""
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        qs = self.get_queryset(hotel)
        data = [self.serialize_item(obj) for obj in qs]
        return self.success_response(data={'templates': data})

    def create_instance(self, request, *args, **kwargs):
        """Override for JSON field handling and scope logic."""
        from pricing.models import ImportTemplate
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        data, err = self._parse_body(request)
        if err:
            return err

        name = (data.get('name') or '').strip()
        if not name:
            return self.error_response('Template name is required')

        scope = data.get('scope', 'property')

        template = ImportTemplate.objects.create(
            hotel=hotel if scope == 'property' else None,
            organization=hotel.organization if scope == 'organization' else None,
            name=name,
            import_type=data.get('import_type', 'reservation'),
            column_map=data.get('column_map', {}),
            value_transforms=data.get('value_transforms', {}),
            source_headers=data.get('source_headers', []),
            settings=data.get('settings', {}),
        )

        return self.success_response(
            data={'id': template.id, 'name': template.name},
            message=f'Template "{name}" saved'
        )

    def update_instance(self, request, *args, **kwargs):
        """Override for JSON field handling and org/hotel scoping."""
        from pricing.models import ImportTemplate
        from django.db.models import Q
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = self.kwargs.get(self.lookup_field)
        data, err = self._parse_body(request)
        if err:
            return err

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

    def delete_instance(self, request, *args, **kwargs):
        """Soft-delete (set is_active=False) instead of hard delete."""
        from pricing.models import ImportTemplate
        from django.db.models import Q
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)

        pk = self.kwargs.get(self.lookup_field)
        template = ImportTemplate.objects.filter(
            Q(hotel=hotel) | Q(organization=hotel.organization),
            pk=pk, is_active=True,
        ).first()

        if not template:
            return self.error_response('Template not found', 404)

        template.is_active = False
        template.save()
        return self.success_response(message=f'Template "{template.name}" deleted')


# =============================================================================
# PRICING MANAGEMENT DASHBOARD
# =============================================================================
class SettingsMixin:
    """Base mixin for settings views."""

    def get_organization(self):
        """Get organization from URL kwargs, with access check."""
        from pricing.models import Organization
        org_code = self.kwargs.get('org_code')
        org = get_object_or_404(Organization, code=org_code, is_active=True)
        user = self.request.user
        if not user.is_superuser:
            has_role = UserOrganizationRole.objects.filter(
                user=user, organization=org, is_active=True
            ).exists()
            if not has_role:
                raise PermissionDenied("You do not have access to this organization.")
        return org

    def get_property(self):
        """Get property from URL kwargs."""
        from pricing.models import Property
        org = self.get_organization()  # includes access check
        prop_code = self.kwargs.get('prop_code')
        return get_object_or_404(
            Property.objects.select_related('organization'),
            organization=org,
            code=prop_code,
            is_active=True
        )
    
    def json_response(self, data, status=200):
        return JsonResponse(data, status=status)
    
    def error_response(self, message, status=400):
        return JsonResponse({'success': False, 'error': message}, status=status)
    
    def success_response(self, data=None, message=None):
        response = {'success': True}
        if message:
            response['message'] = message
        if data:
            response['data'] = data
        return JsonResponse(response)
    
    def parse_decimal(self, value, default=Decimal('0.00')):
        if value is None or value == '':
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return default


# =============================================================================
# ROLE-BASED ACCESS MIXINS
# =============================================================================

class RoleRequiredMixin:
    """
    Restrict view access based on UserOrganizationRole.
    Set `required_roles` on the view class, e.g. required_roles = ['admin', 'manager'].
    Superusers always have access.
    """
    required_roles = []

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        if not self.required_roles:
            return super().dispatch(request, *args, **kwargs)

        # Get user's role — try OrganizationMixin cache first, then DB lookup
        user_role = getattr(self, '_cached_user_role', None)
        if user_role is None:
            org_code = kwargs.get('org_code', '')
            if org_code:
                user_role = UserOrganizationRole.objects.filter(
                    user=request.user,
                    organization__code=org_code,
                    is_active=True,
                ).first()

        if user_role and user_role.role in self.required_roles:
            return super().dispatch(request, *args, **kwargs)

        # Denied — redirect to dashboard or return 403 for AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Access denied'}, status=403)

        from django.shortcuts import redirect
        org_code = kwargs.get('org_code', '')
        prop_code = kwargs.get('prop_code', '')
        if org_code and prop_code:
            return redirect('pricing:property_dashboard',
                            org_code=org_code, prop_code=prop_code)
        return redirect('pricing:root')


class AnalyticsAccessMixin(RoleRequiredMixin):
    """All roles can access analytics."""
    required_roles = ['admin', 'manager', 'sales', 'viewer']


class PricingAccessMixin(RoleRequiredMixin):
    """Only admin and manager can access pricing pages."""
    required_roles = ['admin', 'manager']


class DistributionAccessMixin(RoleRequiredMixin):
    """Admin, manager, and sales can access distribution."""
    required_roles = ['admin', 'manager', 'sales']


class SetupAccessMixin(RoleRequiredMixin):
    """Only admin can access setup pages."""
    required_roles = ['admin']


# =============================================================================
# ORGANIZATION SETTINGS PAGE
# =============================================================================

