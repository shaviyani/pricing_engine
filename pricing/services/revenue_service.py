"""
Revenue management services: budget tracking, segment analysis,
group allotment management, displacement analysis, LOS pricing.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
from django.db.models import Sum, Count, Avg, Q, F
import calendar


class BudgetService:
    """
    Compares monthly budget targets against actual performance.
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def get_budget_vs_actual(self, year, month):
        """
        Get budget vs actual comparison for a given month.

        Returns dict with targets, actuals, and variance.
        """
        from pricing.models import MonthlyBudget, Reservation, RoomType

        budget = MonthlyBudget.objects.filter(
            hotel=self.hotel, year=year, month=month
        ).first()

        # Calculate actuals from reservations
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])

        reservations = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__lte=month_end,
            departure_date__gt=month_start,
            status__in=Reservation.FUTURE_STATUSES + Reservation.ACTIVE_STATUSES,
        )

        actual_revenue = float(reservations.aggregate(
            rev=Sum('total_amount'))['rev'] or 0)

        # Room nights in month
        total_rooms = self.hotel.get_total_rooms()
        days_in_month = calendar.monthrange(year, month)[1]
        available_room_nights = total_rooms * days_in_month

        booked_room_nights = 0
        for r in reservations:
            stay_start = max(r.arrival_date, month_start)
            stay_end = min(r.departure_date, month_end + timedelta(days=1))
            booked_room_nights += (stay_end - stay_start).days

        actual_occ = round(booked_room_nights / available_room_nights * 100, 1) if available_room_nights > 0 else 0
        actual_adr = round(actual_revenue / booked_room_nights, 2) if booked_room_nights > 0 else 0
        actual_revpar = round(actual_revenue / available_room_nights, 2) if available_room_nights > 0 else 0

        result = {
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'has_budget': budget is not None,
            'actuals': {
                'revenue': actual_revenue,
                'occupancy': actual_occ,
                'adr': actual_adr,
                'revpar': actual_revpar,
                'room_nights': booked_room_nights,
                'available_room_nights': available_room_nights,
            },
        }

        if budget:
            rev_target = float(budget.revenue_target)
            occ_target = float(budget.occupancy_target)
            adr_target = float(budget.adr_target)
            revpar_target = float(budget.revpar_target)

            result['budget'] = {
                'revenue': rev_target,
                'occupancy': occ_target,
                'adr': adr_target,
                'revpar': revpar_target,
            }
            result['variance'] = {
                'revenue': round(actual_revenue - rev_target, 2),
                'revenue_pct': round((actual_revenue / rev_target - 1) * 100, 1) if rev_target > 0 else 0,
                'occupancy': round(actual_occ - occ_target, 1),
                'adr': round(actual_adr - adr_target, 2),
                'revpar': round(actual_revpar - revpar_target, 2),
            }

        return result

    def get_ytd_summary(self, year):
        """Get year-to-date budget vs actual for all months."""
        today = date.today()
        max_month = today.month if today.year == year else 12
        months = []
        for m in range(1, max_month + 1):
            months.append(self.get_budget_vs_actual(year, m))
        return months


class SegmentAnalysisService:
    """
    Analyzes revenue and booking patterns by market segment.
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def get_segment_mix(self, start_date, end_date):
        """
        Get segment distribution for a date range.

        Uses Reservation.source field or booking_source to approximate segments.
        """
        from pricing.models import Reservation, MarketSegment

        segments = MarketSegment.objects.filter(hotel=self.hotel, is_active=True)
        reservations = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__gte=start_date,
            arrival_date__lte=end_date,
            status__in=Reservation.FUTURE_STATUSES + Reservation.ACTIVE_STATUSES,
        )

        total_rev = float(reservations.aggregate(rev=Sum('total_amount'))['rev'] or 0)
        total_nights = reservations.aggregate(n=Sum('nights'))['n'] or 0

        # Group by channel to approximate segment
        channel_data = reservations.values(
            'channel__name', 'channel__id'
        ).annotate(
            rev=Sum('total_amount'),
            count=Count('id'),
            nights=Sum('nights'),
        ).order_by('-rev')

        result = {
            'total_revenue': total_rev,
            'total_room_nights': total_nights,
            'total_bookings': reservations.count(),
            'channels': [],
        }

        for cd in channel_data:
            rev = float(cd['rev'] or 0)
            result['channels'].append({
                'channel_id': cd['channel__id'],
                'channel_name': cd['channel__name'] or 'Direct',
                'revenue': rev,
                'revenue_share': round(rev / total_rev * 100, 1) if total_rev > 0 else 0,
                'bookings': cd['count'],
                'room_nights': cd['nights'] or 0,
                'adr': round(rev / cd['nights'], 2) if cd['nights'] else 0,
            })

        return result


class AllotmentService:
    """
    Manages group allotment tracking and availability.
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def get_allotments_for_date(self, target_date):
        """Get all active allotments covering a specific date."""
        from pricing.models import GroupAllotment

        return GroupAllotment.objects.filter(
            hotel=self.hotel,
            arrival_date__lte=target_date,
            departure_date__gt=target_date,
            status__in=['tentative', 'confirmed'],
        )

    def get_blocked_rooms(self, target_date):
        """Total rooms blocked by allotments on a date."""
        allotments = self.get_allotments_for_date(target_date)
        return allotments.aggregate(
            total=Sum('rooms_blocked'))['total'] or 0

    def get_available_inventory(self, target_date):
        """Rooms available after subtracting allotment blocks."""
        total_rooms = self.hotel.get_total_rooms()
        blocked = self.get_blocked_rooms(target_date)
        return max(0, total_rooms - blocked)

    def get_allotment_summary(self, start_date, end_date):
        """Summary of allotments in a date range."""
        from pricing.models import GroupAllotment

        allotments = GroupAllotment.objects.filter(
            hotel=self.hotel,
            arrival_date__lte=end_date,
            departure_date__gt=start_date,
        ).order_by('arrival_date')

        return {
            'allotments': list(allotments),
            'total_blocked': allotments.aggregate(t=Sum('rooms_blocked'))['t'] or 0,
            'total_picked_up': allotments.aggregate(t=Sum('rooms_picked_up'))['t'] or 0,
            'count': allotments.count(),
        }

    def check_expiring_allotments(self, days_ahead=7):
        """Find allotments approaching their release date."""
        from pricing.models import GroupAllotment

        cutoff = date.today() + timedelta(days=days_ahead)
        return GroupAllotment.objects.filter(
            hotel=self.hotel,
            release_date__lte=cutoff,
            release_date__gte=date.today(),
            status__in=['tentative', 'confirmed'],
        ).order_by('release_date')


