"""
Platform Data Views
===================

Superuser-only views for managing organizations, properties,
and market intelligence data.
"""

import json
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Sum, Count, Avg, Q, Max
from django.utils import timezone


class SuperuserRequiredMixin(UserPassesTestMixin):
    """Restrict access to superusers only."""
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_superuser
    
    def handle_no_permission(self):
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(self.request.get_full_path())


def success_response(data=None, message=''):
    resp = {'success': True}
    if data:
        resp['data'] = data
    if message:
        resp['message'] = message
    return JsonResponse(resp)


def error_response(message, status=400):
    return JsonResponse({'success': False, 'error': message}, status=status)


# =============================================================================
# PLATFORM DASHBOARD
# =============================================================================

class PlatformDashboardView(SuperuserRequiredMixin, TemplateView):
    """
    Main platform dashboard — the operator's command center.
    
    Shows all organizations, properties, data health, and signal freshness.
    """
    template_name = 'platform_data/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.models import Organization, Property
        from pricing.models.analytics import FileImport, Reservation
        from .models import MarketArrivalData, MarketEvent, PlatformFileImport
        
        # Organizations
        orgs = Organization.objects.filter(is_active=True).prefetch_related('properties')
        org_data = []
        for org in orgs:
            props = org.properties.filter(is_active=True)
            org_data.append({
                'org': org,
                'properties': props,
                'property_count': props.count(),
                'total_rooms': sum(p.total_rooms for p in props),
            })
        context['organizations'] = org_data
        context['total_organizations'] = len(org_data)
        context['total_properties'] = Property.objects.filter(is_active=True).count()
        context['total_rooms'] = Property.objects.filter(is_active=True).aggregate(
            total=Sum('total_rooms'))['total'] or 0
        
        # Properties with data status
        properties = Property.objects.filter(is_active=True).select_related('organization')
        prop_status = []
        for prop in properties:
            last_import = FileImport.objects.filter(
                hotel=prop, status__in=['completed', 'completed_with_errors']
            ).order_by('-created_at').first()
            
            reservation_count = Reservation.objects.filter(hotel=prop).count()
            
            prop_status.append({
                'property': prop,
                'org_name': prop.organization.name,
                'reservation_count': reservation_count,
                'last_import': last_import,
                'last_import_date': last_import.created_at if last_import else None,
                'country_code': prop.country_code,
            })
        context['property_status'] = prop_status
        
        # Platform data freshness
        countries = set(p.country_code for p in properties)
        from .services import MarketSignalService
        freshness = {}
        for cc in countries:
            freshness[cc] = MarketSignalService.get_data_freshness(cc)
        context['data_freshness'] = freshness
        
        # Recent platform imports
        context['recent_platform_imports'] = PlatformFileImport.objects.order_by('-created_at')[:10]
        
        # Upcoming events
        context['upcoming_events'] = MarketEvent.objects.filter(
            is_active=True, end_date__gte=date.today()
        ).order_by('start_date')[:10]
        
        # Stats
        context['total_arrival_records'] = MarketArrivalData.objects.count()
        context['total_events'] = MarketEvent.objects.filter(is_active=True).count()
        
        return context


# =============================================================================
# ORGANIZATION MANAGEMENT
# =============================================================================

class PlatformOrganizationsView(SuperuserRequiredMixin, TemplateView):
    """List and manage all organizations."""
    template_name = 'platform_data/organizations.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import Organization
        from pricing.models.analytics import Reservation
        
        orgs = Organization.objects.filter(is_active=True).prefetch_related('properties')
        org_list = []
        for org in orgs:
            props = org.properties.filter(is_active=True)
            total_reservations = Reservation.objects.filter(
                hotel__organization=org
            ).count()
            org_list.append({
                'org': org,
                'properties': props,
                'property_count': props.count(),
                'total_rooms': sum(p.total_rooms for p in props),
                'total_reservations': total_reservations,
            })
        context['organizations'] = org_list
        return context


