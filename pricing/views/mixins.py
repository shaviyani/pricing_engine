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

    **Delete views** only need the above — inherit and you're done.

    **Create/Update views** override ``get_create_kwargs(data, hotel)``
    or ``apply_updates(instance, data)`` respectively.
    """

    model_class = None
    model_label = ''
    hotel_field = 'hotel'
    lookup_field = 'pk'

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

