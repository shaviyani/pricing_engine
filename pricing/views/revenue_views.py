"""
Revenue management views: Budget tracking, Group allotments, Displacement analysis.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.db import transaction

from pricing.models import (
    MonthlyBudget, GroupAllotment, MarketSegment, LengthOfStayTier,
    RoomType, RatePlan,
)

from .admin_views import ManageBaseMixin

logger = logging.getLogger(__name__)


# =============================================================================
# BUDGET MANAGEMENT
# =============================================================================

class ManageBudgetView(ManageBaseMixin, TemplateView):
    """Monthly budget management and tracking."""
    template_name = 'pricing/manage/budget.html'
    active_section = 'budget'
    nav_active_override = 'pricing'
    nav_sub_override = 'budget'
    required_roles = ['admin', 'manager']  # PricingAccess

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hotel = context.get('hotel')
        if not hotel:
            return context

        from pricing.services import BudgetService

        today = date.today()
        year = int(self.request.GET.get('year', today.year))
        context['selected_year'] = year
        context['years'] = list(range(today.year - 1, today.year + 2))

        svc = BudgetService(hotel)
        context['months'] = svc.get_ytd_summary(year)

        # Annual totals
        budgets = MonthlyBudget.objects.filter(hotel=hotel, year=year)
        context['annual_revenue_target'] = float(
            budgets.aggregate(t=sum_field('revenue_target'))['t'] or 0
        )
        context['budget_count'] = budgets.count()

        return context


class BudgetSaveView(ManageBaseMixin, View):
    """API endpoint to save/update a monthly budget."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response("Property not found")

        try:
            data = json.loads(request.body)
            year = int(data['year'])
            month = int(data['month'])

            budget, _ = MonthlyBudget.objects.update_or_create(
                hotel=hotel, year=year, month=month,
                defaults={
                    'revenue_target': Decimal(str(data.get('revenue_target', 0))),
                    'occupancy_target': Decimal(str(data.get('occupancy_target', 70))),
                    'adr_target': Decimal(str(data.get('adr_target', 0))),
                    'revpar_target': Decimal(str(data.get('revpar_target', 0))),
                    'notes': data.get('notes', ''),
                }
            )
            return self.success_response(message=f"Budget for {budget} saved.")
        except Exception as e:
            return self.error_response(str(e))


# =============================================================================
# GROUP ALLOTMENT MANAGEMENT
# =============================================================================

class ManageGroupsView(ManageBaseMixin, TemplateView):
    """Group allotment management page."""
    template_name = 'pricing/manage/groups.html'
    active_section = 'groups'
    nav_active_override = 'distribution'
    nav_sub_override = 'allotments'
    required_roles = ['admin', 'manager', 'sales']  # DistributionAccess

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hotel = context.get('hotel')
        if not hotel:
            return context

        from pricing.services import AllotmentService, DisplacementService

        allotment_svc = AllotmentService(hotel)

        # Active and upcoming allotments
        today = date.today()
        context['active_allotments'] = GroupAllotment.objects.filter(
            hotel=hotel,
            departure_date__gt=today,
            status__in=['tentative', 'confirmed'],
        ).order_by('arrival_date')

        context['past_allotments'] = GroupAllotment.objects.filter(
            hotel=hotel,
            departure_date__lte=today,
        ).order_by('-arrival_date')[:20]

        # Expiring soon
        context['expiring_allotments'] = allotment_svc.check_expiring_allotments(days_ahead=14)

        # Displacement summary
        displacement_svc = DisplacementService(hotel)
        context['displacement'] = displacement_svc.analyze_all_active()

        # Segments for form dropdown
        context['segments'] = MarketSegment.objects.filter(hotel=hotel, is_active=True)

        # Room types and rate plans for displacement form
        from pricing.models import PricingMatrixVersion
        active_version = PricingMatrixVersion.get_published(hotel)
        version_filter = {'hotel': hotel}
        if active_version:
            version_filter['version'] = active_version
        context['room_types'] = RoomType.objects.filter(**version_filter).order_by('sort_order')
        context['rate_plans'] = RatePlan.objects.filter(**version_filter).order_by('sort_order')

        return context