class PlatformOrgDetailView(SuperuserRequiredMixin, TemplateView):
    """Detail view for a single organization — properties + user management."""
    template_name = 'platform_data/org_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_section'] = 'organizations'
        from pricing.models import Organization, UserOrganizationRole
        from pricing.models.analytics import FileImport, Reservation
        from django.contrib.auth import get_user_model
        User = get_user_model()

        org = get_object_or_404(Organization, pk=self.kwargs['pk'], is_active=True)
        context['org'] = org

        # Properties
        props = org.properties.filter(is_active=True)
        prop_list = []
        for prop in props:
            last_import = FileImport.objects.filter(
                hotel=prop, status__in=['completed', 'completed_with_errors']
            ).order_by('-created_at').first()
            res_count = Reservation.objects.filter(hotel=prop).count()

            prop_list.append({
                'property': prop,
                'reservation_count': res_count,
                'last_import': last_import,
            })
        context['properties'] = prop_list

        # User roles for this org
        context['user_roles'] = UserOrganizationRole.objects.filter(
            organization=org
        ).select_related('user').order_by('-is_active', 'user__username')

        context['role_choices'] = UserOrganizationRole.ROLE_CHOICES

        # Available users (not already assigned to this org)
        assigned_user_ids = UserOrganizationRole.objects.filter(
            organization=org
        ).values_list('user_id', flat=True)
        context['available_users'] = User.objects.filter(
            is_active=True
        ).exclude(
            id__in=assigned_user_ids
        ).order_by('username')

        return context


class PlatformOrgUserAddView(SuperuserRequiredMixin, View):
    """POST: Add a user to an organization with a role."""

    def post(self, request, pk):
        from pricing.models import Organization, UserOrganizationRole
        from django.contrib.auth import get_user_model
        User = get_user_model()

        org = get_object_or_404(Organization, pk=pk, is_active=True)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')

        user_id = data.get('user_id')
        role = data.get('role', 'viewer')

        if not user_id:
            return error_response('User is required')

        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return error_response('User not found')

        valid_roles = [r[0] for r in UserOrganizationRole.ROLE_CHOICES]
        if role not in valid_roles:
            return error_response(f'Invalid role. Must be one of: {", ".join(valid_roles)}')

        obj, created = UserOrganizationRole.objects.update_or_create(
            user=user, organization=org,
            defaults={'role': role, 'is_active': True}
        )

        return success_response({
            'id': obj.id,
            'username': user.username,
            'email': user.email,
            'role': obj.role,
            'is_active': obj.is_active,
            'created': created,
        }, message=f'{"Added" if created else "Updated"} {user.username} as {obj.get_role_display()}')


class PlatformOrgUserUpdateView(SuperuserRequiredMixin, View):
    """POST: Update a user's role in an organization."""

    def post(self, request, pk, role_id):
        from pricing.models import UserOrganizationRole

        role_obj = get_object_or_404(UserOrganizationRole, pk=role_id, organization_id=pk)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')

        new_role = data.get('role')
        is_active = data.get('is_active')

        if new_role is not None:
            valid_roles = [r[0] for r in UserOrganizationRole.ROLE_CHOICES]
            if new_role not in valid_roles:
                return error_response(f'Invalid role')
            role_obj.role = new_role

        if is_active is not None:
            role_obj.is_active = bool(is_active)

        role_obj.save()

        return success_response({
            'id': role_obj.id,
            'role': role_obj.role,
            'is_active': role_obj.is_active,
        }, message=f'Updated {role_obj.user.username}')


class PlatformOrgUserRemoveView(SuperuserRequiredMixin, View):
    """POST: Remove a user from an organization."""

    def post(self, request, pk, role_id):
        from pricing.models import UserOrganizationRole

        role_obj = get_object_or_404(UserOrganizationRole, pk=role_id, organization_id=pk)
        username = role_obj.user.username
        role_obj.delete()

        return success_response(message=f'Removed {username} from organization')


class PlatformUserCreateView(SuperuserRequiredMixin, View):
    """POST: Create a new Django user and optionally assign to an organization."""

    def post(self, request):
        from django.contrib.auth import get_user_model
        from pricing.models import UserOrganizationRole
        User = get_user_model()

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')

        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        org_id = data.get('organization_id')
        role = data.get('role', 'viewer')

        if not username:
            return error_response('Username is required')
        if not password:
            return error_response('Password is required')
        if len(password) < 6:
            return error_response('Password must be at least 6 characters')

        if User.objects.filter(username=username).exists():
            return error_response(f'Username "{username}" already exists')
        if email and User.objects.filter(email=email).exists():
            return error_response(f'Email "{email}" is already in use')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        # Assign to organization if provided
        org_role = None
        if org_id:
            from pricing.models import Organization
            try:
                org = Organization.objects.get(pk=org_id, is_active=True)
                valid_roles = [r[0] for r in UserOrganizationRole.ROLE_CHOICES]
                if role not in valid_roles:
                    role = 'viewer'
                org_role = UserOrganizationRole.objects.create(
                    user=user, organization=org, role=role, is_active=True
                )
            except Organization.DoesNotExist:
                pass

        return success_response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role_id': org_role.id if org_role else None,
        }, message=f'Created user "{username}"' + (f' as {org_role.get_role_display()}' if org_role else ''))


