from .models import Organization, Property, UserOrganizationRole


def organization_context(request):
    """
    Add organization and property context to all templates.

    Available in templates:
        {{ current_org }} - Current organization (from URL or session)
        {{ current_property }} - Current property (from URL or session)
        {{ all_organizations }} - Organizations the user has access to
        {{ user_properties }} - All properties user has access to
        {{ user_org_role }} - UserOrganizationRole for current org (None for superusers)
    """
    context = {
        'current_org': None,
        'current_property': None,
        'all_organizations': [],
        'user_properties': [],
        'user_org_role': None,
    }

    user = request.user
    if not user.is_authenticated:
        return context

    # Get organizations filtered by user access
    if user.is_superuser:
        context['all_organizations'] = Organization.objects.filter(is_active=True)
    else:
        user_org_ids = UserOrganizationRole.objects.filter(
            user=user, is_active=True
        ).values_list('organization_id', flat=True)
        context['all_organizations'] = Organization.objects.filter(
            id__in=user_org_ids, is_active=True
        )

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

                # Get user's role for this org
                if not user.is_superuser:
                    context['user_org_role'] = UserOrganizationRole.objects.filter(
                        user=user, organization=org, is_active=True
                    ).first()

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
                # Validate user has access to this org
                org = prop.organization
                if user.is_superuser or UserOrganizationRole.objects.filter(
                    user=user, organization=org, is_active=True
                ).exists():
                    context['current_property'] = prop
                    context['current_org'] = org
                    context['user_properties'] = org.properties.filter(is_active=True)
                    if not user.is_superuser:
                        context['user_org_role'] = UserOrganizationRole.objects.filter(
                            user=user, organization=org, is_active=True
                        ).first()
                else:
                    # Clear invalid session data
                    request.session.pop('current_property_id', None)
                    request.session.pop('current_org_id', None)
            except Property.DoesNotExist:
                pass

    return context