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
                'country_code': getattr(prop, 'country_code', 'MV'),
            })
        context['property_status'] = prop_status
        
        # Platform data freshness
        countries = set(getattr(p, 'country_code', 'MV') for p in properties)
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
    """Detail view for a single organization and its properties."""
    template_name = 'platform_data/org_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from pricing.models import Organization
        from pricing.models.analytics import FileImport, Reservation
        
        org = get_object_or_404(Organization, pk=self.kwargs['pk'], is_active=True)
        context['org'] = org
        
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
        return context


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
            'country_code': getattr(p, 'country_code', 'MV'),
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
        
        suffix = os.path.splitext(uploaded_file.name)[1]
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
                'headers': result['headers'],
                'preview': result['preview'],
                'row_count': result['row_count'],
                'file_type': result['file_type'],
                'template_match': template_match,
                'field_definitions': fields,
            })
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return error_response(str(e))


class PlatformSignalExecuteView(SuperuserRequiredMixin, View):
    """POST: Execute platform data import with column mapping."""
    
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return error_response('Invalid JSON')
        
        column_map = data.get('column_map', {})
        import_type = data.get('import_type', 'arrival_report')
        country_code = data.get('country_code', 'MV')
        template_id = data.get('template_id')
        report_period_str = data.get('report_period')
        
        tmp_path = request.session.get('platform_import_tmp_path')
        if not tmp_path or not os.path.exists(tmp_path):
            return error_response('No file uploaded. Please upload a file first.')
        
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