# =============================================================================
# ORGANIZATION CRUD API
# =============================================================================

class PlatformOrgCreateView(SuperuserRequiredMixin, View):
    """POST: Create a new organization."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Organization
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        name = data.get('name', '').strip()
        code = data.get('code', '').strip().lower()
        
        if not name:
            return error_response('Organization name is required')
        if not code:
            from django.utils.text import slugify
            code = slugify(name)
        
        if Organization.objects.filter(code=code).exists():
            return error_response(f'Organization code "{code}" already exists')
        
        org = Organization.objects.create(
            name=name,
            code=code,
            default_currency=data.get('default_currency', 'USD'),
            currency_symbol=data.get('currency_symbol', '$'),
        )
        
        return success_response(
            data={'id': org.id, 'name': org.name, 'code': org.code},
            message=f'Organization "{name}" created'
        )


class PlatformOrgUpdateView(SuperuserRequiredMixin, View):
    """POST: Update an organization."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Organization
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        org = get_object_or_404(Organization, pk=self.kwargs['pk'])
        
        if 'name' in data:
            org.name = data['name'].strip()
        if 'default_currency' in data:
            org.default_currency = data['default_currency']
        if 'currency_symbol' in data:
            org.currency_symbol = data['currency_symbol']
        if 'is_active' in data:
            org.is_active = data['is_active']
        
        org.save()
        return success_response(message=f'Organization "{org.name}" updated')


class PlatformOrgDeleteView(SuperuserRequiredMixin, View):
    """POST: Deactivate an organization."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Organization
        
        org = get_object_or_404(Organization, pk=self.kwargs['pk'])
        org.is_active = False
        org.save()
        
        # Deactivate all properties too
        org.properties.update(is_active=False)
        
        return success_response(message=f'Organization "{org.name}" deactivated')


# =============================================================================
# PROPERTY CRUD API
# =============================================================================

class PlatformPropertyCreateView(SuperuserRequiredMixin, View):
    """POST: Create a new property under an organization."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Organization, Property
        from decimal import Decimal
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        org_id = data.get('organization_id')
        if not org_id:
            return error_response('Organization is required')
        
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        
        name = data.get('name', '').strip()
        code = data.get('code', '').strip().lower()
        
        if not name:
            return error_response('Property name is required')
        if not code:
            from django.utils.text import slugify
            code = slugify(name)
        
        if Property.objects.filter(organization=org, code=code).exists():
            return error_response(f'Property code "{code}" already exists in {org.name}')
        
        prop = Property.objects.create(
            organization=org,
            name=name,
            code=code,
            location=data.get('location', ''),
            reference_base_rate=Decimal(str(data.get('reference_base_rate', '100.00'))),
            currency_symbol=data.get('currency_symbol', '$'),
            total_rooms=int(data.get('total_rooms', 0)),
            service_charge_percent=Decimal(str(data.get('service_charge_percent', '10.00'))),
            tax_percent=Decimal(str(data.get('tax_percent', '16.00'))),
            tax_on_service_charge=data.get('tax_on_service_charge', True),
            country_code=data.get('country_code', 'MV'),
        )
        
        return success_response(
            data={'id': prop.id, 'name': prop.name, 'code': prop.code},
            message=f'Property "{name}" created under {org.name}'
        )


