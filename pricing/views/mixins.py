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
# ORGANIZATION SETTINGS PAGE
# =============================================================================

