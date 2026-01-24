from .models import Organization, Property


def organization_context(request):
    """
    Add organization and property context to all templates.
    
    Available in templates:
        {{ current_org }} - Current organization (from URL or session)
        {{ current_property }} - Current property (from URL or session)
        {{ all_organizations }} - All active organizations
        {{ user_properties }} - All properties user has access to
    """
    context = {
        'current_org': None,
        'current_property': None,
        'all_organizations': Organization.objects.filter(is_active=True),
        'user_properties': [],
    }
    
    # Try to get from URL kwargs
    if hasattr(request, 'resolver_match') and request.resolver_match:
        kwargs = request.resolver_match.kwargs
        org_code = kwargs.get('org_code')
        prop_code = kwargs.get('prop_code')
        
        if org_code:
            try:
                org = Organization.objects.get(code=org_code, is_active=True)
                context['current_org'] = org
                context['user_properties'] = org.properties.filter(is_active=True)
                
                if prop_code:
                    try:
                        prop = Property.objects.get(
                            organization=org, 
                            code=prop_code,
                            is_active=True
                        )
                        context['current_property'] = prop
                    except Property.DoesNotExist:
                        pass
            except Organization.DoesNotExist:
                pass
    
    # Fall back to session
    if not context['current_property']:
        property_id = request.session.get('current_property_id')
        if property_id:
            try:
                prop = Property.objects.select_related('organization').get(
                    pk=property_id,
                    is_active=True
                )
                context['current_property'] = prop
                context['current_org'] = prop.organization
                context['user_properties'] = prop.organization.properties.filter(is_active=True)
            except Property.DoesNotExist:
                pass
    
    return context