class PlatformPropertyUpdateView(SuperuserRequiredMixin, View):
    """POST: Update a property."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Property
        from decimal import Decimal
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        prop = get_object_or_404(Property, pk=self.kwargs['pk'])
        
        if 'name' in data:
            prop.name = data['name'].strip()
        if 'location' in data:
            prop.location = data['location']
        if 'reference_base_rate' in data:
            prop.reference_base_rate = Decimal(str(data['reference_base_rate']))
        if 'currency_symbol' in data:
            prop.currency_symbol = data['currency_symbol']
        if 'service_charge_percent' in data:
            prop.service_charge_percent = Decimal(str(data['service_charge_percent']))
        if 'tax_percent' in data:
            prop.tax_percent = Decimal(str(data['tax_percent']))
        if 'tax_on_service_charge' in data:
            prop.tax_on_service_charge = data['tax_on_service_charge']
        if 'country_code' in data:
            prop.country_code = data['country_code']
        if 'is_active' in data:
            prop.is_active = data['is_active']
        
        prop.save()
        return success_response(message=f'Property "{prop.name}" updated')


class PlatformPropertyDeleteView(SuperuserRequiredMixin, View):
    """POST: Deactivate a property."""
    
    def post(self, request, *args, **kwargs):
        from pricing.models import Property
        
        prop = get_object_or_404(Property, pk=self.kwargs['pk'])
        prop.is_active = False
        prop.save()
        
        return success_response(message=f'Property "{prop.name}" deactivated')


class PlatformPropertyListAPIView(SuperuserRequiredMixin, View):
    """GET: List all properties (optionally filtered by org)."""
    
    def get(self, request, *args, **kwargs):
        from pricing.models import Property
        
        qs = Property.objects.filter(is_active=True).select_related('organization')
        
        org_id = request.GET.get('organization_id')
        if org_id:
            qs = qs.filter(organization_id=org_id)
        
        data = [{
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'organization_id': p.organization_id,
            'organization_name': p.organization.name,
            'location': p.location,
            'total_rooms': p.total_rooms,
            'reference_base_rate': float(p.reference_base_rate),
            'currency_symbol': p.currency_symbol,
            'service_charge_percent': float(p.service_charge_percent),
            'tax_percent': float(p.tax_percent),
            'country_code': p.country_code,
        } for p in qs]
        
        return success_response(data={'properties': data})


# =============================================================================
# SIGNAL MANAGEMENT (Upload & Browse)
# =============================================================================

class PlatformSignalsView(SuperuserRequiredMixin, TemplateView):
    """Upload and manage market intelligence data."""
    template_name = 'platform_data/signals.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import MarketArrivalData, MarketEvent, PlatformFileImport, PlatformImportTemplate
        
        # Recent imports
        context['recent_imports'] = PlatformFileImport.objects.order_by('-created_at')[:20]
        
        # Arrival data summary
        latest_period = MarketArrivalData.objects.order_by('-report_period').first()
        context['latest_arrival_period'] = latest_period.report_period if latest_period else None
        context['total_arrival_records'] = MarketArrivalData.objects.count()
        
        # Distinct periods available
        context['arrival_periods'] = MarketArrivalData.objects.values_list(
            'report_period', flat=True
        ).distinct().order_by('-report_period')[:12]
        
        # Events
        context['upcoming_events'] = MarketEvent.objects.filter(
            is_active=True, end_date__gte=date.today()
        ).order_by('start_date')[:20]
        context['total_events'] = MarketEvent.objects.filter(is_active=True).count()
        
        # Templates
        context['templates'] = PlatformImportTemplate.objects.filter(is_active=True)
        
        return context


# =============================================================================
# SIGNAL API ENDPOINTS
# =============================================================================

class PlatformSignalUploadView(SuperuserRequiredMixin, View):
    """POST: Upload a file for platform data import."""
    
    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get('file')
        import_type = request.POST.get('import_type', 'arrival_report')
        
        if not uploaded_file:
            return error_response('No file uploaded')
        
        suffix = os.path.splitext(uploaded_file.name)[1].lower()
        
        # Handle PDF (MoT reports)
        if suffix == '.pdf':
            return self._handle_pdf(request, uploaded_file, import_type)
        
        # Handle CSV/Excel (standard import flow)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        
        try:
            from .services import PlatformImportService
            svc = PlatformImportService()
            result = svc.read_headers(tmp_path)
            
            if 'error' in result:
                return error_response(result['error'])
            
            request.session['platform_import_tmp_path'] = tmp_path
            request.session['platform_import_filename'] = uploaded_file.name
            
            # Auto-detect template
            template_match = svc.detect_template(result['headers'], import_type)
            fields = svc.get_field_definitions(import_type)
            
            return success_response(data={
                'filename': uploaded_file.name,
                'file_type': 'csv',
                'headers': result['headers'],
                'preview': result['preview'],
                'row_count': result['row_count'],
                'template_match': template_match,
                'field_definitions': fields,
            })
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return error_response(str(e))
    
    def _handle_pdf(self, request, uploaded_file, import_type):
        """Handle PDF upload — auto-parse MoT report and import."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        
        try:
            from .mot_parser import MoTReportParser, import_mot_report
            
            # First just parse to show preview
            parser = MoTReportParser()
            parsed = parser.parse_pdf(tmp_path)
            
            if 'error' in parsed:
                os.unlink(tmp_path)
                return error_response(parsed['error'])
            
            # Store path for execution
            request.session['platform_import_tmp_path'] = tmp_path
            request.session['platform_import_filename'] = uploaded_file.name
            
            # Build preview
            top_countries = sorted(
                parsed['countries'], key=lambda x: -(x['arrivals'] or 0)
            )[:15]
            
            preview_rows = []
            for c in top_countries:
                preview_rows.append([
                    c['country'],
                    str(c['arrivals'] or ''),
                    str(c.get('market_share', '') or ''),
                    str(c.get('pct_change', '') or ''),
                    str(c.get('ranking', '') or ''),
                ])
            
            return success_response(data={
                'filename': uploaded_file.name,
                'file_type': 'pdf',
                'report_type': parsed['report_type'],
                'report_period': parsed['report_period'].isoformat(),
                'report_source': parsed['source'],
                'total_arrivals': parsed['total_arrivals'],
                'country_count': parsed['country_count'],
                'key_indicators': parsed.get('key_indicators', {}),
                'headers': ['Country', 'Arrivals', 'Market Share %', 'YoY Change %', 'Ranking'],
                'preview': preview_rows,
                'row_count': parsed['country_count'],
                'auto_import': True,  # Signal to UI: no column mapping needed
            })
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return error_response(str(e))