class DisplacementService:
    """
    Analyzes revenue displacement from group bookings vs individual rates.
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def analyze_displacement(self, allotment):
        """
        Calculate displacement cost for a group allotment.

        Compares group rate against what those rooms could earn
        at prevailing individual rates.
        """
        from pricing.services.pricing_service import PricingService

        pricing_svc = PricingService(self.hotel)

        # Get rate card for the allotment dates
        rate_data = pricing_svc.get_rate_card(allotment.arrival_date)

        # Average individual rate across room types
        avg_individual = Decimal('0')
        count = 0
        for rt in rate_data.get('room_types', []):
            for ch in rt.get('channels', []):
                for rp in ch.get('rate_plans', []):
                    avg_individual += Decimal(str(rp.get('room_rate', 0)))
                    count += 1

        if count > 0:
            avg_individual = (avg_individual / count).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)

        group_rate = allotment.agreed_rate
        nights = allotment.nights
        rooms = allotment.rooms_blocked

        group_revenue = float(group_rate * rooms * nights)
        individual_revenue = float(avg_individual * rooms * nights)
        displacement = round(individual_revenue - group_revenue, 2)

        return {
            'allotment': allotment,
            'group_rate': float(group_rate),
            'avg_individual_rate': float(avg_individual),
            'rate_difference': float(avg_individual - group_rate),
            'nights': nights,
            'rooms': rooms,
            'group_revenue': group_revenue,
            'individual_revenue': individual_revenue,
            'displacement_cost': displacement,
            'displacement_percent': round(
                displacement / individual_revenue * 100, 1
            ) if individual_revenue > 0 else 0,
            'is_positive': displacement <= 0,  # Group rate >= individual = no displacement
        }

    def analyze_all_active(self):
        """Displacement analysis for all active group allotments."""
        from pricing.models import GroupAllotment

        allotments = GroupAllotment.objects.filter(
            hotel=self.hotel,
            status__in=['tentative', 'confirmed'],
            departure_date__gt=date.today(),
        )

        results = []
        total_displacement = 0
        for allotment in allotments:
            analysis = self.analyze_displacement(allotment)
            results.append(analysis)
            total_displacement += analysis['displacement_cost']

        return {
            'analyses': results,
            'total_displacement': round(total_displacement, 2),
            'allotment_count': len(results),
        }


class LosService:
    """
    Length of Stay pricing service.
    Finds applicable LOS tier and returns the rate multiplier.
    """

    def __init__(self, hotel, version=None):
        self.hotel = hotel
        self.version = version

    def get_los_multiplier(self, nights, room_type=None, season=None):
        """
        Get the LOS pricing multiplier for a given stay length.

        Returns (multiplier, tier_name) or (1.0, None) if no tier matches.
        """
        from pricing.models import LengthOfStayTier

        tiers = LengthOfStayTier.objects.filter(
            hotel=self.hotel, is_active=True
        ).order_by('sort_order')

        if self.version:
            tiers = tiers.filter(Q(version=self.version) | Q(version__isnull=True))

        for tier in tiers:
            if tier.matches_stay(nights, room_type, season):
                return float(tier.get_multiplier()), tier.name

        return 1.0, None

    def get_los_curve(self, max_nights=14, room_type=None, season=None):
        """
        Build a LOS pricing curve showing multiplier at each stay length.
        Useful for visualization.
        """
        curve = []
        for n in range(1, max_nights + 1):
            mult, tier_name = self.get_los_multiplier(n, room_type, season)
            curve.append({
                'nights': n,
                'multiplier': mult,
                'adjustment_pct': round((mult - 1.0) * 100, 1),
                'tier': tier_name,
            })
        return curve
