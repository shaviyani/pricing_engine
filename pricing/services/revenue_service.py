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
    Full counterfactual displacement analysis for group bookings.

    Compares group net revenue against estimated individual revenue
    those rooms would generate, considering:
    - Actual individual fill probability (STLY occupancy, OTB pace)
    - Channel-weighted net ADR (commission-adjusted)
    - Seasonal demand patterns
    - Opportunity cost (rooms that would sit empty without the group)
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def analyze_displacement(self, allotment=None, **kwargs):
        """
        Full counterfactual displacement analysis.

        Accepts either a GroupAllotment object OR ad-hoc keyword parameters:
            rooms, arrival, departure, rate, commission, supplement, pax

        Returns dict with recommendation, revenue comparison, break-even rate.
        """
        if allotment:
            arrival = allotment.arrival_date
            departure = allotment.departure_date
            commission_pct = 10.0
            meal_supplement = 0.0
            pax = 2
            group_name = allotment.group_name
            room_allocations = [{'rooms': allotment.rooms_blocked, 'rate': float(allotment.agreed_rate)}]
            if allotment.agent and hasattr(allotment.agent, 'channel'):
                ch = allotment.agent.channel
                if ch:
                    commission_pct = float(ch.commission_percent)
            if allotment.rate_plan:
                meal_supplement = float(allotment.rate_plan.meal_supplement)
        else:
            arrival = kwargs['arrival']
            departure = kwargs['departure']
            commission_pct = float(kwargs.get('commission', 10))
            meal_supplement = float(kwargs.get('supplement', 0))
            pax = int(kwargs.get('pax', 2))
            group_name = kwargs.get('group_name', 'Ad-hoc analysis')

        # Parse room allocations: [{room_type_id, rooms, rate}, ...]
        if not allotment:
            room_allocations = kwargs.get('room_allocations', [])
            if not room_allocations:
                rooms_fallback = int(kwargs.get('rooms', 1))
                rate_fallback = float(kwargs.get('rate', 0))
                room_allocations = [{'rooms': rooms_fallback, 'rate': rate_fallback}]

        # Resolve room type objects for each allocation
        from pricing.models import RoomType
        resolved_allocs = []
        total_group_rooms = 0
        for alloc in room_allocations:
            rt_id = alloc.get('room_type_id')
            rt_rooms = int(alloc.get('rooms', 1))
            rt_rate = float(alloc.get('rate', 0))
            rt_obj = None
            if rt_id:
                try:
                    rt_obj = RoomType.objects.get(id=int(rt_id), hotel=self.hotel)
                except RoomType.DoesNotExist:
                    pass
            resolved_allocs.append({
                'room_type': rt_obj, 'rooms': rt_rooms, 'rate': rt_rate,
            })
            total_group_rooms += rt_rooms

        rooms = total_group_rooms

        nights = (departure - arrival).days
        if nights <= 0:
            return {'error': 'Departure must be after arrival'}

        total_rooms = self.hotel.get_total_rooms()

        # === 1. GROUP NET REVENUE (per room-type allocation) ===
        group_room_revenue = sum(a['rate'] * a['rooms'] * nights for a in resolved_allocs)
        group_meal_total = meal_supplement * pax * nights
        group_gross = group_room_revenue + group_meal_total
        group_commission = group_gross * (commission_pct / 100)
        group_net = group_gross - group_commission
        # Weighted average rate for display
        group_rate = group_room_revenue / (rooms * nights) if rooms * nights > 0 else 0

        # === 2. ESTIMATE INDIVIDUAL FILL RATE ===
        fill_rate, fill_components = self._estimate_fill_rate(
            arrival, departure, rooms, total_rooms
        )

        # === 3. PER-ROOM-TYPE CHANNEL-WEIGHTED NET ADR ===
        individual_net = 0.0
        room_type_breakdown = []
        combined_channel_mix = []

        for alloc in resolved_allocs:
            rt_obj = alloc['room_type']
            rt_rooms = alloc['rooms']
            channel_adr, channel_mix = self._get_channel_weighted_adr(
                arrival, room_type=rt_obj)
            rt_would_sell = rt_rooms * fill_rate
            rt_individual = channel_adr * rt_would_sell * nights
            individual_net += rt_individual
            room_type_breakdown.append({
                'room_type_name': rt_obj.name if rt_obj else 'All Types',
                'rooms': rt_rooms,
                'net_adr': round(channel_adr, 2),
                'would_sell': round(rt_would_sell, 1),
                'individual_net': round(rt_individual, 2),
            })
            if not combined_channel_mix:
                combined_channel_mix = channel_mix

        # Weighted average ADR across all room types for display
        if rooms > 0:
            channel_adr_avg = sum(
                rt['net_adr'] * rt['rooms'] for rt in room_type_breakdown
            ) / rooms
        else:
            channel_adr_avg = 0.0

        # === 4. INDIVIDUAL NET REVENUE (counterfactual) ===
        rooms_that_would_sell = rooms * fill_rate

        # === 5. OTB REVENUE THAT WOULD BE DISPLACED ===
        otb_displacement = self._get_otb_revenue(arrival, departure, resolved_allocs)

        # === 6. DISPLACEMENT ===
        displacement = group_net - individual_net
        displacement_per_rn = displacement / (rooms * nights) if rooms * nights > 0 else 0

        # === 7. BREAK-EVEN RATE ===
        if rooms * nights > 0 and (1 - commission_pct / 100) > 0:
            breakeven_gross_per_rn = (individual_net / (rooms * nights))
            breakeven_rate = breakeven_gross_per_rn / (1 - commission_pct / 100)
            meal_per_rn = meal_supplement * pax
            breakeven_rate = breakeven_rate - meal_per_rn
        else:
            breakeven_rate = 0

        negotiation_gap = group_rate - breakeven_rate

        # === 8. RECOMMENDATION ===
        recommendation, confidence, reasoning = self._make_recommendation(
            displacement, fill_rate, group_rate, breakeven_rate,
            rooms, total_rooms, nights
        )

        return {
            'group_name': group_name,
            'rooms': rooms,
            'nights': nights,
            'total_room_nights': rooms * nights,

            # Group side
            'group_rate': round(group_rate, 2),
            'group_gross': round(group_gross, 2),
            'group_commission': round(group_commission, 2),
            'group_commission_pct': commission_pct,
            'group_net': round(group_net, 2),
            'group_net_per_rn': round(group_net / (rooms * nights), 2) if rooms * nights > 0 else 0,
            'meal_supplement': meal_supplement,
            'group_alloc_breakdown': [
                {
                    'room_type_name': a['room_type'].name if a['room_type'] else 'Unspecified',
                    'rooms': a['rooms'],
                    'rate': round(a['rate'], 2),
                    'room_nights': a['rooms'] * nights,
                    'revenue': round(a['rate'] * a['rooms'] * nights, 2),
                }
                for a in resolved_allocs
            ],

            # Individual side (counterfactual)
            'fill_rate': round(fill_rate, 3),
            'fill_rate_pct': round(fill_rate * 100, 1),
            'fill_components': fill_components,
            'rooms_that_would_sell': round(rooms_that_would_sell, 1),
            'channel_weighted_adr': round(channel_adr_avg, 2),
            'channel_mix': combined_channel_mix,
            'room_type_breakdown': room_type_breakdown,
            'individual_net': round(individual_net, 2),
            'individual_net_per_rn': round(individual_net / (rooms * nights), 2) if rooms * nights > 0 else 0,

            # Displacement
            'displacement': round(displacement, 2),
            'displacement_per_rn': round(displacement_per_rn, 2),
            'displacement_pct': round(
                displacement / individual_net * 100, 1
            ) if individual_net > 0 else 0,

            # OTB displacement
            'otb_revenue': round(otb_displacement['total_revenue'], 2),
            'otb_room_nights': otb_displacement['total_room_nights'],
            'otb_bookings': otb_displacement['total_bookings'],
            'otb_by_room_type': otb_displacement['by_room_type'],

            # Break-even
            'breakeven_rate': round(breakeven_rate, 2),
            'negotiation_gap': round(negotiation_gap, 2),

            # Recommendation
            'recommendation': recommendation,
            'confidence': confidence,
            'reasoning': reasoning,
        }

    def _estimate_fill_rate(self, arrival, departure, block_rooms, total_rooms):
        """
        Estimate what fraction of blocked rooms would sell individually.

        Combines STLY occupancy (40%), current OTB pace (30%),
        block-size ratio (20%), days-out uncertainty (10%).
        """
        from pricing.utils import build_daily_occupancy_map

        today = date.today()
        days_out = (arrival - today).days

        # --- STLY occupancy ---
        try:
            stly_arrival = arrival.replace(year=arrival.year - 1)
            stly_departure = departure.replace(year=departure.year - 1)
            stly_map = build_daily_occupancy_map(
                self.hotel, stly_arrival, stly_departure - timedelta(days=1)
            )
            stly_nights = sum(stly_map.values())
            stly_available = total_rooms * (stly_departure - stly_arrival).days
            stly_occ = stly_nights / stly_available if stly_available > 0 else 0.5
        except Exception:
            stly_occ = 0.5

        # --- Current OTB pace ---
        try:
            otb_map = build_daily_occupancy_map(
                self.hotel, arrival, departure - timedelta(days=1)
            )
            otb_nights = sum(otb_map.values())
            otb_available = total_rooms * (departure - arrival).days
            otb_occ = otb_nights / otb_available if otb_available > 0 else 0
        except Exception:
            otb_occ = 0

        # --- Block-size ratio (larger block = harder to fill individually) ---
        block_ratio = block_rooms / total_rooms if total_rooms > 0 else 0.5
        block_factor = max(0.2, 1.0 - block_ratio)

        # --- Days-out factor ---
        if days_out <= 14:
            days_factor = 0.95
        elif days_out <= 30:
            days_factor = 0.85
        elif days_out <= 60:
            days_factor = 0.70
        elif days_out <= 90:
            days_factor = 0.55
        else:
            days_factor = 0.40

        fill_rate = (
            stly_occ * 0.40 +
            otb_occ * 0.30 +
            block_factor * 0.20 +
            days_factor * 0.10
        )
        fill_rate = max(0.05, min(0.98, fill_rate))

        components = {
            'stly_occupancy': round(stly_occ * 100, 1),
            'otb_occupancy': round(otb_occ * 100, 1),
            'block_ratio': round(block_ratio * 100, 1),
            'block_factor': round(block_factor, 2),
            'days_out': days_out,
            'days_factor': round(days_factor, 2),
        }
        return fill_rate, components

    def _get_channel_weighted_adr(self, target_date, room_type=None):
        """
        Calculate channel-weighted net ADR from actual booking data
        for the same calendar month, optionally filtered by room type.
        """
        from pricing.models import Reservation

        month = target_date.month
        qs = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__month=month,
            status__in=Reservation.ACTIVE_STATUSES,
        )
        if room_type:
            qs = qs.filter(room_type=room_type)
        reservations = qs.select_related('channel')

        channel_data = defaultdict(lambda: {
            'revenue': Decimal('0'), 'nights': 0, 'commission_pct': Decimal('0'),
        })

        for res in reservations:
            ch_name = res.channel.name if res.channel else 'Direct'
            ch_commission = res.channel.commission_percent if res.channel else Decimal('0')
            channel_data[ch_name]['revenue'] += res.total_amount or Decimal('0')
            channel_data[ch_name]['nights'] += res.nights or 0
            channel_data[ch_name]['commission_pct'] = ch_commission

        total_nights = sum(d['nights'] for d in channel_data.values())
        channel_mix = []
        weighted_net_adr = Decimal('0')

        if total_nights > 0:
            for ch_name, data in channel_data.items():
                if data['nights'] > 0:
                    gross_adr = data['revenue'] / data['nights']
                    net_adr = gross_adr * (1 - data['commission_pct'] / 100)
                    share = Decimal(str(data['nights'])) / Decimal(str(total_nights))
                    weighted_net_adr += net_adr * share
                    channel_mix.append({
                        'channel': ch_name,
                        'share_pct': round(float(share * 100), 1),
                        'gross_adr': round(float(gross_adr), 2),
                        'commission_pct': float(data['commission_pct']),
                        'net_adr': round(float(net_adr), 2),
                        'room_nights': data['nights'],
                    })

        if weighted_net_adr == 0:
            try:
                from pricing.services.pricing_service import PricingService
                svc = PricingService(self.hotel)
                card = svc.get_rate_card(target_date)
                rates = []
                for rt in card.get('room_types', []):
                    # If room_type specified, only use that room type's rates
                    if room_type and rt.get('room_type_id') != room_type.id:
                        continue
                    for ch in rt.get('channels', []):
                        for rp in ch.get('rate_plans', []):
                            rates.append(Decimal(str(rp.get('room_rate', 0))))
                if rates:
                    weighted_net_adr = sum(rates) / len(rates)
            except Exception:
                pass

        channel_mix.sort(key=lambda x: x.get('share_pct', 0), reverse=True)
        return float(weighted_net_adr), channel_mix

    def _get_otb_revenue(self, arrival, departure, resolved_allocs):
        """
        Calculate actual on-the-books revenue that would be displaced
        by the group block for the specific room types and date range.

        Returns revenue from confirmed/future reservations that overlap
        the group stay period, filtered by the room types in the block.
        """
        from pricing.models import Reservation

        result = {
            'total_revenue': 0.0,
            'total_room_nights': 0,
            'total_bookings': 0,
            'by_room_type': [],
        }

        # Get room type IDs from allocations
        rt_ids = [a['room_type'].id for a in resolved_allocs if a['room_type']]

        if not rt_ids:
            return result

        # Find reservations overlapping the group stay for these room types
        otb_qs = Reservation.objects.filter(
            hotel=self.hotel,
            room_type_id__in=rt_ids,
            arrival_date__lt=departure,
            departure_date__gt=arrival,
            status__in=Reservation.FUTURE_STATUSES,
        ).select_related('room_type')

        # Calculate per-room-type OTB
        rt_otb = defaultdict(lambda: {'revenue': 0.0, 'room_nights': 0, 'bookings': 0})

        for res in otb_qs:
            # Only count nights that overlap with the group stay
            overlap_start = max(res.arrival_date, arrival)
            overlap_end = min(res.departure_date, departure)
            overlap_nights = (overlap_end - overlap_start).days
            if overlap_nights <= 0:
                continue

            # Pro-rate revenue for the overlapping nights
            if res.nights and res.nights > 0:
                daily_rate = float(res.total_amount or 0) / res.nights
            else:
                daily_rate = float(res.total_amount or 0)
            overlap_revenue = daily_rate * overlap_nights

            rt_name = res.room_type.name if res.room_type else 'Unknown'
            rt_otb[rt_name]['revenue'] += overlap_revenue
            rt_otb[rt_name]['room_nights'] += overlap_nights
            rt_otb[rt_name]['bookings'] += 1

        for rt_name, data in rt_otb.items():
            result['by_room_type'].append({
                'room_type_name': rt_name,
                'revenue': round(data['revenue'], 2),
                'room_nights': data['room_nights'],
                'bookings': data['bookings'],
            })
            result['total_revenue'] += data['revenue']
            result['total_room_nights'] += data['room_nights']
            result['total_bookings'] += data['bookings']

        return result

    def get_room_availability(self, arrival, departure):
        """
        Per-room-type availability for the full stay duration.

        Returns for each room type: total rooms, max occupied on any night,
        and minimum available rooms across the stay.
        """
        from pricing.models import Reservation, RoomType, PricingMatrixVersion

        nights = (departure - arrival).days
        if nights <= 0:
            return []

        # Get room types for this hotel
        active_version = PricingMatrixVersion.get_published(self.hotel)
        version_filter = {'hotel': self.hotel}
        if active_version:
            version_filter['version'] = active_version
        room_types = RoomType.objects.filter(**version_filter).order_by('sort_order')

        # Get all reservations overlapping the stay
        reservations = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__lt=departure,
            departure_date__gt=arrival,
            status__in=Reservation.FUTURE_STATUSES,
            room_type__isnull=False,
        ).values('room_type_id', 'arrival_date', 'departure_date')

        # Build per-room-type daily occupancy
        rt_daily = defaultdict(lambda: defaultdict(int))
        for res in reservations:
            overlap_start = max(res['arrival_date'], arrival)
            overlap_end = min(res['departure_date'], departure)
            current = overlap_start
            while current < overlap_end:
                rt_daily[res['room_type_id']][current] += 1
                current += timedelta(days=1)

        result = []
        for rt in room_types:
            total = rt.number_of_rooms or 0
            daily_occ = rt_daily.get(rt.id, {})
            max_occ = max(daily_occ.values()) if daily_occ else 0
            min_avail = total - max_occ
            result.append({
                'room_type_id': rt.id,
                'room_type_name': rt.name,
                'total_rooms': total,
                'max_occupied': max_occ,
                'min_available': max(0, min_avail),
            })

        return result

    def _make_recommendation(self, displacement, fill_rate, group_rate,
                              breakeven_rate, rooms, total_rooms, nights):
        """Generate accept/negotiate/reject recommendation with reasoning."""
        reasons = []
        rn = rooms * nights

        if displacement > 0:
            recommendation = 'accept'
            confidence = 'high'
            reasons.append(f'Group generates ${displacement:,.0f} more than estimated individual revenue')
            if fill_rate < 0.50:
                reasons.append(f'Low individual fill probability ({fill_rate*100:.0f}%) — rooms likely to sit empty')
            elif fill_rate < 0.70:
                reasons.append(f'Moderate individual demand ({fill_rate*100:.0f}%) supports accepting group')

        elif rn > 0 and displacement > -(rn * 5):
            recommendation = 'accept'
            confidence = 'medium'
            reasons.append(f'Minor displacement of ${abs(displacement):,.0f} (${abs(displacement/rn):,.0f}/room-night)')
            if fill_rate < 0.60:
                reasons.append(f'Low fill rate ({fill_rate*100:.0f}%) makes individual revenue uncertain')
                confidence = 'high'
            else:
                reasons.append('Guaranteed group revenue offsets small gap')

        elif breakeven_rate > 0 and group_rate < breakeven_rate * 0.85:
            recommendation = 'reject'
            confidence = 'high' if fill_rate > 0.70 else 'medium'
            gap_pct = (breakeven_rate - group_rate) / breakeven_rate * 100 if breakeven_rate > 0 else 0
            reasons.append(f'Group rate ${group_rate:,.0f} is {gap_pct:.0f}% below break-even ${breakeven_rate:,.0f}')
            if fill_rate > 0.70:
                reasons.append(f'Strong individual demand ({fill_rate*100:.0f}%) — rooms will likely sell at higher rates')
            else:
                reasons.append(f'Negotiate closer to break-even rate of ${breakeven_rate:,.0f}')

        else:
            recommendation = 'negotiate'
            confidence = 'medium'
            reasons.append(f'Displacement of ${abs(displacement):,.0f} — negotiate rate from ${group_rate:,.0f} toward ${breakeven_rate:,.0f}')
            if fill_rate > 0.75:
                reasons.append(f'High fill rate ({fill_rate*100:.0f}%) gives leverage to negotiate')
                confidence = 'high'
            elif fill_rate < 0.40:
                reasons.append(f'Low fill rate ({fill_rate*100:.0f}%) — consider accepting to secure guaranteed revenue')
                recommendation = 'accept'
                confidence = 'medium'

        block_ratio = rooms / total_rooms if total_rooms > 0 else 0
        if block_ratio > 0.30:
            reasons.append(f'Large block ({rooms}/{total_rooms} rooms = {block_ratio*100:.0f}%) — significant inventory impact')

        return recommendation, confidence, reasons

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
            total_displacement += analysis.get('displacement', 0)

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