class GroupAllotmentCreateView(ManageBaseMixin, View):
    """API endpoint to create a group allotment."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response("Property not found")

        try:
            data = json.loads(request.body)
            allotment = GroupAllotment.objects.create(
                hotel=hotel,
                group_name=data['group_name'],
                group_code=data.get('group_code', ''),
                contact_name=data.get('contact_name', ''),
                contact_email=data.get('contact_email', ''),
                arrival_date=data['arrival_date'],
                departure_date=data['departure_date'],
                rooms_blocked=int(data['rooms_blocked']),
                agreed_rate=Decimal(str(data['agreed_rate'])),
                release_date=data['release_date'],
                status=data.get('status', 'tentative'),
                segment_id=data.get('segment_id'),
                notes=data.get('notes', ''),
            )
            return self.success_response(
                data={'id': allotment.id},
                message=f"Group '{allotment.group_name}' created."
            )
        except Exception as e:
            return self.error_response(str(e))


class GroupAllotmentUpdateView(ManageBaseMixin, View):
    """API endpoint to update a group allotment."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response("Property not found")

        pk = kwargs.get('pk')
        try:
            allotment = GroupAllotment.objects.get(pk=pk, hotel=hotel)
            data = json.loads(request.body)

            for field in ['group_name', 'group_code', 'contact_name', 'contact_email',
                          'arrival_date', 'departure_date', 'release_date',
                          'status', 'notes']:
                if field in data:
                    setattr(allotment, field, data[field])

            if 'rooms_blocked' in data:
                allotment.rooms_blocked = int(data['rooms_blocked'])
            if 'rooms_picked_up' in data:
                allotment.rooms_picked_up = int(data['rooms_picked_up'])
            if 'agreed_rate' in data:
                allotment.agreed_rate = Decimal(str(data['agreed_rate']))
            if 'segment_id' in data:
                allotment.segment_id = data['segment_id'] or None

            allotment.save()
            return self.success_response(message=f"Group '{allotment.group_name}' updated.")
        except GroupAllotment.DoesNotExist:
            return self.error_response("Allotment not found", status=404)
        except Exception as e:
            return self.error_response(str(e))


class GroupAllotmentDeleteView(ManageBaseMixin, View):
    """API endpoint to delete a group allotment."""

    def post(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        pk = kwargs.get('pk')
        try:
            allotment = GroupAllotment.objects.get(pk=pk, hotel=hotel)
            name = allotment.group_name
            allotment.delete()
            return self.success_response(message=f"Group '{name}' deleted.")
        except GroupAllotment.DoesNotExist:
            return self.error_response("Allotment not found", status=404)


class DisplacementAnalysisView(ManageBaseMixin, View):
    """
    AJAX endpoint for ad-hoc displacement analysis.

    GET /org/<org>/<prop>/api/displacement-analysis/?rooms=3&arrival=2026-06-01&departure=2026-06-11&rate=55&commission=10&supplement=0&pax=2
    """

    def get(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response("Property not found")

        try:
            arrival = date.fromisoformat(request.GET.get('arrival', ''))
            departure = date.fromisoformat(request.GET.get('departure', ''))
        except (ValueError, TypeError):
            return self.error_response("Invalid arrival/departure date format (use YYYY-MM-DD)")

        commission = float(request.GET.get('commission', 10))
        supplement = float(request.GET.get('supplement', 0))
        pax = int(request.GET.get('pax', 2))
        group_name = request.GET.get('group_name', 'Ad-hoc analysis')

        # Parse room allocations: [{room_type_id, rooms, rate}, ...]
        room_allocations = []
        raw_allocs = request.GET.get('room_allocations', '')
        if raw_allocs:
            try:
                room_allocations = json.loads(raw_allocs)
            except (json.JSONDecodeError, TypeError):
                pass

        # Backward compat: single room_type_id + rooms + rate
        if not room_allocations:
            rate = float(request.GET.get('rate', 0))
            room_type_id = request.GET.get('room_type_id', '')
            rooms = int(request.GET.get('rooms', 1))
            if room_type_id:
                room_allocations = [{'room_type_id': int(room_type_id), 'rooms': rooms, 'rate': rate}]
            else:
                room_allocations = [{'rooms': rooms, 'rate': rate}]

        from pricing.services import DisplacementService
        svc = DisplacementService(hotel)

        result = svc.analyze_displacement(
            arrival=arrival,
            departure=departure,
            commission=commission,
            supplement=supplement,
            pax=pax,
            group_name=group_name,
            room_allocations=room_allocations,
        )

        if 'error' in result:
            return self.error_response(result['error'])

        return self.success_response(data=result)


class RoomAvailabilityView(ManageBaseMixin, View):
    """
    AJAX endpoint for per-room-type availability across a date range.

    GET /org/<org>/<prop>/api/room-availability/?arrival=2026-06-01&departure=2026-06-11
    """

    def get(self, request, *args, **kwargs):
        hotel = self.get_hotel(request)
        if not hotel:
            return self.error_response("Property not found")

        try:
            arrival = date.fromisoformat(request.GET.get('arrival', ''))
            departure = date.fromisoformat(request.GET.get('departure', ''))
        except (ValueError, TypeError):
            return self.error_response("Invalid date format (use YYYY-MM-DD)")

        from pricing.services import DisplacementService
        svc = DisplacementService(hotel)
        availability = svc.get_room_availability(arrival, departure)

        return self.success_response(data={'room_types': availability})


# =============================================================================
# HELPER
# =============================================================================

def sum_field(field_name):
    """Helper to create Sum expression for aggregate."""
    from django.db.models import Sum
    return Sum(field_name)
