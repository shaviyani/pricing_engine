"""
View mixins: OrganizationMixin, PropertyMixin, PricingManagementMixin, SettingsMixin.
"""

import json
import logging
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, View
from django.http import JsonResponse

from pricing.models import Organization, Property, Season, RoomType, RatePlan, Channel

logger = logging.getLogger(__name__)

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
class SettingsMixin:
    """Base mixin for settings views."""
    
    def get_organization(self):
        """Get organization from URL kwargs."""
        from pricing.models import Organization
        org_code = self.kwargs.get('org_code')
        return get_object_or_404(Organization, code=org_code, is_active=True)
    
    def get_property(self):
        """Get property from URL kwargs."""
        from pricing.models import Property
        org_code = self.kwargs.get('org_code')
        prop_code = self.kwargs.get('prop_code')
        return get_object_or_404(
            Property.objects.select_related('organization'),
            organization__code=org_code,
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

