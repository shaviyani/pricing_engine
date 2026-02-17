"""
Version management views and Dynamic Pricing management views.
"""

import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import date

from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.db import transaction

from pricing.models import (
    Property, PricingMatrixVersion, Season, RoomType, Channel, RatePlan, RateModifier,
    BookingWindowConfig, BookingWindowBand, DynamicPricingRule, DynamicPricingBand,
    DynamicPricingMultiplier, EventUplift,
)
from pricing.services.version_service import PricingVersionService, DynamicPricingService
from pricing.views.mixins import PropertyMixin, PricingManagementMixin

logger = logging.getLogger(__name__)


# =============================================================================
# VERSION MANAGEMENT VIEWS
# =============================================================================

class VersionListView(PricingManagementMixin, View):
    """GET: List all versions with summaries."""
    
    def get(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        svc = PricingVersionService(hotel)
        versions = PricingMatrixVersion.objects.filter(hotel=hotel).order_by('-version_number')
        
        data = []
        for v in versions:
            summary = svc.get_version_summary(v)
            data.append({
                'id': v.id,
                'version_number': v.version_number,
                'name': v.name,
                'status': v.status,
                'notes': v.notes,
                'created_by': v.created_by,
                'published_at': v.published_at.isoformat() if v.published_at else None,
                'created_at': v.created_at.isoformat(),
                'seasons': summary['seasons'],
                'room_types': summary['room_types'],
                'rate_plans': summary['rate_plans'],
                'channels': summary['channels'],
                'modifiers': summary['modifiers'],
                'dynamic_rules': summary['dynamic_rules'],
            })
        
        return JsonResponse({'success': True, 'data': data})


class VersionCreateDraftView(PricingManagementMixin, View):
    """POST: Create a new draft version from published."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            body = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            body = {}
        
        name = body.get('name', f'Draft {date.today().strftime("%b %Y")}')
        notes = body.get('notes', '')
        created_by = body.get('created_by', 'admin')
        
        try:
            svc = PricingVersionService(hotel)
            draft = svc.create_draft(name, notes, created_by)
            return self.success_response(
                data={'id': draft.id, 'version_number': draft.version_number, 'name': draft.name},
                message=f'Draft v{draft.version_number} created'
            )
        except ValueError as e:
            return self.error_response(str(e))


class VersionPublishView(PricingManagementMixin, View):
    """POST: Publish the current draft."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            svc = PricingVersionService(hotel)
            published = svc.publish_draft()
            return self.success_response(
                data={'id': published.id, 'version_number': published.version_number},
                message=f'v{published.version_number} published'
            )
        except ValueError as e:
            return self.error_response(str(e))


class VersionDiscardView(PricingManagementMixin, View):
    """POST: Discard the current draft."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            svc = PricingVersionService(hotel)
            svc.discard_draft()
            return self.success_response(message='Draft discarded')
        except ValueError as e:
            return self.error_response(str(e))


class VersionRevertView(PricingManagementMixin, View):
    """POST: Create a new draft from a historical version."""
    
    def post(self, request, org_code, prop_code, version_number):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            body = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            body = {}
        
        try:
            svc = PricingVersionService(hotel)
            draft = svc.revert_to_version(version_number, body.get('created_by', 'admin'))
            return self.success_response(
                data={'id': draft.id, 'version_number': draft.version_number, 'name': draft.name},
                message=f'Reverted to v{version_number} as draft v{draft.version_number}'
            )
        except ValueError as e:
            return self.error_response(str(e))


class VersionInitializeView(PricingManagementMixin, View):
    """POST: Create initial v1 from unversioned data."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        svc = PricingVersionService(hotel)
        version = svc.create_initial_version()
        return self.success_response(
            data={'id': version.id, 'version_number': version.version_number},
            message=f'v{version.version_number} initialized'
        )


# =============================================================================
# DYNAMIC PRICING VIEWS
# =============================================================================

class DynamicPricingRuleListView(PricingManagementMixin, View):
    """GET: List all dynamic pricing rules for published version."""
    
    def get(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        version = PricingMatrixVersion.get_published(hotel)
        if not version:
            return JsonResponse({'success': True, 'data': []})
        
        rules = DynamicPricingRule.objects.filter(
            hotel=hotel, version=version
        ).select_related('season', 'booking_window_config')
        
        data = []
        for rule in rules:
            bands = rule.bands.all().order_by('-min_occupancy')
            window_bands = list(rule.booking_window_config.bands.order_by('sort_order'))
            
            bands_data = []
            for band in bands:
                multipliers = {}
                for mult in band.multipliers.select_related('window_band').all():
                    multipliers[mult.window_band.id] = str(mult.multiplier)
                
                bands_data.append({
                    'id': band.id,
                    'min_occupancy': str(band.min_occupancy),
                    'max_occupancy': str(band.max_occupancy),
                    'label': str(band),
                    'rationale': band.rationale,
                    'multipliers': multipliers,
                })
            
            window_data = [{'id': wb.id, 'label': wb.label, 'min_days': wb.min_days,
                           'max_days': wb.max_days} for wb in window_bands]
            
            data.append({
                'id': rule.id,
                'season_id': rule.season.id,
                'season_name': rule.season.name,
                'season_type': rule.season.season_type,
                'is_active': rule.is_active,
                'window_bands': window_data,
                'bands': bands_data,
            })
        
        return JsonResponse({'success': True, 'data': data})


class DynamicPricingMultiplierUpdateView(PricingManagementMixin, View):
    """POST: Update a single multiplier cell value."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        band_id = body.get('band_id')
        window_band_id = body.get('window_band_id')
        multiplier = body.get('multiplier')
        
        if not all([band_id, window_band_id, multiplier is not None]):
            return self.error_response('band_id, window_band_id, and multiplier required')
        
        try:
            mult_val = Decimal(str(multiplier))
            if mult_val < Decimal('0.50') or mult_val > Decimal('2.00'):
                return self.error_response('Multiplier must be between 0.50 and 2.00')
        except (ValueError, InvalidOperation):
            return self.error_response('Invalid multiplier value')
        
        mult_obj, created = DynamicPricingMultiplier.objects.update_or_create(
            band_id=band_id, window_band_id=window_band_id,
            defaults={'multiplier': mult_val}
        )
        
        return self.success_response(
            data={'multiplier': str(mult_obj.multiplier)},
            message='Updated'
        )


class DynamicPricingSeedView(PricingManagementMixin, View):
    """POST: Seed default dynamic pricing rules from spreadsheet model."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        version = PricingMatrixVersion.get_published(hotel)
        if not version:
            return self.error_response('No published version')
        
        svc = DynamicPricingService(hotel)
        svc.seed_default_rules(version)
        
        rule_count = DynamicPricingRule.objects.filter(hotel=hotel, version=version).count()
        return self.success_response(
            message=f'Seeded {rule_count} dynamic pricing rules'
        )


class DynamicPricingPreviewView(PricingManagementMixin, View):
    """GET: Preview dynamic multiplier for a specific date."""
    
    def get(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        target_date_str = request.GET.get('date')
        if not target_date_str:
            target_date = date.today()
        else:
            try:
                target_date = date.fromisoformat(target_date_str)
            except ValueError:
                return self.error_response('Invalid date format (use YYYY-MM-DD)')
        
        svc = DynamicPricingService(hotel)
        result = svc.get_multiplier(target_date)
        
        # Convert Decimals to strings for JSON
        json_result = {}
        for k, v in result.items():
            if isinstance(v, Decimal):
                json_result[k] = str(v)
            else:
                json_result[k] = v
        
        return JsonResponse({'success': True, 'data': json_result})


# =============================================================================
# EVENT UPLIFT VIEWS
# =============================================================================

class EventUpliftListView(PricingManagementMixin, View):
    """GET: List all event uplifts."""
    
    def get(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        events = EventUplift.objects.filter(hotel=hotel)
        data = [{
            'id': e.id,
            'name': e.name,
            'uplift_percent': str(e.uplift_percent),
            'start_date': e.start_date.isoformat(),
            'end_date': e.end_date.isoformat(),
            'is_active': e.is_active,
            'notes': e.notes,
        } for e in events]
        
        return JsonResponse({'success': True, 'data': data})


class EventUpliftCreateView(PricingManagementMixin, View):
    """POST: Create an event uplift."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        try:
            event = EventUplift.objects.create(
                hotel=hotel,
                name=body.get('name', ''),
                uplift_percent=Decimal(str(body.get('uplift_percent', 0))),
                start_date=body.get('start_date'),
                end_date=body.get('end_date'),
                is_active=body.get('is_active', True),
                notes=body.get('notes', ''),
            )
            return self.success_response(data={'id': event.id}, message='Event created')
        except Exception as e:
            return self.error_response(str(e))


class EventUpliftUpdateView(PricingManagementMixin, View):
    """POST: Update an event uplift."""
    
    def post(self, request, org_code, prop_code, pk):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        event = get_object_or_404(EventUplift, pk=pk, hotel=hotel)
        
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return self.error_response('Invalid JSON')
        
        if 'name' in body: event.name = body['name']
        if 'uplift_percent' in body: event.uplift_percent = Decimal(str(body['uplift_percent']))
        if 'start_date' in body: event.start_date = body['start_date']
        if 'end_date' in body: event.end_date = body['end_date']
        if 'is_active' in body: event.is_active = body['is_active']
        if 'notes' in body: event.notes = body['notes']
        event.save()
        
        return self.success_response(message='Event updated')


class EventUpliftDeleteView(PricingManagementMixin, View):
    """POST: Delete an event uplift."""
    
    def post(self, request, org_code, prop_code, pk):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        event = get_object_or_404(EventUplift, pk=pk, hotel=hotel)
        event.delete()
        return self.success_response(message='Event deleted')


# =============================================================================
# DYNAMIC PRICING SUGGESTION VIEWS
# =============================================================================

class DPSuggestionAnalyzeView(PricingManagementMixin, View):
    """POST: Run analysis and generate new suggestions."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        from pricing.services.version_service import DynamicPricingOptimizer
        
        optimizer = DynamicPricingOptimizer(hotel)
        suggestions = optimizer.generate_suggestions()
        
        return self.success_response(
            data={'count': len(suggestions)},
            message=f'Analysis complete: {len(suggestions)} suggestion{"s" if len(suggestions) != 1 else ""} generated'
        )


class DPSuggestionListView(PricingManagementMixin, View):
    """GET: List suggestions. ?status=pending (default) or all."""
    
    def get(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        from pricing.models import DynamicPricingSuggestion
        
        status = request.GET.get('status', 'pending')
        qs = DynamicPricingSuggestion.objects.filter(hotel=hotel)
        if status != 'all':
            qs = qs.filter(status=status)
        
        data = []
        for s in qs[:50]:
            data.append({
                'id': s.id,
                'season_type': s.season_type,
                'occupancy_band_label': s.occupancy_band_label,
                'window_band_label': s.window_band_label,
                'current_multiplier': str(s.current_multiplier),
                'suggested_multiplier': str(s.suggested_multiplier),
                'direction': s.direction,
                'change_display': s.get_change_display(),
                'sample_size': s.sample_size,
                'confidence': s.confidence,
                'actual_adr': str(s.actual_adr) if s.actual_adr else None,
                'actual_occupancy_pct': str(s.actual_occupancy_pct) if s.actual_occupancy_pct else None,
                'actual_revpar': str(s.actual_revpar) if s.actual_revpar else None,
                'revpar_improvement_pct': str(s.revpar_improvement_pct) if s.revpar_improvement_pct else None,
                'reasoning': s.reasoning,
                'status': s.status,
                'generated_at': s.generated_at.isoformat(),
                'analysis_period_start': s.analysis_period_start.isoformat() if s.analysis_period_start else None,
                'analysis_period_end': s.analysis_period_end.isoformat() if s.analysis_period_end else None,
            })
        
        # Counts
        pending_count = DynamicPricingSuggestion.objects.filter(hotel=hotel, status='pending').count()
        
        return JsonResponse({
            'success': True,
            'data': data,
            'pending_count': pending_count,
        })


class DPSuggestionAcceptView(PricingManagementMixin, View):
    """POST: Accept a suggestion — applies the multiplier change."""
    
    def post(self, request, org_code, prop_code, pk):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        from pricing.services.version_service import DynamicPricingOptimizer
        
        try:
            suggestion = DynamicPricingOptimizer.apply_suggestion(pk)
            return self.success_response(
                message=f'Applied: {suggestion.season_type} {suggestion.occupancy_band_label} '
                        f'{suggestion.window_band_label} → x{suggestion.suggested_multiplier}'
            )
        except Exception as e:
            return self.error_response(str(e))


class DPSuggestionRejectView(PricingManagementMixin, View):
    """POST: Reject a suggestion."""
    
    def post(self, request, org_code, prop_code, pk):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        from pricing.services.version_service import DynamicPricingOptimizer
        
        try:
            suggestion = DynamicPricingOptimizer.reject_suggestion(pk)
            return self.success_response(message='Suggestion rejected')
        except Exception as e:
            return self.error_response(str(e))


class DPSuggestionAcceptAllView(PricingManagementMixin, View):
    """POST: Accept all pending suggestions."""
    
    def post(self, request, org_code, prop_code):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response('Property not found', 404)
        
        from pricing.models import DynamicPricingSuggestion
        from pricing.services.version_service import DynamicPricingOptimizer
        
        pending = DynamicPricingSuggestion.objects.filter(hotel=hotel, status='pending')
        count = 0
        for s in pending:
            try:
                DynamicPricingOptimizer.apply_suggestion(s.id)
                count += 1
            except Exception:
                pass
        
        return self.success_response(message=f'Applied {count} suggestions')