class PlatformSignalExecuteView(SuperuserRequiredMixin, View):
    """POST: Execute platform data import with column mapping or PDF auto-import."""
    
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        tmp_path = request.session.get('platform_import_tmp_path')
        if not tmp_path or not os.path.exists(tmp_path):
            return error_response('No file uploaded. Please upload a file first.')
        
        country_code = data.get('country_code', 'MV')
        
        # PDF auto-import (MoT reports)
        if data.get('auto_import') or tmp_path.endswith('.pdf'):
            try:
                from .mot_parser import import_mot_report
                result = import_mot_report(
                    file_path=tmp_path,
                    country_code=country_code,
                    user=request.user,
                )
                
                # Cleanup
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                request.session.pop('platform_import_tmp_path', None)
                request.session.pop('platform_import_filename', None)
                
                if result.get('success'):
                    return success_response(
                        data=result,
                        message=f"PDF import complete: {result['rows_created']} created, {result['rows_updated']} updated from {result['countries_parsed']} countries"
                    )
                else:
                    return error_response(result.get('error', 'PDF import failed'))
            except Exception as e:
                return error_response(str(e))
        
        # Standard CSV/Excel import
        column_map = data.get('column_map', {})
        import_type = data.get('import_type', 'arrival_report')
        template_id = data.get('template_id')
        report_period_str = data.get('report_period')
        
        # Parse report period if provided
        report_period = None
        if report_period_str:
            try:
                from datetime import datetime
                report_period = datetime.strptime(report_period_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        # Load template
        template = None
        if template_id:
            from .models import PlatformImportTemplate
            try:
                template = PlatformImportTemplate.objects.get(pk=template_id, is_active=True)
            except PlatformImportTemplate.DoesNotExist:
                pass
        
        try:
            from .services import PlatformImportService
            svc = PlatformImportService()
            result = svc.execute_import(
                file_path=tmp_path,
                column_map=column_map,
                import_type=import_type,
                country_code=country_code,
                report_period=report_period,
                template=template,
                user=request.user,
            )
            
            # Cleanup
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            request.session.pop('platform_import_tmp_path', None)
            request.session.pop('platform_import_filename', None)
            
            if result.get('success'):
                return success_response(
                    data=result,
                    message=f"Import complete: {result['rows_created']} created, {result['rows_updated']} updated"
                )
            else:
                return error_response(result.get('error', 'Import failed'))
        except Exception as e:
            return error_response(str(e))


class PlatformTemplateSaveView(SuperuserRequiredMixin, View):
    """POST: Save a platform import template."""
    
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        from .models import PlatformImportTemplate
        
        name = data.get('name', '').strip()
        if not name:
            return error_response('Template name is required')
        
        template = PlatformImportTemplate.objects.create(
            name=name,
            import_type=data.get('import_type', 'arrival_report'),
            column_map=data.get('column_map', {}),
            source_headers=data.get('source_headers', []),
        )
        
        return success_response(
            data={'id': template.id, 'name': template.name},
            message=f'Template "{name}" saved'
        )


class PlatformTemplateListView(SuperuserRequiredMixin, View):
    """GET: List platform import templates."""
    
    def get(self, request, *args, **kwargs):
        from .models import PlatformImportTemplate
        
        templates = PlatformImportTemplate.objects.filter(is_active=True)
        data = [{
            'id': t.id, 'name': t.name, 'import_type': t.import_type,
            'column_map': t.column_map, 'use_count': t.use_count,
            'last_used_at': t.last_used_at.isoformat() if t.last_used_at else None,
        } for t in templates]
        
        return success_response(data={'templates': data})


class PlatformTemplateDeleteView(SuperuserRequiredMixin, View):
    """POST: Delete a platform import template."""
    
    def post(self, request, *args, **kwargs):
        from .models import PlatformImportTemplate
        pk = self.kwargs.get('pk')
        template = get_object_or_404(PlatformImportTemplate, pk=pk, is_active=True)
        template.is_active = False
        template.save()
        return success_response(message=f'Template "{template.name}" deleted')


# =============================================================================
# ARRIVAL DATA API
# =============================================================================

class PlatformArrivalDataView(SuperuserRequiredMixin, View):
    """GET: Browse arrival data with filters."""
    
    def get(self, request, *args, **kwargs):
        from .models import MarketArrivalData
        
        country_code = request.GET.get('country', 'MV')
        period_str = request.GET.get('period')
        
        qs = MarketArrivalData.objects.filter(country_code=country_code)
        
        if period_str:
            try:
                from datetime import datetime
                period = datetime.strptime(period_str, '%Y-%m-%d').date()
                qs = qs.filter(report_period=period)
            except ValueError:
                pass
        
        data = list(qs.order_by('-report_period', '-arrivals').values(
            'id', 'country_code', 'report_period', 'origin_country',
            'arrivals', 'market_share_pct', 'yoy_change_pct', 'source_report'
        )[:200])
        
        # Convert dates and decimals to serializable
        for row in data:
            row['report_period'] = row['report_period'].isoformat()
            if row['market_share_pct']:
                row['market_share_pct'] = float(row['market_share_pct'])
            if row['yoy_change_pct']:
                row['yoy_change_pct'] = float(row['yoy_change_pct'])
        
        return success_response(data={'records': data, 'count': len(data)})


class PlatformArrivalMonthlySummaryView(SuperuserRequiredMixin, View):
    """GET: Monthly arrival totals for bar chart."""

    def get(self, request, *args, **kwargs):
        from .models import MarketArrivalData

        country_code = request.GET.get('country', 'MV')

        qs = MarketArrivalData.objects.filter(
            country_code=country_code
        ).values('report_period').annotate(
            total_arrivals=Sum('arrivals')
        ).order_by('report_period')

        data = [{
            'period': row['report_period'].isoformat(),
            'label': row['report_period'].strftime('%b %Y'),
            'total_arrivals': row['total_arrivals'],
        } for row in qs]

        return success_response(data={'monthly': data})


class PlatformArrivalCountryDetailView(SuperuserRequiredMixin, View):
    """GET: Per-country arrival time series + list of unique origin countries."""

    def get(self, request, *args, **kwargs):
        from .models import MarketArrivalData

        country_code = request.GET.get('country', 'MV')
        origin = request.GET.get('origin_country', '')

        # Always return the list of unique origin countries (for the dropdown)
        origins = list(
            MarketArrivalData.objects.filter(country_code=country_code)
            .values_list('origin_country', flat=True)
            .distinct()
            .order_by('origin_country')
        )

        # If a specific origin country is requested, return its time series
        series = []
        if origin:
            qs = MarketArrivalData.objects.filter(
                country_code=country_code, origin_country=origin
            ).order_by('report_period')
            series = [{
                'period': row.report_period.isoformat(),
                'label': row.report_period.strftime('%b %Y'),
                'arrivals': row.arrivals,
                'market_share_pct': float(row.market_share_pct) if row.market_share_pct else None,
                'yoy_change_pct': float(row.yoy_change_pct) if row.yoy_change_pct else None,
            } for row in qs]

        return success_response(data={
            'origins': origins,
            'origin_country': origin,
            'series': series,
        })


class PlatformArrivalDeleteView(SuperuserRequiredMixin, View):
    """POST: Delete arrival records — single record or entire period."""

    def post(self, request, *args, **kwargs):
        import json
        from .models import MarketArrivalData

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return error_response('Invalid JSON')

        record_id = body.get('id')
        period = body.get('period')
        country_code = body.get('country_code', 'MV')

        if record_id:
            deleted, _ = MarketArrivalData.objects.filter(id=record_id).delete()
            return success_response(
                data={'deleted': deleted},
                message=f'{deleted} record deleted'
            )
        elif period:
            from datetime import datetime
            try:
                period_date = datetime.strptime(period, '%Y-%m-%d').date()
            except ValueError:
                return error_response('Invalid period format. Use YYYY-MM-DD.')
            deleted, _ = MarketArrivalData.objects.filter(
                country_code=country_code, report_period=period_date
            ).delete()
            return success_response(
                data={'deleted': deleted},
                message=f'{deleted} records deleted for {period_date.strftime("%b %Y")}'
            )
        else:
            return error_response('Provide "id" or "period" to delete.')


# =============================================================================
# EVENT MANAGEMENT API
# =============================================================================

class PlatformEventListView(SuperuserRequiredMixin, View):
    """GET: List market events."""
    
    def get(self, request, *args, **kwargs):
        from .models import MarketEvent
        
        events = MarketEvent.objects.filter(is_active=True).order_by('start_date')
        data = [{
            'id': e.id, 'name': e.name, 'country_code': e.country_code,
            'event_type': e.event_type, 'start_date': e.start_date.isoformat(),
            'end_date': e.end_date.isoformat(), 'impact_level': e.impact_level,
            'demand_uplift_pct': float(e.demand_uplift_pct),
            'source_markets': e.source_markets, 'recurring': e.recurring,
        } for e in events]
        
        return success_response(data={'events': data})


class PlatformEventCreateView(SuperuserRequiredMixin, View):
    """POST: Create a market event."""
    
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        from .models import MarketEvent
        from datetime import datetime
        
        name = data.get('name', '').strip()
        if not name:
            return error_response('Event name is required')
        
        try:
            start = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            return error_response('Valid start_date and end_date required (YYYY-MM-DD)')
        
        event = MarketEvent.objects.create(
            country_code=data.get('country_code', 'MV'),
            name=name,
            event_type=data.get('event_type', 'other'),
            start_date=start,
            end_date=end,
            impact_level=data.get('impact_level', 'medium'),
            demand_uplift_pct=Decimal(str(data.get('demand_uplift_pct', 0))),
            source_markets=data.get('source_markets', ''),
            recurring=data.get('recurring', False),
            notes=data.get('notes', ''),
        )
        
        return success_response(
            data={'id': event.id},
            message=f'Event "{name}" created'
        )


class PlatformEventUpdateView(SuperuserRequiredMixin, View):
    """POST: Update a market event."""
    
    def post(self, request, *args, **kwargs):
        from .models import MarketEvent
        from datetime import datetime
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        event = get_object_or_404(MarketEvent, pk=self.kwargs['pk'])
        
        if 'name' in data:
            event.name = data['name'].strip()
        if 'start_date' in data:
            event.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        if 'end_date' in data:
            event.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        if 'event_type' in data:
            event.event_type = data['event_type']
        if 'impact_level' in data:
            event.impact_level = data['impact_level']
        if 'demand_uplift_pct' in data:
            event.demand_uplift_pct = Decimal(str(data['demand_uplift_pct']))
        if 'source_markets' in data:
            event.source_markets = data['source_markets']
        if 'recurring' in data:
            event.recurring = data['recurring']
        if 'notes' in data:
            event.notes = data['notes']
        if 'country_code' in data:
            event.country_code = data['country_code']
        
        event.save()
        return success_response(message=f'Event "{event.name}" updated')


class PlatformEventDeleteView(SuperuserRequiredMixin, View):
    """POST: Soft-delete a market event."""
    
    def post(self, request, *args, **kwargs):
        from .models import MarketEvent
        event = get_object_or_404(MarketEvent, pk=self.kwargs['pk'])
        event.is_active = False
        event.save()
        return success_response(message=f'Event "{event.name}" deleted')
