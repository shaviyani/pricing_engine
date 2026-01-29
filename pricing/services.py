

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar


"""
Pricing calculation services.

Three-step calculation process:
1. Base Rate × Season Index = Seasonal Rate
2. Seasonal Rate + (Meal Supplement × Occupancy) = Rate Plan Price
3. Rate Plan Price × (1 - Discount%) = Final Channel Rate
"""

from decimal import Decimal, ROUND_HALF_UP
import math


def calculate_seasonal_rate(room_base_rate, season_index):
    """
    Step 1: Apply season index to base rate.
    
    Args:
        room_base_rate: Decimal - Base rate for the room (e.g., $65)
        season_index: Decimal - Season multiplier (e.g., 1.3)
    
    Returns:
        Decimal - Seasonal rate
    
    Example:
        calculate_seasonal_rate(Decimal('65.00'), Decimal('1.30'))
        >>> Decimal('84.50')
    """
    seasonal_rate = room_base_rate * season_index
    return seasonal_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy=2):
    """
    Step 2: Add meal supplements (default 2 people).
    
    Args:
        seasonal_rate: Decimal - Rate after season adjustment
        meal_supplement: Decimal - Meal cost per person (e.g., $6)
        occupancy: int - Number of people (default 2)
    
    Returns:
        Decimal - Rate plan price
    
    Example:
        calculate_rate_plan_price(Decimal('84.50'), Decimal('6.00'), 2)
        >>> Decimal('96.50')
    """
    meal_cost = meal_supplement * occupancy
    rate_plan_price = seasonal_rate + meal_cost
    return rate_plan_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_channel_rate(rate_plan_price, discount_percent):
    """
    Step 3: Apply channel discount.
    
    Args:
        rate_plan_price: Decimal - Rate after meals added (this is BAR)
        discount_percent: Decimal - Channel discount percentage (e.g., 15.00)
    
    Returns:
        Decimal - Final channel rate
    
    Example:
        calculate_channel_rate(Decimal('96.50'), Decimal('15.00'))
        >>> Decimal('82.03')
    """
    discount_multiplier = Decimal('1.00') - (discount_percent / Decimal('100.00'))
    channel_rate = rate_plan_price * discount_multiplier
    return channel_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_modifier_rate(channel_base_rate, modifier_discount_percent):
    """
    Step 4: Apply rate modifier discount (Genius, Mobile App, etc.).
    
    Args:
        channel_base_rate: Decimal - Rate after channel base discount
        modifier_discount_percent: Decimal - Additional modifier discount %
    
    Returns:
        Decimal - Final rate after modifier
    
    Example:
        calculate_modifier_rate(Decimal('96.50'), Decimal('10.00'))
        >>> Decimal('86.85')
    """
    discount_multiplier = Decimal('1.00') - (modifier_discount_percent / Decimal('100.00'))
    final_rate = channel_base_rate * discount_multiplier
    return final_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def ceil_to_increment(value, increment=5):
    """
    Round up to nearest increment.
    
    Args:
        value: Decimal or float - The value to round
        increment: int - Round up to this increment (default 5)
    
    Returns:
        Decimal - Rounded value
    
    Examples:
        ceil_to_increment(142.50) -> 145
        ceil_to_increment(96.30) -> 100
        ceil_to_increment(100.00) -> 100
        ceil_to_increment(88.75, 10) -> 90
    """
    if value is None:
        return None
    float_val = float(value)
    ceiled = math.ceil(float_val / increment) * increment
    return Decimal(str(ceiled))


def calculate_final_rate(room_base_rate, season_index, meal_supplement, 
                         channel_base_discount, modifier_discount=Decimal('0.00'),
                         commission_percent=Decimal('0.00'), occupancy=2,
                         apply_ceiling=True, ceiling_increment=5):
    """
    Enhanced calculator with BAR, channel base discount, rate modifier, and ceiling support.
    
    Full Pricing Flow:
    1. Base Rate × Season Index = Seasonal Rate
    2. Seasonal Rate + Meal Supplements = BAR (Best Available Rate)
    3. BAR - Channel Base Discount = Channel Base Rate
    4. Channel Base Rate - Modifier Discount = Final Guest Rate
    5. Final Guest Rate - Commission = Net Revenue (what you actually get)
    6. (Optional) Apply ceiling to round up rates to nearest increment
    
    Args:
        room_base_rate: Decimal - Base rate for the room
        season_index: Decimal - Season multiplier
        meal_supplement: Decimal - Meal cost per person
        channel_base_discount: Decimal - Channel's base discount from BAR
        modifier_discount: Decimal - Additional modifier discount (default 0)
        commission_percent: Decimal - Commission the channel takes (default 0)
        occupancy: int - Number of people (default 2)
        apply_ceiling: bool - Whether to round up rates (default True)
        ceiling_increment: int - Round to nearest X dollars (default 5)
    
    Returns:
        tuple: (final_rate, breakdown_dict)
    """
    # Step 1: Calculate seasonal rate
    seasonal_rate = calculate_seasonal_rate(room_base_rate, season_index)
    
    # Step 2: Calculate BAR (Best Available Rate)
    meal_cost = meal_supplement * occupancy
    bar_rate = calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy)
    
    # Step 3: Apply channel base discount
    channel_base_rate = calculate_channel_rate(bar_rate, channel_base_discount)
    
    # Step 4: Apply rate modifier discount
    final_rate = calculate_modifier_rate(channel_base_rate, modifier_discount)
    
    # Step 5: Calculate net revenue (what you actually receive)
    commission_amount = final_rate * (commission_percent / Decimal('100.00'))
    net_revenue = final_rate - commission_amount
    
    # Calculate total savings from BAR
    total_discount = channel_base_discount + modifier_discount
    total_savings = bar_rate - final_rate
    
    # Step 6: Apply ceiling to round up rates
    if apply_ceiling:
        bar_rate_display = ceil_to_increment(bar_rate, ceiling_increment)
        final_rate_display = ceil_to_increment(final_rate, ceiling_increment)
        channel_base_rate_display = ceil_to_increment(channel_base_rate, ceiling_increment)
        net_revenue_display = ceil_to_increment(net_revenue, ceiling_increment)
        # Recalculate commission based on ceiled final rate
        commission_amount_display = final_rate_display * (commission_percent / Decimal('100.00'))
        commission_amount_display = commission_amount_display.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        bar_rate_display = bar_rate
        final_rate_display = final_rate
        channel_base_rate_display = channel_base_rate
        net_revenue_display = net_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        commission_amount_display = commission_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    # Build comprehensive breakdown
    breakdown = {
        # Step 1
        'base_rate': room_base_rate,
        'season_index': season_index,
        'seasonal_rate': seasonal_rate,
        
        # Step 2
        'meal_supplement_per_person': meal_supplement,
        'occupancy': occupancy,
        'meal_cost': meal_cost,
        'bar_rate': bar_rate_display,  # Ceiled BAR
        'bar_rate_exact': bar_rate,    # Exact BAR for reference
        
        # Step 3
        'channel_base_discount_percent': channel_base_discount,
        'channel_base_discount_amount': bar_rate - channel_base_rate,
        'channel_base_rate': channel_base_rate_display,  # Ceiled
        
        # Step 4
        'modifier_discount_percent': modifier_discount,
        'modifier_discount_amount': channel_base_rate - final_rate,
        'final_rate': final_rate_display,  # Ceiled - Guest pays this
        'final_rate_exact': final_rate,    # Exact for reference
        
        # Summary
        'total_discount_percent': total_discount,
        'total_savings': total_savings,
        
        # Step 5 - Revenue
        'commission_percent': commission_percent,
        'commission_amount': commission_amount_display,
        'net_revenue': net_revenue_display,  # Ceiled - You receive this
        'net_revenue_exact': net_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        
        # Ceiling info
        'ceiling_applied': apply_ceiling,
        'ceiling_increment': ceiling_increment,
    }
    
    return final_rate_display, breakdown


def calculate_final_rate_with_modifier(room_base_rate, season_index, meal_supplement, 
                                       channel_base_discount, modifier_discount=Decimal('0.00'),
                                       commission_percent=Decimal('0.00'), occupancy=2):
    """
    Enhanced calculator with BAR, channel base discount, and rate modifier support.
    (Original function without ceiling - kept for backward compatibility)
    
    Full Pricing Flow:
    1. Base Rate × Season Index = Seasonal Rate
    2. Seasonal Rate + Meal Supplements = BAR (Best Available Rate)
    3. BAR - Channel Base Discount = Channel Base Rate
    4. Channel Base Rate - Modifier Discount = Final Guest Rate
    5. Final Guest Rate - Commission = Net Revenue (what you actually get)
    
    Args:
        room_base_rate: Decimal - Base rate for the room
        season_index: Decimal - Season multiplier
        meal_supplement: Decimal - Meal cost per person
        channel_base_discount: Decimal - Channel's base discount from BAR
        modifier_discount: Decimal - Additional modifier discount (default 0)
        commission_percent: Decimal - Commission the channel takes (default 0)
        occupancy: int - Number of people (default 2)
    
    Returns:
        tuple: (final_rate, breakdown_dict)
    """
    # Step 1: Calculate seasonal rate
    seasonal_rate = calculate_seasonal_rate(room_base_rate, season_index)
    
    # Step 2: Calculate BAR (Best Available Rate)
    meal_cost = meal_supplement * occupancy
    bar_rate = calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy)
    
    # Step 3: Apply channel base discount
    channel_base_rate = calculate_channel_rate(bar_rate, channel_base_discount)
    
    # Step 4: Apply rate modifier discount
    final_rate = calculate_modifier_rate(channel_base_rate, modifier_discount)
    
    # Step 5: Calculate net revenue (what you actually receive)
    commission_amount = final_rate * (commission_percent / Decimal('100.00'))
    net_revenue = final_rate - commission_amount
    
    # Calculate total savings from BAR
    total_discount = channel_base_discount + modifier_discount
    total_savings = bar_rate - final_rate
    
    # Build comprehensive breakdown
    breakdown = {
        # Step 1
        'base_rate': room_base_rate,
        'season_index': season_index,
        'seasonal_rate': seasonal_rate,
        
        # Step 2
        'meal_supplement_per_person': meal_supplement,
        'occupancy': occupancy,
        'meal_cost': meal_cost,
        'bar_rate': bar_rate,  # This is your BAR - the key reference rate
        
        # Step 3
        'channel_base_discount_percent': channel_base_discount,
        'channel_base_discount_amount': bar_rate - channel_base_rate,
        'channel_base_rate': channel_base_rate,
        
        # Step 4
        'modifier_discount_percent': modifier_discount,
        'modifier_discount_amount': channel_base_rate - final_rate,
        'final_rate': final_rate,  # Guest pays this
        
        # Summary
        'total_discount_percent': total_discount,
        'total_savings': total_savings,
        
        # Step 5 - Revenue
        'commission_percent': commission_percent,
        'commission_amount': commission_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        'net_revenue': net_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),  # You receive this
    }
    
    return final_rate, breakdown


"""
Revenue Forecast Service

Calculates projected revenue based on:
- Room inventory (number_of_rooms per RoomType)
- Expected occupancy per season
- Channel distribution mix (from Channel.distribution_share_percent)
- Pricing setup (rates, modifiers, discounts, commissions)
"""

class RevenueForecastService:
    """
    Service for calculating revenue forecasts with channel distribution.
    
    Now supports multi-property filtering via 'hotel' parameter.
    """
    
    def __init__(self, hotel=None):
        """
        Initialize forecast service.
        
        Args:
            hotel: Property instance to filter by (None for all properties)
        """
        self.hotel = hotel
    
    def _get_seasons(self):
        """Get seasons queryset, filtered by hotel if set."""
        from pricing.models import Season
        qs = Season.objects.all()
        if self.hotel:
            qs = qs.filter(hotel=self.hotel)
        return qs.order_by('start_date')
    
    def _get_room_types(self):
        """Get room types queryset, filtered by hotel if set."""
        from pricing.models import RoomType
        qs = RoomType.objects.all()
        if self.hotel:
            qs = qs.filter(hotel=self.hotel)
        return qs
    
    def _get_total_rooms(self):
        """Get total room count, filtered by hotel if set."""
        return sum(room.number_of_rooms for room in self._get_room_types())
    
    def calculate_seasonal_forecast(self):
        """
        Calculate revenue forecast by season with channel breakdown.
        
        Returns:
            list of dicts with season data
        """
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if total_rooms == 0:
            return []
        
        seasonal_data = []
        
        for season in seasons:
            season_forecast = self._calculate_season_revenue(season, total_rooms)
            seasonal_data.append(season_forecast)
        
        return seasonal_data
    
    def calculate_monthly_forecast(self, year=None):
        """
        Calculate revenue forecast by month.
        
        Args:
            year: Optional year (defaults to current calendar year if most seasons are in it)
        
        Returns:
            list of dicts with monthly data
        """
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if not seasons.exists() or total_rooms == 0:
            return []
        
        # Determine the main year based on where most season days fall
        if year is None:
            year_days = defaultdict(int)
            for season in seasons:
                current_date = season.start_date
                while current_date <= season.end_date:
                    year_days[current_date.year] += 1
                    current_date += timedelta(days=1)
            
            year = max(year_days.items(), key=lambda x: x[1])[0] if year_days else seasons.first().start_date.year
        
        monthly_data = []
        
        for month_num in range(1, 13):
            month_start = date(year, month_num, 1)
            last_day = calendar.monthrange(year, month_num)[1]
            month_end = date(year, month_num, last_day)
            
            month_forecast = self._calculate_month_revenue(
                month_start, month_end, seasons, total_rooms
            )
            
            monthly_data.append(month_forecast)
        
        return monthly_data
    
    def _calculate_season_revenue(self, season, total_rooms):
        """Calculate revenue for a specific season."""
        from pricing.models import Channel
        
        days = (season.end_date - season.start_date).days + 1
        available_room_nights = total_rooms * days
        occupancy_rate = season.expected_occupancy / Decimal('100.00')
        occupied_room_nights = int(available_room_nights * occupancy_rate)
        
        # Channels are shared (no hotel filter)
        channels = Channel.objects.all()
        channel_breakdown = []
        
        total_gross_revenue = Decimal('0.00')
        total_net_revenue = Decimal('0.00')
        total_commission = Decimal('0.00')
        total_weighted_room_nights = 0
        
        for channel in channels:
            if channel.distribution_share_percent == 0:
                continue
            
            channel_share = channel.distribution_share_percent / Decimal('100.00')
            channel_room_nights = int(occupied_room_nights * channel_share)
            
            if channel_room_nights == 0:
                continue
            
            channel_adr = self._calculate_channel_adr(channel, season)
            
            channel_gross = channel_adr * channel_room_nights
            channel_commission = channel_gross * (channel.commission_percent / Decimal('100.00'))
            channel_net = channel_gross - channel_commission
            
            channel_breakdown.append({
                'channel': channel,
                'share_percent': channel.distribution_share_percent,
                'room_nights': channel_room_nights,
                'adr': channel_adr,
                'gross_revenue': channel_gross,
                'commission_amount': channel_commission,
                'net_revenue': channel_net,
            })
            
            total_gross_revenue += channel_gross
            total_net_revenue += channel_net
            total_commission += channel_commission
            total_weighted_room_nights += channel_room_nights
        
        weighted_adr = (total_gross_revenue / total_weighted_room_nights 
                       if total_weighted_room_nights > 0 else Decimal('0.00'))
        
        return {
            'season': season,
            'days': days,
            'available_room_nights': available_room_nights,
            'occupied_room_nights': total_weighted_room_nights,
            'occupancy_percent': season.expected_occupancy,
            'weighted_adr': weighted_adr,
            'gross_revenue': total_gross_revenue,
            'commission_amount': total_commission,
            'net_revenue': total_net_revenue,
            'channel_breakdown': channel_breakdown,
        }
    
    def _calculate_channel_adr(self, channel, season):
        """Calculate weighted average ADR for a channel in a season."""
        from pricing.models import RatePlan, RateModifier
        from pricing.services import calculate_final_rate_with_modifier
        
        room_types = self._get_room_types()
        rate_plans = RatePlan.objects.all()  # Shared
        
        if not room_types.exists() or not rate_plans.exists():
            return Decimal('0.00')
        
        total_rate = Decimal('0.00')
        count = 0
        
        # Get modifiers for this channel (shared)
        modifiers = RateModifier.objects.filter(channel=channel, active=True)
        
        for room in room_types:
            for rate_plan in rate_plans:
                if modifiers.exists():
                    for modifier in modifiers:
                        season_discount = modifier.get_discount_for_season(season)
                        
                        final_rate, _ = calculate_final_rate_with_modifier(
                            room_base_rate=room.get_effective_base_rate(),
                            season_index=season.season_index,
                            meal_supplement=rate_plan.meal_supplement,
                            channel_base_discount=channel.base_discount_percent,
                            modifier_discount=season_discount,
                            commission_percent=Decimal('0.00'),
                            occupancy=2
                        )
                        total_rate += final_rate
                        count += 1
                else:
                    final_rate, _ = calculate_final_rate_with_modifier(
                        room_base_rate=room.get_effective_base_rate(),
                        season_index=season.season_index,
                        meal_supplement=rate_plan.meal_supplement,
                        channel_base_discount=channel.base_discount_percent,
                        modifier_discount=Decimal('0.00'),
                        commission_percent=Decimal('0.00'),
                        occupancy=2
                    )
                    total_rate += final_rate
                    count += 1
        
        if count > 0:
            return (total_rate / count).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def _calculate_month_revenue(self, month_start, month_end, seasons, total_rooms):
        """Calculate revenue for a specific month."""
        from pricing.models import Channel
        
        days_in_month = (month_end - month_start).days + 1
        
        month_gross = Decimal('0.00')
        month_commission = Decimal('0.00')
        month_revenue = Decimal('0.00')
        month_room_nights = 0
        channel_contributions = defaultdict(lambda: {
            'room_nights': 0,
            'gross_revenue': Decimal('0.00'),
            'commission': Decimal('0.00'),
            'net_revenue': Decimal('0.00'),
        })
        
        for season in seasons:
            overlap_start = max(month_start, season.start_date)
            overlap_end = min(month_end, season.end_date)
            
            if overlap_start <= overlap_end:
                overlap_days = (overlap_end - overlap_start).days + 1
                season_data = self._calculate_season_revenue(season, total_rooms)
                proportion = Decimal(str(overlap_days)) / Decimal(str(season_data['days']))
                
                month_gross += season_data['gross_revenue'] * proportion
                month_commission += season_data['commission_amount'] * proportion
                month_revenue += season_data['net_revenue'] * proportion
                month_room_nights += int(season_data['occupied_room_nights'] * proportion)
                
                for channel_data in season_data['channel_breakdown']:
                    channel_id = channel_data['channel'].id
                    channel_contributions[channel_id]['room_nights'] += int(
                        channel_data['room_nights'] * proportion
                    )
                    channel_contributions[channel_id]['gross_revenue'] += (
                        channel_data['gross_revenue'] * proportion
                    )
                    channel_contributions[channel_id]['commission'] += (
                        channel_data['commission_amount'] * proportion
                    )
                    channel_contributions[channel_id]['net_revenue'] += (
                        channel_data['net_revenue'] * proportion
                    )
        
        channels = Channel.objects.all()
        channel_breakdown = []
        for channel in channels:
            if channel.id in channel_contributions:
                contrib = channel_contributions[channel.id]
                channel_breakdown.append({
                    'channel': channel,
                    'room_nights': contrib['room_nights'],
                    'gross_revenue': contrib['gross_revenue'],
                    'commission_amount': contrib['commission'],
                    'net_revenue': contrib['net_revenue'],
                })
        
        available_room_nights = total_rooms * days_in_month
        occupancy_percent = (
            Decimal(str(month_room_nights)) / Decimal(str(available_room_nights)) * Decimal('100.00')
            if available_room_nights > 0 else Decimal('0.00')
        )
        
        return {
            'month': month_start.month,
            'month_name': month_start.strftime('%B'),
            'days': days_in_month,
            'available_room_nights': available_room_nights,
            'occupied_room_nights': month_room_nights,
            'occupancy_percent': occupancy_percent.quantize(Decimal('0.1')),
            'gross_revenue': month_gross.quantize(Decimal('0.01')),
            'commission_amount': month_commission.quantize(Decimal('0.01')),
            'net_revenue': month_revenue.quantize(Decimal('0.01')),
            'channel_breakdown': channel_breakdown,
        }
    
    def calculate_occupancy_forecast(self, year=None):
        """Calculate monthly occupancy forecast."""
        seasons = self._get_seasons()
        total_rooms = self._get_total_rooms()
        
        if not seasons.exists() or total_rooms == 0:
            return None
        
        monthly_forecast = self.calculate_monthly_forecast(year)
        
        if not monthly_forecast:
            return None
        
        monthly_data = []
        total_available_nights = 0
        total_occupied_nights = 0
        occupancy_days_80_plus = 0
        
        for month in monthly_forecast:
            monthly_data.append({
                'month': month['month'],
                'month_name': month['month_name'][:3],
                'occupancy_percent': float(month['occupancy_percent']),
                'available_room_nights': month['available_room_nights'],
                'occupied_room_nights': month['occupied_room_nights'],
                'days': month['days'],
            })
            
            total_available_nights += month['available_room_nights']
            total_occupied_nights += month['occupied_room_nights']
            
            if month['occupancy_percent'] >= Decimal('80.00'):
                occupancy_days_80_plus += month['days']
        
        annual_occupancy = (
            Decimal(str(total_occupied_nights)) / Decimal(str(total_available_nights)) * Decimal('100.00')
            if total_available_nights > 0 else Decimal('0.00')
        )
        
        peak_month = max(monthly_data, key=lambda x: x['occupancy_percent'])
        low_month = min(monthly_data, key=lambda x: x['occupancy_percent'])
        
        seasonal_data = []
        for season in seasons:
            days = (season.end_date - season.start_date).days + 1
            available_nights = total_rooms * days
            occupancy_rate = season.expected_occupancy / Decimal('100.00')
            occupied_nights = int(available_nights * occupancy_rate)
            
            seasonal_data.append({
                'season_name': season.name,
                'occupancy_percent': float(season.expected_occupancy),
                'days': days,
                'available_room_nights': available_nights,
                'occupied_room_nights': occupied_nights,
                'start_date': season.start_date.strftime('%b %d'),
                'end_date': season.end_date.strftime('%b %d'),
            })
        
        return {
            'monthly_data': monthly_data,
            'annual_metrics': {
                'annual_occupancy': float(annual_occupancy),
                'peak_month': peak_month['month_name'],
                'peak_occupancy': peak_month['occupancy_percent'],
                'low_month': low_month['month_name'],
                'low_occupancy': low_month['occupancy_percent'],
                'days_80_plus': occupancy_days_80_plus,
                'total_available_nights': total_available_nights,
                'total_occupied_nights': total_occupied_nights,
            },
            'seasonal_data': seasonal_data,
        }
    
    def validate_channel_distribution(self):
        """Validate that channel distribution shares equal 100%."""
        from pricing.models import Channel
        
        total = Channel.objects.aggregate(
            total=Sum('distribution_share_percent')
        )['total'] or Decimal('0.00')
        
        is_valid = abs(total - Decimal('100.00')) < Decimal('0.01')
        
        if is_valid:
            message = f"✓ Total distribution: {total}%"
        elif total == Decimal('0.00'):
            message = "⚠ No distribution shares set"
        elif total < Decimal('100.00'):
            message = f"⚠ Total distribution: {total}% (missing {Decimal('100.00') - total}%)"
        else:
            message = f"⚠ Total distribution: {total}% (exceeds by {total - Decimal('100.00')}%)"
        
        return is_valid, total, message
    
    
    
"""
Pickup Analysis Service - Works directly with Reservation data.

This version calculates OTB (On The Books) metrics directly from Reservation
data, eliminating the need for separate MonthlyPickupSnapshot records.

Usage:
    from pricing.services import PickupAnalysisService
    
    service = PickupAnalysisService(property=prop)
    forecast = service.get_forecast_summary(months_ahead=6)
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
import calendar


class PickupAnalysisService:
    """
    Service for pickup analysis, curve building, and forecasting.
    
    Supports multi-property filtering via the property parameter.
    Calculates OTB directly from Reservation data.
    
    Forecast Methodology:
    - 50% weight: Historical pickup curve for season type
    - 30% weight: STLY (Same Time Last Year) comparison
    - 20% weight: Recent booking velocity trend
    """
    
    def __init__(self, property=None):
        """
        Initialize service with optional property filter.
        
        Args:
            property: Optional Property instance to filter all queries.
                     If None, analyzes all properties (legacy behavior).
        """
        self.property = property
    
    # =========================================================================
    # HELPER METHODS FOR PROPERTY FILTERING
    # =========================================================================
    
    def _get_reservations_queryset(self):
        """Get Reservation queryset, filtered by property if set."""
        from pricing.models import Reservation
        qs = Reservation.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_room_types(self):
        """Get RoomType queryset, filtered by property if set."""
        from pricing.models import RoomType
        qs = RoomType.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_total_rooms(self):
        """Get total room count, filtered by property if set."""
        return sum(room.number_of_rooms for room in self._get_room_types()) or 20
    
    def _get_seasons_queryset(self):
        """Get Season queryset, filtered by property if set."""
        from pricing.models import Season
        qs = Season.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs
    
    def _get_season_for_date(self, target_date):
        """Get the season that contains the target date."""
        return self._get_seasons_queryset().filter(
            start_date__lte=target_date,
            end_date__gte=target_date
        ).first()
    
    def _get_season_type(self, target_date):
        """Determine season type for a date (peak, high, shoulder, low)."""
        season = self._get_season_for_date(target_date)
        if season:
            idx = float(season.season_index)
            if idx >= 1.3:
                return 'peak'
            elif idx >= 1.1:
                return 'high'
            elif idx >= 0.9:
                return 'shoulder'
            else:
                return 'low'
        
        # Default based on month for Maldives seasonality
        month = target_date.month
        if month in [12, 1, 2, 3, 4]:
            if month in [12, 1, 2]:
                return 'peak'
            return 'high'
        elif month in [5, 6, 7, 8, 9]:
            return 'low'
        else:
            return 'shoulder'
    
    # =========================================================================
    # OTB CALCULATION (Direct from Reservations)
    # =========================================================================
    
    def get_otb_for_month(self, target_month):
        """
        Calculate OTB (On The Books) for a specific month from Reservation data.
        
        Args:
            target_month: First day of target month (date)
        
        Returns:
            Dict with OTB metrics
        """
        from django.db.models import Sum, Count
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get confirmed reservations for this month
        reservations = self._get_reservations_queryset().filter(
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        stats = reservations.aggregate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        )
        
        otb_room_nights = stats['room_nights'] or 0
        otb_revenue = stats['revenue'] or Decimal('0.00')
        otb_reservations = stats['count'] or 0
        
        # Calculate occupancy
        total_rooms = self._get_total_rooms()
        total_available = total_rooms * last_day
        
        otb_occupancy = Decimal('0.00')
        if total_available > 0:
            otb_occupancy = (
                Decimal(str(otb_room_nights)) / Decimal(str(total_available)) * 100
            ).quantize(Decimal('0.1'))
        
        # Calculate days out
        today = date.today()
        days_out = (month_start - today).days
        if days_out < 0:
            days_out = 0
        
        return {
            'target_month': target_month,
            'month_name': target_month.strftime('%B %Y'),
            'days_out': days_out,
            'otb_room_nights': otb_room_nights,
            'otb_revenue': otb_revenue,
            'otb_reservations': otb_reservations,
            'otb_occupancy': float(otb_occupancy),
            'total_available': total_available,
            'total_rooms': total_rooms,
        }
    
    # =========================================================================
    # VELOCITY & PACE ANALYSIS
    # =========================================================================
    
    def calculate_booking_velocity(self, target_month, lookback_days=14):
        """
        Calculate booking velocity (bookings per day) for a target month.
        
        Args:
            target_month: First day of target month
            lookback_days: Number of days to look back for trend
        
        Returns:
            Dict with velocity metrics
        """
        from django.db.models import Sum, Count
        
        today = date.today()
        lookback_start = today - timedelta(days=lookback_days)
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get bookings created in lookback period for target month
        recent_bookings = self._get_reservations_queryset().filter(
            booking_date__gte=lookback_start,
            booking_date__lte=today,
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        stats = recent_bookings.aggregate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        )
        
        room_nights = stats['room_nights'] or 0
        revenue = stats['revenue'] or Decimal('0.00')
        bookings = stats['count'] or 0
        
        # Calculate daily averages
        days = lookback_days or 1
        
        return {
            'target_month': target_month,
            'lookback_days': lookback_days,
            'total_bookings': bookings,
            'total_room_nights': room_nights,
            'total_revenue': float(revenue),
            'bookings_per_day': round(bookings / days, 2),
            'room_nights_per_day': round(room_nights / days, 2),
            'revenue_per_day': float((revenue / days).quantize(Decimal('0.01'))),
        }
    
    def get_stly_otb(self, target_month):
        """
        Get STLY (Same Time Last Year) OTB for comparison.
        
        Args:
            target_month: First day of target month
        
        Returns:
            Dict with STLY OTB data
        """
        from dateutil.relativedelta import relativedelta
        
        # STLY month
        stly_month = target_month - relativedelta(years=1)
        
        # Get STLY OTB
        return self.get_otb_for_month(stly_month)
    
    # =========================================================================
    # LEAD TIME ANALYSIS
    # =========================================================================
    
    def analyze_lead_time_distribution(self, start_date=None, end_date=None):
        """
        Analyze booking lead time distribution.
        
        Args:
            start_date: Start of analysis period (default: 90 days ago)
            end_date: End of analysis period (default: today)
        
        Returns:
            Dict with lead time buckets and statistics
        """
        from django.db.models import Avg, Min, Max, Count
        
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=90)
        
        # Get bookings in period with lead time
        bookings = self._get_reservations_queryset().filter(
            booking_date__gte=start_date,
            booking_date__lte=end_date,
            status__in=['confirmed', 'checked_in', 'checked_out']
        ).exclude(
            lead_time_days__isnull=True
        )
        
        # Overall stats
        stats = bookings.aggregate(
            avg_lead_time=Avg('lead_time_days'),
            min_lead_time=Min('lead_time_days'),
            max_lead_time=Max('lead_time_days'),
            total_bookings=Count('id'),
        )
        
        # Bucket distribution
        buckets = [
            {'label': '0-7 days', 'min': 0, 'max': 7},
            {'label': '8-14 days', 'min': 8, 'max': 14},
            {'label': '15-30 days', 'min': 15, 'max': 30},
            {'label': '31-60 days', 'min': 31, 'max': 60},
            {'label': '61-90 days', 'min': 61, 'max': 90},
            {'label': '90+ days', 'min': 91, 'max': 9999},
        ]
        
        total_bookings = stats['total_bookings'] or 1
        bucket_data = []
        
        for bucket in buckets:
            count = bookings.filter(
                lead_time_days__gte=bucket['min'],
                lead_time_days__lte=bucket['max']
            ).count()
            
            percent = round(count / total_bookings * 100, 1)
            
            bucket_data.append({
                'label': bucket['label'],
                'count': count,
                'percent': percent,
            })
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'avg_lead_time': round(stats['avg_lead_time'] or 0, 1),
            'min_lead_time': stats['min_lead_time'] or 0,
            'max_lead_time': stats['max_lead_time'] or 0,
            'total_bookings': stats['total_bookings'] or 0,
            'buckets': bucket_data,
        }
    
    # =========================================================================
    # FORECAST GENERATION
    # =========================================================================
    
    def get_forecast_summary(self, months_ahead=6):
        """
        Get forecast summary for next N months.
        
        Args:
            months_ahead: Number of months to forecast
        
        Returns:
            List of dicts with forecast data for each month
        """
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        forecasts = []
        
        for i in range(months_ahead):
            target = (today + relativedelta(months=i)).replace(day=1)
            forecast_data = self.generate_forecast(target)
            
            if forecast_data:
                forecasts.append(forecast_data)
        
        return forecasts
    
    def generate_forecast(self, target_month):
        """
        Generate forecast for a specific month.
        
        Returns dict with field names matching template expectations:
        - otb_nights, forecast_nights, vs_stly, confidence, confidence_label, etc.
        """
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        
        # Get current OTB
        otb_data = self.get_otb_for_month(target_month)
        
        otb_room_nights = otb_data['otb_room_nights']
        otb_occupancy = otb_data['otb_occupancy']
        days_out = otb_data['days_out']
        total_available = otb_data['total_available']
        
        # Get season info
        season = self._get_season_for_date(target_month)
        season_type = self._get_season_type(target_month)
        
        # Season name for display
        if season:
            season_name = season.name
        else:
            season_name = season_type.capitalize()
        
        # Get pickup curve for this season
        pickup_curves = self.get_default_pickup_curves()
        curve_data = pickup_curves.get(season_type, pickup_curves['shoulder'])
        
        # Find expected pickup percent at current days_out
        expected_percent = 100.0
        for days, percent in curve_data:
            if days_out >= days:
                expected_percent = percent
                break
        
        # Calculate curve-based forecast
        if expected_percent < 100 and expected_percent > 0:
            curve_forecast = int(otb_room_nights / (expected_percent / 100))
        else:
            curve_forecast = otb_room_nights
        
        # Get STLY data
        stly_data = self.get_stly_otb(target_month)
        stly_room_nights = stly_data['otb_room_nights'] or curve_forecast
        
        # Get velocity trend
        velocity = self.calculate_booking_velocity(target_month)
        velocity_forecast = otb_room_nights
        if days_out > 0 and velocity['room_nights_per_day'] > 0:
            velocity_forecast = otb_room_nights + int(velocity['room_nights_per_day'] * days_out)
        
        # Weighted forecast: 50% curve, 30% STLY, 20% velocity
        forecast_room_nights = int(
            curve_forecast * 0.5 +
            stly_room_nights * 0.3 +
            velocity_forecast * 0.2
        )
        
        # Cap at available
        forecast_room_nights = min(forecast_room_nights, total_available)
        
        # Calculate forecast occupancy
        forecast_occupancy = 0.0
        if total_available > 0:
            forecast_occupancy = round(forecast_room_nights / total_available * 100, 1)
        
        # Calculate pace vs STLY
        pace_variance = otb_room_nights - stly_room_nights
        vs_stly = None
        if stly_room_nights > 0:
            vs_stly = round(pace_variance / stly_room_nights * 100, 1)
        
        # Get scenario occupancy from Season expected_occupancy or OccupancyForecast
        scenario_occupancy = forecast_occupancy  # Default to forecast
        if season and hasattr(season, 'expected_occupancy') and season.expected_occupancy:
            scenario_occupancy = float(season.expected_occupancy)
        else:
            # Try OccupancyForecast
            try:
                from pricing.models import OccupancyForecast
                occ_qs = OccupancyForecast.objects.filter(target_month=target_month)
                if self.property:
                    occ_qs = occ_qs.filter(hotel=self.property)
                occ_forecast = occ_qs.first()
                if occ_forecast and occ_forecast.scenario_occupancy:
                    scenario_occupancy = float(occ_forecast.scenario_occupancy)
            except:
                pass
        
        # Determine confidence level (as percentage and label)
        if days_out <= 14:
            confidence = 85
            confidence_label = 'High'
        elif days_out <= 30:
            confidence = 70
            confidence_label = 'Good'
        elif days_out <= 60:
            confidence = 50
            confidence_label = 'Medium'
        elif days_out <= 90:
            confidence = 35
            confidence_label = 'Low'
        else:
            confidence = 25
            confidence_label = 'Very Low'
        
        return {
            # Month info - 'month' for onclick handler
            'month': target_month,
            'target_month': target_month,
            'month_name': target_month.strftime('%B %Y'),
            'month_short': target_month.strftime('%b'),
            'days_out': days_out,
            
            # Season
            'season_type': season_type,
            'season_name': season_name,
            
            # OTB - FIXED: 'otb_nights' for template
            'otb_nights': otb_room_nights,
            'otb_room_nights': otb_room_nights,
            'otb_occupancy': otb_occupancy,
            'otb_revenue': float(otb_data['otb_revenue']),
            'otb_reservations': otb_data['otb_reservations'],
            'total_available': total_available,
            
            # Forecast - FIXED: 'forecast_nights' for template
            'forecast_nights': forecast_room_nights,
            'forecast_room_nights': forecast_room_nights,
            'forecast_occupancy': forecast_occupancy,
            
            # Scenario - FIXED: added scenario_occupancy
            'scenario_occupancy': scenario_occupancy,
            
            # STLY - FIXED: 'vs_stly' for template (can be None)
            'stly_room_nights': stly_room_nights,
            'vs_stly': vs_stly,
            'vs_stly_pace': vs_stly,
            'pace_variance': pace_variance,
            
            # Confidence - FIXED: number + label
            'confidence': confidence,
            'confidence_label': confidence_label,
            
            # Curve info
            'curve_percent': expected_percent,
            'curve_forecast': curve_forecast,
            
            # Velocity
            'velocity': velocity,
        }
    
    def get_default_pickup_curves(self):
        """
        Get default pickup curves by season type.
        
        Returns:
            Dict with curves for each season type.
            Each curve is a list of (days_out, cumulative_percent) tuples.
        """
        return {
            'peak': [
                (180, 15), (150, 25), (120, 40), (90, 55),
                (60, 70), (45, 80), (30, 88), (14, 95), (7, 98), (0, 100)
            ],
            'high': [
                (180, 10), (150, 18), (120, 30), (90, 45),
                (60, 60), (45, 72), (30, 82), (14, 92), (7, 97), (0, 100)
            ],
            'shoulder': [
                (180, 5), (150, 12), (120, 22), (90, 35),
                (60, 50), (45, 62), (30, 75), (14, 88), (7, 95), (0, 100)
            ],
            'low': [
                (180, 3), (150, 8), (120, 15), (90, 25),
                (60, 40), (45, 52), (30, 65), (14, 82), (7, 92), (0, 100)
            ],
        }
    
    # =========================================================================
    # CHANNEL ANALYSIS
    # =========================================================================
    
    def get_channel_breakdown(self, target_month):
        """
        Get OTB breakdown by channel for a specific month.
        
        Args:
            target_month: First day of target month
        
        Returns:
            List of dicts with channel metrics
        """
        from django.db.models import Sum, Count
        
        # Calculate month boundaries
        year = target_month.year
        month = target_month.month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        
        # Get reservations grouped by channel
        reservations = self._get_reservations_queryset().filter(
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        channel_stats = reservations.values('channel__name').annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            count=Count('id'),
        ).order_by('-room_nights')
        
        total_nights = sum(s['room_nights'] or 0 for s in channel_stats)
        
        result = []
        for stat in channel_stats:
            name = stat['channel__name'] or 'Unknown'
            room_nights = stat['room_nights'] or 0
            percent = round(room_nights / total_nights * 100, 1) if total_nights > 0 else 0
            
            result.append({
                'name': name,
                'room_nights': room_nights,
                'revenue': float(stat['revenue'] or 0),
                'bookings': stat['count'] or 0,
                'percent': percent,
            })
        
        return result
    
"""
Reservation Import Service - Updated for multiple PMS formats and Multi-Property Support.

Supports:
- ABS PMS (Reservation Activity Report, Arrival List)
- Thundi/Biosphere PMS (BookingList export)
- Generic CSV/Excel formats
- Multi-property imports (hotel parameter)
"""

import re
import hashlib
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Tuple, Any

from django.db import transaction
from django.utils import timezone


class ReservationImportService:
    """
    Service for importing reservation data from Excel/CSV files.
    
    Supports multiple PMS formats including:
    - ABS PMS: "Res#", "Arr", "Dept", "Revenue($)"
    - Thundi/Biosphere: "Res #", "Arrival", "Dept", "Total"
    
    Column Mapping handles various naming conventions automatically.
    
    Multi-Property Support:
    - Pass hotel parameter to import_file() to assign reservations to a property
    - If not provided, uses hotel from file_import record
    """
    
    DEFAULT_COLUMN_MAPPING = {
    # =========================================================================
    # CONFIRMATION NUMBER
    # =========================================================================
    'confirmation_no': [
        # ABS / Thundi formats
        'Res #', 'Res#', 'Res. No', 'Res No', 'Res.No',
        'Conf. No', 'Conf No', 'Confirmation', 'Confirmation No', 'ConfNo',
        'Reservation', 'Reservation No', 'Booking No', 'BookingNo',
        # NEW: SynXis Activity Report
        'FXRes#',
        'TPRes#',
        'BookingSr.No',
    ],
    
    # =========================================================================
    # BOOKING DATE
    # =========================================================================
    'booking_date': [
        # ABS / Thundi formats
        'Booking Date', 'Res. Date', 'Res Date', 'Booked On', 
        'Created', 'Book Date', 'Created Date',
        # SynXis format - Status Date is when booking was made/modified
        'BookedDate',
    ],
    
    # Booking time (for Thundi format)
    'booking_time': [
        'Booking Time', 'Time', 'Created Time',
    ],
    
    # =========================================================================
    # ARRIVAL / DEPARTURE
    # =========================================================================
    'arrival_date': [
        # Common formats
        'Arrival', 'Arr',
        'Check In', 'CheckIn', 'Arrival Date', 'Check-In',
        # SynXis format
        'arrival_date',
    ],
    
    'departure_date': [
        # Common formats
        'Dept', 'Departure',
        'Check Out', 'CheckOut', 'Departure Date', 'Check-Out',
        # SynXis format
        'departure_date',
    ],
    
    # =========================================================================
    # NIGHTS
    # =========================================================================
    'nights': [
        'No Of Nights', 'Nights', 'Night', 'LOS', 'Length of Stay',
        'NoOfNights', 'Number of Nights',
    ],
    
    # =========================================================================
    # PAX / OCCUPANCY
    # =========================================================================
    'pax': ['Pax', 'Guests', 'Occupancy'],
    
    'adults': [
        'Adults', 'Adult', 'No of Adults',
        # SynXis format
        'Total Adult Occupancy',
    ],
    
    'children': [
        'Children', 'Child', 'Kids', 'No of Children',
        # SynXis - need special handling to sum child age groups
        'Total Child Occupancy For Age Group1',
    ],
    
    # SynXis child age group columns (for summing)
    'children_group1': ['Total Child Occupancy For Age Group1'],
    'children_group2': ['Total Child Occupancy For Age Group2'],
    'children_group3': ['Total Child Occupancy For Age Group3'],
    'children_group4': ['Total Child Occupancy For Age Group4'],
    'children_group5': ['Total Child Occupancy For Age Group5'],
    'children_unknown': ['Total Child Occupancy For Unknown Age Group'],
    
    # =========================================================================
    # ROOM
    # =========================================================================
    'room_no': [
        # ABS / Thundi formats
        'Room', 'Room No', 'Room Number', 'RoomNo', 
        'Room Type', 'RoomType', 'Room Name',
    ],
    
    # =========================================================================
    # SOURCE / CHANNEL
    # =========================================================================
    'source': [
        # ABS formats
        'Source', 'Business Source',
        # Thundi format
        'Booking Source', 'channel',
        # SynXis format - Secondary Channel has actual OTA name
        'Secondary Channel',
    ],
    
    # SynXis primary channel (SYDC, WEB) - for categorization
    'channel_type': [
        'Channel',
    ],
    
    # SynXis sub-source details
    'sub_source': ['Sub Source'],
    'sub_source_code': ['Sub Source Code'],
    
    # OTA confirmation number
    'ota_confirmation': [
        'Channel Connect Confirm #',
        'OTA Confirmation', 'OTA Conf',
    ],
    
    # =========================================================================
    # USER / AGENT
    # =========================================================================
    'user': ['User', 'Created By', 'Agent', 'Booked By'],
    
    # =========================================================================
    # RATE PLAN
    # =========================================================================
    'rate_plan': [
        # ABS / Thundi formats
        'Rate Type', 'Rate Plan', 'RatePlan', 'Meal Plan', 'Board',
        'Board Type', 'Package',
        # SynXis format
        'Rate Type Code',
        'Rate Category Name',
    ],
    
    # =========================================================================
    # AMOUNTS / PRICING
    # =========================================================================
    'total_amount': [
        # Thundi format
        'Total', 'Grand Total', 'Total Amount',
        # ABS formats
        'Revenue($)', 'Balance Due($)', 'Revenue',
        'Amount', 'Net Amount',
        # SynXis format
        'Cash Paid(Total)',
    ],
    
    'adr': [
        'ADR', 'Average Daily Rate', 'Daily Rate', 'Rate',
        # SynXis format
        'Avg Rate',
    ],
    
    'deposit': [
        'Deposit', 'Deposit Amount', 'Advance',
        # SynXis format
        'Pay at Property',
    ],
    
    'total_charges': ['Total Charges', 'Charges', 'Extra Charges'],
    
    # SynXis pricing details
    'total_adult_price': ['Total Price For Adult'],
    'points_used': ['Points Used(Total)'],
    'cash_refund': ['Cash Refund(Total)'],
    
    # =========================================================================
    # GUEST INFO
    # =========================================================================
    'guest_name': [
        'Guest Name', 'Name', 'Guest', 'Customer', 'Customer Name',
    ],
    
    'country': [
        'Country', 'Nationality', 'Guest Country',
        # SynXis format - 2-letter country codes
        'Guest Location',
    ],
    
    'city': ['City', 'Guest City'],
    'state': ['State', 'Province', 'Guest State'],
    'zip_code': ['Zip Code', 'Postal Code', 'Zip', 'Postcode'],
    'email': ['Email', 'Guest Email', 'E-mail'],
    
    # =========================================================================
    # STATUS
    # =========================================================================
    'status': [
        'Status', 'Booking Status', 'State', 'Res.Type',
        'Reservation Status',
    ],
    
    'reservation_type': [
        'Reservationn Type', 'Reservation Type', 'Res Type',
        'Booking Type',
    ],
    
    # =========================================================================
    # CANCELLATION
    # =========================================================================
    'cancellation_date': [
        'Cancellation Date', 'Cancelled Date', 'Cancel Date',
    ],
    
    # =========================================================================
    # OTHER
    # =========================================================================
    'market_code': ['Market Code', 'Market', 'Segment'],
    'payment_type': ['Payment Type', 'Payment Method', 'Payment'],
    'hotel_name': ['Hotel Name', 'Property', 'Hotel'],
    
    # SynXis specific
    'pms_confirmation': ['PMS Confirmation\nCode', 'PMS Confirmation Code'],
    'rooms_count': ['Rooms'],
    'promotion': ['Promotion'],
    'promo_discount': ['Promo\nDiscount', 'Promo Discount'],
    'loyalty_program': ['Loyalty Program'],
    'loyalty_level': ['Loyalty Level Name'],
}


    # =============================================================================
    # SYNXIS ROOM TYPE MAPPING
    # =============================================================================
    # Maps SynXis room type codes to standard room type names
    # Update these based on your actual room configuration

    SYNXIS_ROOM_TYPE_MAPPING = {
        # Deluxe variants
        'SHDLX001': 'Deluxe Room',
        'SHDLX002': 'Deluxe Room',
        'SHDLX003': 'Deluxe Room',
        'SHDLX004': 'Deluxe Room',
        # Standard
        'SHSTD001': 'Standard Room',
        # Grand
        'SHGRD001': 'Grand Room',
        'SHGRD002': 'Grand Room',
    }


    # =============================================================================
    # SYNXIS RATE PLAN MAPPING
    # =============================================================================
    # Maps SynXis rate type codes to standard rate plan names
    # Update these based on your actual rate plan configuration

    SYNXIS_RATE_PLAN_MAPPING = {
        # Standard OTA rates
        'SHSTROTA001': 'Room Only',
        'SHSTROTA002': 'Room Only',
        # Booking.com rates
        'SHHBBCM': 'Half Board',      # HB Booking.com
        'SHFBBCM': 'Full Board',      # FB Booking.com
        'SHBBWBCM': 'Bed & Breakfast', # BB Booking.com
        # Agoda rates
        'SHHBAGD': 'Half Board',      # HB Agoda
        'SHFBAGD': 'Full Board',      # FB Agoda
        # Expedia rates
        'SHFBEXP': 'Full Board',      # FB Expedia
        # Booking Engine rates
        'SHSTRSBE001': 'Room Only',   # Standard BE
        'SHFBSBE003': 'Full Board',   # FB BE
    }


    # =============================================================================
    # SYNXIS CHANNEL MAPPING
    # =============================================================================
    # Maps SynXis secondary channel values to your channel names

    SYNXIS_CHANNEL_MAPPING = {
        # OTAs
        'Booking.com': 'OTA',
        'Agoda.com': 'OTA',
        'Expedia': 'OTA',
        'Expedia Affiliate Network': 'OTA',
        # Direct
        'Booking Engine': 'Direct',
        'Mobile': 'Direct',
        'Web': 'Direct',
    }
        
    # Status mapping from import values to model choices
    STATUS_MAPPING = {
        'confirmed': [
            'confirmed', 'confirm', 'active', 'booked',
            'confirm booking',  # Thundi format
        ],
        'cancelled': [
            'cancelled', 'canceled', 'cancel', 'void',
        ],
        'checked_in': [
            'checked in', 'checkedin', 'in house', 'inhouse', 'arrived',
        ],
        'checked_out': [
            'checked out', 'checkedout', 'departed', 'completed',
        ],
        'no_show': [
            'no show', 'noshow', 'no-show',
        ],
    }
    
    def __init__(self, column_mapping: Dict = None):
        """
        Initialize import service.
        
        Args:
            column_mapping: Custom column mapping (optional)
        """
        self.column_mapping = column_mapping or self.DEFAULT_COLUMN_MAPPING
        self.errors = []
        self.stats = {
            'rows_total': 0,
            'rows_processed': 0,
            'rows_created': 0,
            'rows_updated': 0,
            'rows_skipped': 0,
        }
        self.hotel = None  # Will be set during import
    
    def import_file(self, file_path: str, file_import=None, hotel=None) -> Dict:
        """
        Import reservations from a file.
        
        Args:
            file_path: Path to Excel or CSV file
            file_import: Optional FileImport record for tracking
            hotel: Optional Property instance to assign to reservations
                   If not provided, uses hotel from file_import
        
        Returns:
            Dict with import results
        """
        from pricing.models import FileImport
        
        file_path = Path(file_path)
        
        # Create or get FileImport record
        if file_import is None:
            file_import = FileImport.objects.create(
                hotel=hotel,
                filename=file_path.name,
                status='processing',
                started_at=timezone.now(),
            )
        else:
            file_import.status = 'processing'
            file_import.started_at = timezone.now()
            file_import.save()
        
        # Determine which hotel to use (parameter takes precedence)
        self.hotel = hotel or file_import.hotel
        
        try:
            # Calculate file hash for duplicate detection
            file_import.file_hash = self._calculate_file_hash(file_path)
            file_import.save()
            
            # Read the file
            df = self._read_file(file_path)
            
            if df is None or df.empty:
                file_import.status = 'failed'
                file_import.errors = [{'row': 0, 'message': 'File is empty or could not be read'}]
                file_import.completed_at = timezone.now()
                file_import.save()
                return self._build_result(file_import)
            
            self.stats['rows_total'] = len(df)
            file_import.rows_total = len(df)
            file_import.save()
            
            # Clean Excel-escaped values (="314" format)
            df = self._clean_excel_escapes(df)
            
            # Map columns
            df = self._map_columns(df)
            
            # Filter out day-use bookings (Nights == 0)
            if 'nights' in df.columns:
                initial_count = len(df)
                df = df[df['nights'].fillna(0).astype(float).astype(int) > 0]
                day_use_filtered = initial_count - len(df)
                
                if day_use_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {day_use_filtered} day-use bookings (Nights=0)'
                    })
            
            # Process rows
            self._process_dataframe(df, file_import)
            
            # Update file import record
            file_import.rows_processed = self.stats['rows_processed']
            file_import.rows_created = self.stats['rows_created']
            file_import.rows_updated = self.stats['rows_updated']
            file_import.rows_skipped = self.stats['rows_skipped']
            file_import.errors = self.errors
            file_import.completed_at = timezone.now()
            
            if self.errors and any(e.get('row', 0) > 0 for e in self.errors):
                file_import.status = 'completed_with_errors'
            else:
                file_import.status = 'completed'
            
            file_import.save()
            
            # Link multi-room bookings after all reservations are imported
            self._link_multi_room_bookings(file_import)
            
            return self._build_result(file_import)
            
        except Exception as e:
            file_import.status = 'failed'
            file_import.errors = [{'row': 0, 'message': str(e)}]
            file_import.completed_at = timezone.now()
            file_import.save()
            raise
    
    def _read_file(self, file_path: Path) -> Optional[pd.DataFrame]:
        """Read Excel or CSV file into DataFrame."""
        suffix = file_path.suffix.lower()
        
        try:
            if suffix in ['.xlsx', '.xls']:
                return pd.read_excel(file_path)
            elif suffix == '.csv':
                # Try different encodings
                for encoding in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        # Use index_col=False to prevent first column being used as index
                        return pd.read_csv(file_path, encoding=encoding, index_col=False)
                    except UnicodeDecodeError:
                        continue
                return pd.read_csv(file_path, encoding='utf-8', errors='replace', index_col=False)
            else:
                self.errors.append({
                    'row': 0,
                    'message': f'Unsupported file format: {suffix}'
                })
                return None
        except Exception as e:
            self.errors.append({
                'row': 0,
                'message': f'Error reading file: {str(e)}'
            })
            return None
    
    def _is_synxis_format(self, df: pd.DataFrame) -> bool:
        """
        Detect if the file is in SynXis format.
        
        SynXis files have distinctive columns like:
        - 'Secondary Channel'
        - 'Channel Connect Confirm #'
        - 'Total Adult Occupancy'
        - 'Rate Type Code'
        
        Returns:
            True if SynXis format detected
        """
        synxis_indicators = [
            'Secondary Channel',
            'Channel Connect Confirm #',
            'Total Adult Occupancy',
            'Rate Type Code',
            'Rate Category Name',
            'Sub Source Code',
        ]
    
        # Check if at least 3 SynXis-specific columns exist
        matches = sum(1 for col in synxis_indicators if col in df.columns)
        return matches >= 3
        
    def _clean_excel_escapes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean Excel-escaped values like ="314" to just 314.
        
        This format is common when exporting from some PMS systems.
        """
        def clean_value(val):
            if pd.isna(val):
                return val
            val_str = str(val).strip()
            # Match pattern: ="value" or ='value'
            match = re.match(r'^[=]?["\'](.+)["\']$', val_str)
            if match:
                return match.group(1)
            return val_str
        
        # Apply to all object (string) columns
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].apply(clean_value)
        
        return df
    
    def _map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map source columns to standard column names."""
        # Create mapping from source column names to standard names
        column_map = {}
        
        # Clean column names (remove trailing spaces, etc.)
        df.columns = [col.strip() for col in df.columns]
        
        for standard_name, possible_names in self.column_mapping.items():
            for col in df.columns:
                col_lower = col.strip().lower()
                if col_lower in [name.lower() for name in possible_names]:
                    column_map[col] = standard_name
                    break
        
        # Rename columns
        df = df.rename(columns=column_map)
        
        # Log unmapped columns
        mapped_cols = set(column_map.values())
        required_cols = {'confirmation_no', 'arrival_date', 'departure_date'}
        missing_required = required_cols - mapped_cols
        
        if missing_required:
            missing_list = ', '.join(sorted(missing_required))
            self.errors.append({
                'row': 0,
                'message': 'Missing required columns: ' + missing_list
            })
        
        return df
    
    def _process_dataframe(self, df: pd.DataFrame, file_import) -> None:
        """Process each row of the DataFrame."""
        from pricing.models import Reservation, RoomType, RatePlan, BookingSource, Guest
        
                # Detect format
        is_synxis = self._is_synxis_format(df)

        if is_synxis:
            self.errors.append({
                'row': 0,
                'message': 'Detected SynXis format - using SynXis-specific processing'
            })
        # Pre-fetch reference data for performance
        # Filter by hotel if set
        if self.hotel:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.filter(hotel=self.hotel)}
        else:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.all()}
        
        rate_plans = {rp.name.lower(): rp for rp in RatePlan.objects.all()}
        
        for i, (idx, row) in enumerate(df.iterrows()):
            row_num = i + 2  # Excel row number (1-indexed + header)
            
            try:
                self._process_row(row, row_num, file_import, room_types, rate_plans)
                self.stats['rows_processed'] += 1
            except Exception as e:
                self.errors.append({
                    'row': row_num,
                    'message': str(e)
                })
                self.stats['rows_skipped'] += 1
    
    def _process_row(self, row: pd.Series, row_num: int, file_import,
                 room_types: Dict, rate_plans: Dict) -> None:
        """Process a single row and create/update reservation."""
        from pricing.models import Reservation, RoomType, RatePlan, BookingSource, Guest
        
        # Extract confirmation number
        raw_conf = str(row.get('confirmation_no', '')).strip()
        if not raw_conf or raw_conf == 'nan':
            self.stats['rows_skipped'] += 1
            return
        
        base_conf, sequence = Reservation.parse_confirmation_no(raw_conf)
        
        # Parse dates
        booking_date = self._parse_date(row.get('booking_date'))
        arrival_date = self._parse_date(row.get('arrival_date'))
        departure_date = self._parse_date(row.get('departure_date'))
        cancellation_date = self._parse_date(row.get('cancellation_date'))
        
        if not arrival_date or not departure_date:
            self.errors.append({
                'row': row_num,
                'message': f'Invalid dates for confirmation {raw_conf}'
            })
            self.stats['rows_skipped'] += 1
            return
        
        # Calculate nights if not provided
        nights = self._parse_int(row.get('nights'))
        if not nights:
            nights = (departure_date - arrival_date).days
        
        # Parse pax (handles "2 \ 0" and "2 / 0" formats)
        adults, children = self._parse_pax(row)
        
        # FIX: Calculate SynXis children (removed erroneous return statement)
        if children == 0:
            synxis_children = self._calculate_synxis_children(row)
            if synxis_children > 0:
                children = synxis_children
        
        # =======================================================================
        # ROOM TYPE HANDLING - with SynXis support
        # =======================================================================
        room_type_raw = str(row.get('room_no', '')).strip()
        
        # Check if this is a SynXis room code
        if room_type_raw.startswith('SH') and len(room_type_raw) >= 7:
            # SynXis format - map the code to standard name
            room_type_name = self._map_synxis_room_type(room_type_raw)
        else:
            # Standard format - extract room type from room field
            room_type_name = room_type_raw
        
        # FIX: Look up the RoomType object by mapped name
        room_type = room_types.get(room_type_name.lower()) if room_type_name else None
        
        # If not found by exact match, try the extract method for non-SynXis
        if room_type is None and not room_type_raw.startswith('SH'):
            room_type, room_type_name = self._extract_room_type(room_type_raw, room_types)
        
        # =======================================================================
        # RATE PLAN HANDLING - with SynXis support
        # =======================================================================
        rate_plan_raw = str(row.get('rate_plan', '')).strip()
        
        # Check if this is a SynXis rate code
        if rate_plan_raw.startswith('SH') and len(rate_plan_raw) >= 6:
            # SynXis format - map the code to standard name
            rate_plan_name = self._map_synxis_rate_plan(rate_plan_raw)
        else:
            # Standard format
            rate_plan_name = rate_plan_raw
        
        # FIX: Look up the RatePlan object by mapped name
        rate_plan = rate_plans.get(rate_plan_name.lower()) if rate_plan_name else None
        
        # If not found by exact match, try the map method for non-SynXis
        if rate_plan is None and not rate_plan_raw.startswith('SH'):
            rate_plan, rate_plan_name = self._map_rate_plan(rate_plan_raw, rate_plans)
        
        # =======================================================================
        # BOOKING SOURCE HANDLING
        # =======================================================================
        source_str = str(row.get('source', '')).strip()
        
        # If source is empty or "PMS", it's likely a direct booking
        if not source_str or source_str == 'nan' or source_str.upper() == 'PMS':
            source_str = 'Direct'
        
        booking_source = BookingSource.find_source(
            source_str,
            str(row.get('user', ''))
        )
        
        if not booking_source:
            booking_source = BookingSource.get_or_create_unknown()
        
        # =======================================================================
        # GUEST HANDLING
        # =======================================================================
        guest_name = str(row.get('guest_name', '')).strip()
        country = str(row.get('country', '')).strip()
        city = str(row.get('city', '')).strip()
        email = str(row.get('email', '')).strip()
        
        if guest_name and guest_name != 'nan':
            guest = Guest.find_or_create(
                name=guest_name,
                country=country if country not in ['nan', '-', ''] else None,
                email=email if email not in ['nan', '-', ''] else None
            )
        else:
            guest = None
        
        # =======================================================================
        # AMOUNTS
        # =======================================================================
        total_amount = self._parse_decimal(row.get('total_amount'))
        adr = self._parse_decimal(row.get('adr'))
        deposit = self._parse_decimal(row.get('deposit'))
        
        # =======================================================================
        # STATUS
        # =======================================================================
        raw_status = str(row.get('status', 'confirmed')).strip()
        status = self._map_status(raw_status)
        
        # If status is Active but there's a cancellation date, it might be cancelled
        if cancellation_date and status == 'confirmed':
            status = 'cancelled'
        
        # Determine if multi-room
        is_multi_room = sequence > 1
        
        # Build raw data for storage
        raw_data = {k: str(v) for k, v in row.items() if pd.notna(v)}
        
        # =======================================================================
        # CREATE OR UPDATE RESERVATION
        # =======================================================================
        with transaction.atomic():
            # Build lookup criteria
            lookup = {
                'confirmation_no': base_conf,
                'room_sequence': sequence,
            }
            
            # If hotel is set, include it in lookup for proper multi-property support
            if self.hotel:
                lookup['hotel'] = self.hotel
            
            # Build defaults
            defaults = {
                'original_confirmation_no': raw_conf,
                'booking_date': booking_date or arrival_date,
                'arrival_date': arrival_date,
                'departure_date': departure_date,
                'nights': nights,
                'adults': adults,
                'children': children,
                'room_type': room_type,
                'room_type_name': room_type_name,
                'rate_plan': rate_plan,
                'rate_plan_name': rate_plan_name,
                'booking_source': booking_source,
                'channel': booking_source.channel if booking_source else None,
                'guest': guest,
                'total_amount': total_amount,
                'status': status,
                'cancellation_date': cancellation_date,
                'is_multi_room': is_multi_room,
                'file_import': file_import,
                'raw_data': raw_data,
            }
            
            # Always set hotel in defaults if we have one
            if self.hotel:
                defaults['hotel'] = self.hotel
            
            reservation, created = Reservation.objects.update_or_create(
                **lookup,
                defaults=defaults
            )
            
            if created:
                self.stats['rows_created'] += 1
            else:
                self.stats['rows_updated'] += 1
            
            # Update guest stats
            if guest:
                guest.update_stats()
    
    def _parse_pax(self, row: pd.Series) -> Tuple[int, int]:
        """
        Parse pax/adults/children from row.
        
        Handles formats:
        - "2 \\ 0" (backslash separator)
        - "2 / 0" (forward slash separator)
        - " 2 / 0" (with leading space)
        - Separate adults/children columns
        
        Returns:
            Tuple of (adults, children)
        """
        # First check for combined pax field
        pax_value = row.get('pax', '')
        
        if pd.notna(pax_value):
            pax_str = str(pax_value).strip()
            
            # Try backslash separator: "2 \ 0" or "2 \\ 0"
            if '\\' in pax_str:
                parts = pax_str.split('\\')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try forward slash separator: "2 / 0"
            if '/' in pax_str:
                parts = pax_str.split('/')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try single number (just adults)
            try:
                adults = int(float(pax_str))
                return (adults, 0)
            except (ValueError, TypeError):
                pass
        
        # Fall back to separate columns
        adults = self._parse_int(row.get('adults'), default=2)
        children = self._parse_int(row.get('children'), default=0)
        
        return (adults, children)
    
    def _extract_room_type(self, room_input: Any, room_types: Dict[str, Any]) -> Tuple[Optional[Any], str]:
        """
        Extracts room type from a 'Room' column.
        
        Handles:
        - "116 Standard" -> "Standard"
        - "Room 101 - Deluxe" -> "Deluxe"
        - "Premium Seaview" -> "Premium Seaview"
        
        Args:
            room_input: The raw value from the 'Room' column.
            room_types: Dict mapping lowercase names to RoomType objects.
            
        Returns:
            Tuple of (Matched Object or None, Extracted String Name)
        """
        # 1. Basic Cleaning
        room_str = str(room_input or '').strip()
        if not room_str or room_str.lower() == 'nan':
            return None, ''
        
        # 2. Extract Name (Removing Room Numbers)
        # Handles "116 Standard" or "116 - Standard"
        # The regex looks for leading digits and optional separators
        match = re.match(r'^\d+[\s\-\:]*(.+)$', room_str)
        if match:
            room_type_name = match.group(1).strip()
        else:
            room_type_name = room_str

        room_type_lower = room_type_name.lower()
        
        # 3. Layered Matching Logic (Waterfall)
        
        # Tier 1: Exact Match
        if room_type_lower in room_types:
            return room_types[room_type_lower], room_type_name
        
        # Tier 2: Substring Matching (Known type inside input OR input inside known type)
        for rt_name, rt_obj in room_types.items():
            if rt_name in room_type_lower or room_type_lower in rt_name:
                return rt_obj, room_type_name
                
        # Tier 3: Keyword Mapping
        # Maps common variations to a root concept
        keywords_map = {
            'standard': ['standard', 'std'],
            'deluxe': ['deluxe', 'premium', 'dlx'],
            'suite': ['suite', 'family', 'executive'],
            'superior': ['superior', 'sup'],
            'villa': ['villa', 'bungalow'],
            'view': ['sea', 'seaview', 'ocean', 'beach', 'garden', 'pool', 'island']
        }
        
        # Identify which keyword groups are present in the input string
        found_groups = {
            group for group, synonyms in keywords_map.items()
            if any(syn in room_type_lower for syn in synonyms)
        }
        
        if found_groups:
            for rt_name, rt_obj in room_types.items():
                # Check if this specific RoomType object matches any of the found keyword groups
                rt_name_lower = rt_name.lower()
                if any(any(syn in rt_name_lower for syn in keywords_map[group]) for group in found_groups):
                    return rt_obj, room_type_name

        # 4. Fallback: No structured match found
        return None, room_type_name
    
    def _map_rate_plan(self, rate_plan_str: str, rate_plans: Dict) -> Tuple[Optional[Any], str]:
        """
        Map rate plan string to RatePlan model.
        
        Returns:
            Tuple of (RatePlan or None, original rate plan name)
        """
        rate_plan_str = str(rate_plan_str or '').strip()
        
        if not rate_plan_str or rate_plan_str == 'nan':
            return None, ''
        
        rate_plan_lower = rate_plan_str.lower()
        
        # Exact match
        if rate_plan_lower in rate_plans:
            return rate_plans[rate_plan_lower], rate_plan_str
        
        # Common abbreviation mappings
        abbreviation_map = {
            'ro': 'room only',
            'bb': 'bed & breakfast',
            'b&b': 'bed & breakfast',
            'bed and breakfast': 'bed & breakfast',
            'hb': 'half board',
            'fb': 'full board',
            'ai': 'all inclusive',
        }
        
        expanded = abbreviation_map.get(rate_plan_lower)
        if expanded and expanded in rate_plans:
            return rate_plans[expanded], rate_plan_str
        
        # Also try the expanded form directly
        if rate_plan_lower in abbreviation_map.values():
            for rp_name, rp in rate_plans.items():
                if rate_plan_lower in rp_name or rp_name in rate_plan_lower:
                    return rp, rate_plan_str
        
        # Partial match
        for rp_name, rp in rate_plans.items():
            if rp_name in rate_plan_lower or rate_plan_lower in rp_name:
                return rp, rate_plan_str
        
        return None, rate_plan_str
    
    def _map_status(self, status_str: str) -> str:
        """Map status string to model choice."""
        status_str = str(status_str or '').strip().lower()
        
        for status_choice, variations in self.STATUS_MAPPING.items():
            if status_str in variations:
                return status_choice
        
        return 'confirmed'  # Default
    
    def _parse_date(self, value) -> Optional[date]:
        """Parse date from various formats including datetime with AM/PM."""
        if pd.isna(value):
            return None
        
        if isinstance(value, (datetime, date)):
            return value.date() if isinstance(value, datetime) else value
        
        value = str(value).strip()
        
        if not value or value == 'nan' or value == '-':
            return None
        
        # Date formats to try - ORDER MATTERS (most specific first)
        formats = [
            # DateTime formats with AM/PM
            '%d-%m-%Y %I:%M:%S %p',    # 19-01-2026 11:31:00 AM
            '%d-%m-%Y %H:%M:%S',       # 19-01-2026 11:31:00
            '%d/%m/%Y %I:%M:%S %p',    # 19/01/2026 11:31:00 AM
            '%d/%m/%Y %H:%M:%S',       # 19/01/2026 11:31:00
            
            # Date-only formats
            '%d-%m-%Y',    # 02-01-2026
            '%d/%m/%Y',    # 02/01/2026
            '%Y-%m-%d',    # 2026-01-02
            '%m/%d/%Y',    # 01/02/2026
            '%Y/%m/%d',    # 2026/01/02
            '%d.%m.%Y',    # 02.01.2026
            '%d %b %Y',    # 02 Jan 2026
            '%d %B %Y',    # 02 January 2026
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.date()
            except ValueError:
                continue
        
        return None
    
    def _parse_int(self, value, default: int = 0) -> int:
        """Parse integer from value."""
        if pd.isna(value):
            return default
        
        try:
            # Handle string values that might have extra characters
            val_str = str(value).strip()
            if not val_str or val_str == 'nan' or val_str == '-':
                return default
            return int(float(val_str))
        except (ValueError, TypeError):
            return default
    
    def _parse_decimal(self, value, default: Decimal = None) -> Decimal:
        """Parse decimal from value."""
        if default is None:
            default = Decimal('0.00')
        
        if pd.isna(value):
            return default
        
        try:
            # Remove currency symbols, commas, and handle negative with prefix
            value_str = str(value).strip()
            
            if not value_str or value_str == 'nan' or value_str == '-':
                return default
            
            # Handle "-0" format
            if value_str == '-0':
                return Decimal('0.00')
            
            value_str = value_str.replace('$', '').replace(',', '').strip()
            return Decimal(value_str).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            return default
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def _link_multi_room_bookings(self, file_import) -> None:
        """
        Link multi-room bookings after import.
        
        Finds reservations with sequence > 1 and links them to sequence 1.
        """
        from pricing.models import Reservation
        
        # Find all reservations with sequence > 1 from this import
        multi_room_qs = Reservation.objects.filter(
            file_import=file_import,
            room_sequence__gt=1
        )
        
        # If hotel is set, also filter by hotel
        if self.hotel:
            multi_room_qs = multi_room_qs.filter(hotel=self.hotel)
        
        for res in multi_room_qs:
            # Find the parent (sequence 1)
            parent_lookup = {
                'confirmation_no': res.confirmation_no,
                'room_sequence': 1
            }
            if self.hotel:
                parent_lookup['hotel'] = self.hotel
            
            parent = Reservation.objects.filter(**parent_lookup).first()
            
            if parent:
                res.parent_reservation = parent
                res.is_multi_room = True
                res.save(update_fields=['parent_reservation', 'is_multi_room'])
                
                # Also mark the parent as multi-room
                if not parent.is_multi_room:
                    parent.is_multi_room = True
                    parent.save(update_fields=['is_multi_room'])
                    
    def _map_synxis_room_type(self, room_code: str) -> str:
        """
        Map SynXis room type code to standard room name.
        
        Args:
            room_code: SynXis room code (e.g., 'SHDLX001')
        
        Returns:
            Standard room name or original code if not mapped
        """
        if not room_code:
            return ''
        
        room_code = str(room_code).strip().upper()
        return self.SYNXIS_ROOM_TYPE_MAPPING.get(room_code, room_code)
    
    def _map_synxis_rate_plan(self, rate_code: str) -> str:
        """
        Map SynXis rate type code to standard rate plan name.
        
        Args:
            rate_code: SynXis rate code (e.g., 'SHHBBCM')
        
        Returns:
            Standard rate plan name or original code if not mapped
        """
        if not rate_code:
            return ''
        
        rate_code = str(rate_code).strip().upper()
        return self.SYNXIS_RATE_PLAN_MAPPING.get(rate_code, rate_code)
    
    def _calculate_synxis_children(self, row: pd.Series) -> int:
        """
        Calculate total children from SynXis age group columns.
        
        SynXis splits children into age groups:
        - Total Child Occupancy For Age Group1
        - Total Child Occupancy For Age Group2
        - Total Child Occupancy For Age Group3
        - Total Child Occupancy For Age Group4
        - Total Child Occupancy For Age Group5
        - Total Child Occupancy For Unknown Age Group
        
        Returns:
            Total children count
        """
        child_columns = [
            'Total Child Occupancy For Age Group1',
            'Total Child Occupancy For Age Group2', 
            'Total Child Occupancy For Age Group3',
            'Total Child Occupancy For Age Group4',
            'Total Child Occupancy For Age Group5',
            'Total Child Occupancy For Unknown Age Group',
            # Also check mapped names
            'children_group1', 'children_group2', 'children_group3',
            'children_group4', 'children_group5', 'children_unknown',
        ]
        
        total_children = 0
        for col in child_columns:
            if col in row.index:
                val = row.get(col)
                if pd.notna(val):
                    try:
                        total_children += int(float(val))
                    except (ValueError, TypeError):
                        pass
        
        return total_children
    
    def _build_result(self, file_import) -> Dict:
        """Build result dictionary from file import."""
        return {
            'success': file_import.status in ['completed', 'completed_with_errors'],
            'file_import_id': file_import.id,
            'filename': file_import.filename,
            'status': file_import.status,
            'rows_total': file_import.rows_total,
            'rows_created': file_import.rows_created,
            'rows_updated': file_import.rows_updated,
            'rows_skipped': file_import.rows_skipped,
            'success_rate': float(file_import.success_rate) if hasattr(file_import, 'success_rate') else 0,
            'errors': file_import.errors,
            'duration_seconds': file_import.duration_seconds if hasattr(file_import, 'duration_seconds') else 0,
        }
    
    def validate_file(self, file_path: str) -> Dict:
        """
        Validate a file before importing.
        
        Checks:
        - File can be read
        - Required columns exist
        - Date formats are valid
        - No duplicate confirmation numbers
        
        Returns:
            Dict with validation results
        """
        file_path = Path(file_path)
        issues = []
        warnings = []
        
        # Check file exists
        if not file_path.exists():
            return {
                'valid': False,
                'issues': [{'message': 'File not found'}],
                'warnings': [],
            }
        
        # Read file
        df = self._read_file(file_path)
        
        if df is None or df.empty:
            return {
                'valid': False,
                'issues': [{'message': 'File is empty or could not be read'}],
                'warnings': [],
            }
        
        # Clean Excel escapes
        df = self._clean_excel_escapes(df)
        
        # Map columns
        df = self._map_columns(df)
        
        # Check required columns
        required = {'confirmation_no', 'arrival_date', 'departure_date'}
        present = set(df.columns)
        missing = required - present
        
        if missing:
            issues.append({
                'message': f'Missing required columns: {missing}'
            })
        
        # Check for day-use bookings
        if 'nights' in df.columns:
            day_use_count = len(df[df['nights'].fillna(0).astype(float).astype(int) == 0])
            if day_use_count > 0:
                warnings.append({
                    'message': f'{day_use_count} day-use bookings will be filtered out'
                })
        
        # Check for cancelled reservations
        if 'status' in df.columns:
            cancelled_count = len(df[df['status'].str.lower().str.contains('cancel', na=False)])
            if cancelled_count > 0:
                warnings.append({
                    'message': f'{cancelled_count} cancelled reservations found'
                })
        
        # Check date validity
        if 'arrival_date' in df.columns:
            invalid_dates = 0
            for val in df['arrival_date'].dropna():
                if self._parse_date(val) is None:
                    invalid_dates += 1
            
            if invalid_dates > 0:
                issues.append({
                    'message': f'{invalid_dates} rows have invalid arrival dates'
                })
        
        # Summary stats
        stats = {
            'total_rows': len(df),
            'columns_found': list(df.columns),
            'date_range': None,
        }
        
        if 'arrival_date' in df.columns:
            dates = [self._parse_date(d) for d in df['arrival_date'].dropna()]
            valid_dates = [d for d in dates if d]
            if valid_dates:
                stats['date_range'] = {
                    'start': min(valid_dates).isoformat(),
                    'end': max(valid_dates).isoformat(),
                }
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'stats': stats,
        }
        

"""
Booking Analysis Service.

Calculates dashboard metrics from Reservation data:
- KPIs (Total Revenue, Room Nights, ADR, Occupancy, Reservations)
- Cancellation Metrics (Count, Rate, Lost Revenue, by Channel)
- Monthly breakdown (Revenue, Room Nights, Available, Occupancy, ADR)
- Channel mix
- Meal plan mix
- Room type performance

Usage:
    from pricing.services.booking_analysis import BookingAnalysisService
    
    # For specific property
    service = BookingAnalysisService(property=prop)
    data = service.get_dashboard_data(year=2026)
    
    # For all properties (legacy)
    service = BookingAnalysisService()
    data = service.get_dashboard_data(year=2026)
"""

from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.db.models.functions import TruncMonth
import calendar


class BookingAnalysisService:
    """
    Service for analyzing booking/reservation data.
    
    Generates metrics for the Booking Analysis Dashboard including
    cancellation analysis.
    
    Supports multi-property filtering via the property parameter.
    """
    
    def __init__(self, property=None):
        """
        Initialize the service.
        
        Args:
            property: Optional Property instance to filter reservations.
                     If None, analyzes all reservations (legacy behavior).
        """
        self.property = property
    
    def _get_base_queryset(self):
        """Get base Reservation queryset with optional property filtering."""
        from pricing.models import Reservation
        
        queryset = Reservation.objects.all()
        
        if self.property:
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def _get_room_types(self):
        """Get RoomType queryset with optional property filtering."""
        from pricing.models import RoomType
        
        queryset = RoomType.objects.all()
        
        if self.property:
            # FIX: RoomType uses 'hotel' field, not 'property'
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def get_dashboard_data(self, year=None, start_date=None, end_date=None, include_cancelled=False):
        """
        Get all dashboard data for a given period.
        
        Args:
            year: Optional year to filter by arrival date (default: current year)
            start_date: Optional start date for custom range
            end_date: Optional end date for custom range
            include_cancelled: If True, include cancelled bookings in main metrics
        
        Returns:
            Dict with all dashboard data
        """
        # Default to current year
        if year is None and start_date is None:
            year = date.today().year
        
        # Build base querysets with property filtering
        base_queryset = self._get_base_queryset()
        
        # ACTIVE bookings (exclude cancelled)
        active_queryset = base_queryset.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        # CANCELLED bookings
        cancelled_queryset = base_queryset.filter(
            status='cancelled'
        )
        
        # ALL bookings
        all_queryset = base_queryset
        
        # Apply date filters
        if start_date and end_date:
            active_queryset = active_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            cancelled_queryset = cancelled_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            all_queryset = all_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
        elif year:
            active_queryset = active_queryset.filter(arrival_date__year=year)
            cancelled_queryset = cancelled_queryset.filter(arrival_date__year=year)
            all_queryset = all_queryset.filter(arrival_date__year=year)
        
        # Get total rooms for occupancy calculation (with property filtering)
        room_types = self._get_room_types()
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 20
        
        # Calculate all metrics
        kpis = self._calculate_kpis(active_queryset, total_rooms, year)
        cancellation_metrics = self._calculate_cancellation_metrics(
            cancelled_queryset, all_queryset, year
        )
        monthly_data = self._calculate_monthly_data(active_queryset, total_rooms, year)
        monthly_cancellations = self._calculate_monthly_cancellations(cancelled_queryset, year)
        channel_mix = self._calculate_channel_mix(active_queryset)
        cancellation_by_channel = self._calculate_cancellation_by_channel(
            cancelled_queryset, all_queryset
        )
        meal_plan_mix = self._calculate_meal_plan_mix(active_queryset)
        room_type_performance = self._calculate_room_type_performance(active_queryset)
        
        return {
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'total_rooms': total_rooms,
            'kpis': kpis,
            'cancellation_metrics': cancellation_metrics,
            'monthly_data': monthly_data,
            'monthly_cancellations': monthly_cancellations,
            'channel_mix': channel_mix,
            'cancellation_by_channel': cancellation_by_channel,
            'meal_plan_mix': meal_plan_mix,
            'room_type_performance': room_type_performance,
        }
    
    def _calculate_kpis(self, queryset, total_rooms, year):
        """
        Calculate KPI card values.
        
        Returns:
            Dict with total_revenue, room_nights, avg_adr, avg_occupancy, reservations
        """
        from django.db.models import Sum, Count
        
        # Aggregate basic stats
        stats = queryset.aggregate(
            total_revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            reservation_count=Count('id'),
        )
        
        total_revenue = stats['total_revenue'] or Decimal('0.00')
        room_nights = stats['room_nights'] or 0
        reservation_count = stats['reservation_count'] or 0
        
        # Calculate ADR
        avg_adr = Decimal('0.00')
        if room_nights > 0:
            avg_adr = (total_revenue / room_nights).quantize(Decimal('0.01'))
        
        # Calculate average occupancy for the year
        if year:
            # Total available room nights for the year
            days_in_year = 366 if calendar.isleap(year) else 365
            total_available = total_rooms * days_in_year
            avg_occupancy = Decimal('0.00')
            if total_available > 0:
                avg_occupancy = (
                    Decimal(str(room_nights)) / Decimal(str(total_available)) * 100
                ).quantize(Decimal('0.1'))
        else:
            avg_occupancy = Decimal('0.0')
        
        return {
            'total_revenue': total_revenue,
            'room_nights': room_nights,
            'avg_adr': avg_adr,
            'avg_occupancy': avg_occupancy,
            'reservations': reservation_count,
        }
    
    def _calculate_cancellation_metrics(self, cancelled_queryset, all_queryset, year):
        """
        Calculate cancellation-specific metrics.
        
        Returns:
            Dict with cancellation count, rate, lost revenue, avg lead time
        """
        from django.db.models import Sum, Count, F
        
        # Count cancelled bookings
        cancelled_stats = cancelled_queryset.aggregate(
            count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        )
        
        # Total bookings (all statuses)
        total_bookings = all_queryset.count()
        
        cancelled_count = cancelled_stats['count'] or 0
        lost_revenue = cancelled_stats['lost_revenue'] or Decimal('0.00')
        lost_room_nights = cancelled_stats['lost_room_nights'] or 0
        
        # Calculate cancellation rate
        cancellation_rate = Decimal('0.0')
        if total_bookings > 0:
            cancellation_rate = (
                Decimal(str(cancelled_count)) / Decimal(str(total_bookings)) * 100
            ).quantize(Decimal('0.1'))
        
        # Calculate average cancellation lead time
        # (days between booking_date and cancellation_date)
        cancellations_with_dates = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            booking_date__isnull=False
        ).annotate(
            lead_time=F('cancellation_date') - F('booking_date')
        )
        
        avg_cancel_lead_time = 0
        if cancellations_with_dates.exists():
            # Calculate average days
            total_days = 0
            count = 0
            for res in cancellations_with_dates:
                if res.lead_time:
                    total_days += res.lead_time.days
                    count += 1
            if count > 0:
                avg_cancel_lead_time = round(total_days / count, 1)
        
        # Calculate average days before arrival when cancelled
        # (days between cancellation_date and arrival_date)
        avg_days_before_arrival = 0
        cancellations_with_arrival = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            arrival_date__isnull=False
        )
        
        if cancellations_with_arrival.exists():
            total_days = 0
            count = 0
            for res in cancellations_with_arrival:
                days_before = (res.arrival_date - res.cancellation_date).days
                if days_before >= 0:  # Only count if cancelled before arrival
                    total_days += days_before
                    count += 1
            if count > 0:
                avg_days_before_arrival = round(total_days / count, 1)
        
        return {
            'count': cancelled_count,
            'rate': cancellation_rate,
            'lost_revenue': lost_revenue,
            'lost_room_nights': lost_room_nights,
            'total_bookings': total_bookings,
            'avg_cancel_lead_time': avg_cancel_lead_time,  # Days after booking
            'avg_days_before_arrival': avg_days_before_arrival,  # Days before arrival
        }
    
    def _calculate_monthly_data(self, queryset, total_rooms, year):
        """
        Calculate monthly breakdown.
        
        Returns:
            List of dicts with month, revenue, room_nights, available, occupancy, adr
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            if year:
                # Calculate available room nights for this month
                days_in_month = calendar.monthrange(year, month_num)[1]
                available = total_rooms * days_in_month
            else:
                available = 0
            
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'month_full': calendar.month_name[month_num],
                'revenue': Decimal('0.00'),
                'room_nights': 0,
                'available': available,
                'occupancy': Decimal('0.0'),
                'adr': Decimal('0.00'),
                'bookings': 0,
            })
        
        # Aggregate by arrival month
        monthly_stats = queryset.values('arrival_date__month').annotate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            revenue = stat['revenue'] or Decimal('0.00')
            room_nights = stat['room_nights'] or 0
            available = monthly_data[month_idx]['available']
            
            monthly_data[month_idx]['revenue'] = revenue
            monthly_data[month_idx]['room_nights'] = room_nights
            monthly_data[month_idx]['bookings'] = stat['bookings']
            
            # Calculate occupancy
            if available > 0:
                monthly_data[month_idx]['occupancy'] = (
                    Decimal(str(room_nights)) / Decimal(str(available)) * 100
                ).quantize(Decimal('0.1'))
            
            # Calculate ADR
            if room_nights > 0:
                monthly_data[month_idx]['adr'] = (
                    revenue / room_nights
                ).quantize(Decimal('0.01'))
        
        return monthly_data
    
    def _calculate_monthly_cancellations(self, cancelled_queryset, year):
        """
        Calculate monthly cancellation breakdown.
        
        Returns:
            List of dicts with month, cancelled_count, lost_revenue, lost_room_nights
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'cancelled_count': 0,
                'lost_revenue': Decimal('0.00'),
                'lost_room_nights': 0,
            })
        
        # Aggregate cancellations by arrival month
        monthly_stats = cancelled_queryset.values('arrival_date__month').annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            monthly_data[month_idx]['cancelled_count'] = stat['cancelled_count'] or 0
            monthly_data[month_idx]['lost_revenue'] = stat['lost_revenue'] or Decimal('0.00')
            monthly_data[month_idx]['lost_room_nights'] = stat['lost_room_nights'] or 0
        
        return monthly_data
    
    def _calculate_channel_mix(self, queryset):
        """
        Calculate channel/source breakdown.
        
        Returns:
            List of dicts with channel, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Try to group by channel first
        channel_stats = queryset.values(
            'channel__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no channel data, try booking_source
        if not channel_stats.exists() or all(s['channel__name'] is None for s in channel_stats):
            channel_stats = queryset.values(
                'booking_source__name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'booking_source__name'
        else:
            name_field = 'channel__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in channel_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return channel_data
    
    def _calculate_cancellation_by_channel(self, cancelled_queryset, all_queryset):
        """
        Calculate cancellation rate by channel.
        
        Returns:
            List of dicts with channel, cancelled_count, total_count, rate, lost_revenue
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Get cancelled by channel
        cancelled_by_channel = cancelled_queryset.values(
            'channel__name'
        ).annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('-cancelled_count')
        
        # Get total by channel
        total_by_channel = all_queryset.values(
            'channel__name'
        ).annotate(
            total_count=Count('id'),
        )
        
        # Build lookup for totals
        total_lookup = {
            stat['channel__name']: stat['total_count'] 
            for stat in total_by_channel
        }
        
        for stat in cancelled_by_channel:
            name = stat.get('channel__name') or 'Unknown'
            cancelled_count = stat['cancelled_count'] or 0
            total_count = total_lookup.get(name, cancelled_count)
            
            # Calculate cancellation rate for this channel
            rate = Decimal('0.0')
            if total_count > 0:
                rate = (
                    Decimal(str(cancelled_count)) / Decimal(str(total_count)) * 100
                ).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'cancelled_count': cancelled_count,
                'total_count': total_count,
                'rate': rate,
                'lost_revenue': stat['lost_revenue'] or Decimal('0.00'),
                'lost_room_nights': stat['lost_room_nights'] or 0,
            })
        
        # Sort by cancellation rate (highest first)
        channel_data.sort(key=lambda x: x['rate'], reverse=True)
        
        return channel_data
    
    def _calculate_meal_plan_mix(self, queryset):
        """
        Calculate meal plan/rate plan breakdown.
        
        Returns:
            List of dicts with meal_plan, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        meal_plan_data = []
        
        # Group by rate_plan
        plan_stats = queryset.values(
            'rate_plan__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no rate_plan data, try rate_plan_name
        if not plan_stats.exists() or all(s['rate_plan__name'] is None for s in plan_stats):
            plan_stats = queryset.values(
                'rate_plan_name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'rate_plan_name'
        else:
            name_field = 'rate_plan__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in plan_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            meal_plan_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return meal_plan_data
    
    def _calculate_room_type_performance(self, queryset):
        """
        Calculate room type breakdown.
        
        Groups by room_type FK if available, otherwise by room_type_name.
        
        Returns:
            List of dicts with room_type, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        room_type_data = []
        
        # First, try to get stats for reservations WITH room_type FK
        rt_stats_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # Then, get stats for reservations WITHOUT room_type FK (use room_type_name)
        rt_stats_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        # Combine results - first from FK, then from name
        seen_names = set()
        
        for stat in rt_stats_fk:
            name = stat.get('room_type__name') or 'Unknown'
            if name in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        for stat in rt_stats_name:
            name = stat.get('room_type_name') or 'Unknown'
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        # Sort by revenue descending
        room_type_data.sort(key=lambda x: x['revenue'], reverse=True)
        
        return room_type_data
    
    def get_chart_data(self, year=None):
        """
        Get data formatted for Chart.js charts.
        
        Returns:
            Dict with chart-ready data (lists for labels, values, etc.)
            All Decimal values are converted to float for JSON serialization.
        """
        dashboard_data = self.get_dashboard_data(year=year)
        monthly = dashboard_data['monthly_data']
        monthly_cancel = dashboard_data['monthly_cancellations']
        
        # Helper to convert Decimal to float
        def to_float(val):
            if isinstance(val, Decimal):
                return float(val)
            return val
        
        # Convert KPIs to JSON-safe format
        kpis_safe = {
            'total_revenue': to_float(dashboard_data['kpis']['total_revenue']),
            'room_nights': dashboard_data['kpis']['room_nights'],
            'avg_adr': to_float(dashboard_data['kpis']['avg_adr']),
            'avg_occupancy': to_float(dashboard_data['kpis']['avg_occupancy']),
            'reservations': dashboard_data['kpis']['reservations'],
        }
        
        # Convert cancellation metrics to JSON-safe format
        cancel_metrics_safe = {
            'count': dashboard_data['cancellation_metrics']['count'],
            'rate': to_float(dashboard_data['cancellation_metrics']['rate']),
            'lost_revenue': to_float(dashboard_data['cancellation_metrics']['lost_revenue']),
            'lost_room_nights': dashboard_data['cancellation_metrics']['lost_room_nights'],
            'total_bookings': dashboard_data['cancellation_metrics']['total_bookings'],
            'avg_cancel_lead_time': dashboard_data['cancellation_metrics']['avg_cancel_lead_time'],
            'avg_days_before_arrival': dashboard_data['cancellation_metrics']['avg_days_before_arrival'],
        }
        
        return {
            # Monthly metrics
            'months': [m['month_name'] for m in monthly],
            'revenue': [float(m['revenue']) for m in monthly],
            'room_nights': [m['room_nights'] for m in monthly],
            'available': [m['available'] for m in monthly],
            'occupancy': [float(m['occupancy']) for m in monthly],
            'adr': [float(m['adr']) for m in monthly],
            'bookings': [m['bookings'] for m in monthly],
            
            # Cancellation metrics
            'cancelled_count': [m['cancelled_count'] for m in monthly_cancel],
            'lost_revenue': [float(m['lost_revenue']) for m in monthly_cancel],
            'lost_room_nights': [m['lost_room_nights'] for m in monthly_cancel],
            
            # Channel mix
            'channel_labels': [c['name'] for c in dashboard_data['channel_mix']],
            'channel_values': [float(c['revenue']) for c in dashboard_data['channel_mix']],
            'channel_percents': [float(c['percent']) for c in dashboard_data['channel_mix']],
            
            # Cancellation by channel
            'cancel_channel_labels': [c['name'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_counts': [c['cancelled_count'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_rates': [float(c['rate']) for c in dashboard_data['cancellation_by_channel']],
            
            # Meal plan mix
            'meal_plan_labels': [m['name'] for m in dashboard_data['meal_plan_mix']],
            'meal_plan_values': [float(m['revenue']) for m in dashboard_data['meal_plan_mix']],
            'meal_plan_percents': [float(m['percent']) for m in dashboard_data['meal_plan_mix']],
            
            # KPIs for display (JSON-safe)
            'kpis': kpis_safe,
            'cancellation_metrics': cancel_metrics_safe,
        }
    
    def get_net_pickup(self, start_date=None, end_date=None, days=30):
        """
        Calculate net pickup (new bookings - cancellations) for a period.
        
        Args:
            start_date: Start of period (default: days ago)
            end_date: End of period (default: today)
            days: Number of days to look back (default: 30)
        
        Returns:
            Dict with gross_bookings, cancellations, net_bookings, net_revenue
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=days)
        
        # Use property-filtered base queryset
        base_queryset = self._get_base_queryset()
        
        # New bookings created in this period
        new_bookings = base_queryset.filter(
            booking_date__gte=start_date,
            booking_date__lte=end_date
        ).exclude(status='cancelled')
        
        from django.db.models import Sum, Count
        
        new_stats = new_bookings.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        # Cancellations in this period
        cancellations = base_queryset.filter(
            cancellation_date__gte=start_date,
            cancellation_date__lte=end_date,
            status='cancelled'
        )
        
        cancel_stats = cancellations.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        gross_bookings = new_stats['count'] or 0
        gross_revenue = new_stats['revenue'] or Decimal('0.00')
        gross_room_nights = new_stats['room_nights'] or 0
        
        cancelled_count = cancel_stats['count'] or 0
        cancelled_revenue = cancel_stats['revenue'] or Decimal('0.00')
        cancelled_room_nights = cancel_stats['room_nights'] or 0
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'gross_bookings': gross_bookings,
            'gross_revenue': gross_revenue,
            'gross_room_nights': gross_room_nights,
            'cancellations': cancelled_count,
            'cancelled_revenue': cancelled_revenue,
            'cancelled_room_nights': cancelled_room_nights,
            'net_bookings': gross_bookings - cancelled_count,
            'net_revenue': gross_revenue - cancelled_revenue,
            'net_room_nights': gross_room_nights - cancelled_room_nights,
        }
        
    def get_month_detail(self, year, month):
        """
        Get detailed analysis for a specific arrival month.
        
        Args:
            year: Arrival year
            month: Arrival month (1-12)
        
        Returns:
            Dict with summary, velocity, room_distribution, lead_time, 
            channel_distribution, country_distribution
        """
        from django.db.models import Sum, Count, Avg, F
        from django.db.models.functions import TruncMonth
        
        # Base queryset for this arrival month
        base_qs = self._get_base_queryset().filter(
            arrival_date__year=year,
            arrival_date__month=month
        )
        
        # Active bookings only for summary
        active_qs = base_qs.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        # Get room types for available calculation
        room_types = self._get_room_types()
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 1
        days_in_month = calendar.monthrange(year, month)[1]
        available = total_rooms * days_in_month
        
        # ===================
        # SUMMARY
        # ===================
        summary_stats = active_qs.aggregate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id')
        )
        
        revenue = float(summary_stats['revenue'] or 0)
        room_nights = summary_stats['room_nights'] or 0
        adr = revenue / room_nights if room_nights > 0 else 0
        occupancy = (room_nights / available * 100) if available > 0 else 0
        
        summary = {
            'revenue': revenue,
            'room_nights': room_nights,
            'occupancy': occupancy,
            'adr': adr,
            'bookings': summary_stats['bookings'] or 0,
            'available': available,
        }
        
        # ===================
        # BOOKING VELOCITY
        # ===================
        velocity = self._get_velocity_for_month(base_qs, year, month)
        
        # ===================
        # ROOM DISTRIBUTION
        # ===================
        room_distribution = self._get_room_distribution_detail(active_qs)
        
        # ===================
        # LEAD TIME DISTRIBUTION
        # ===================
        lead_time = self._get_lead_time_distribution_detail(active_qs)
        
        # ===================
        # CHANNEL DISTRIBUTION
        # ===================
        channel_distribution = self._get_channel_distribution_detail(active_qs)
        
        # ===================
        # COUNTRY DISTRIBUTION
        # ===================
        country_distribution = self._get_country_distribution(active_qs)
        
        return {
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'summary': summary,
            'velocity': velocity,
            'room_distribution': room_distribution,
            'lead_time': lead_time,
            'channel_distribution': channel_distribution,
            'country_distribution': country_distribution,
        }

    def _get_velocity_for_month(self, base_qs, year, month):
        """
        Get booking velocity for a specific arrival month.
        
        IMPORTANT: This now calculates properly so cumulative matches final OTB:
        - New RN: Only counts ACTIVE bookings created in that month
        - Lost RN: Cancelled/Void/NoShow bookings created in that month
        - Net Pickup: New - Lost
        - Cumulative: Running total = Final Active OTB
        """
        from django.db.models import Sum, Count
        from django.db.models.functions import TruncMonth
        
        # Active statuses
        active_statuses = ['confirmed', 'checked_in', 'checked_out']
        # Lost statuses (cancelled, void, no_show)
        lost_statuses = ['cancelled', 'void', 'no_show']
        
        # Get ACTIVE bookings grouped by booking month
        active_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=active_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            new_bookings=Count('id'),
            new_nights=Sum('nights'),
        ).order_by('bm')
        
        # Get LOST bookings (cancelled/void/no_show) grouped by booking month
        lost_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=lost_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            lost_bookings=Count('id'),
            lost_nights=Sum('nights'),
        ).order_by('bm')
        
        # Build lookups
        active_lookup = {a['bm']: a for a in active_bookings}
        lost_lookup = {l['bm']: l for l in lost_bookings}
        
        # Get all booking months
        all_months = sorted(set(
            list(active_lookup.keys()) + list(lost_lookup.keys())
        ))
        
        # Build velocity data
        velocity = []
        for bm in all_months:
            active_data = active_lookup.get(bm, {})
            lost_data = lost_lookup.get(bm, {})
            
            new_nights = active_data.get('new_nights', 0) or 0
            lost_nights = lost_data.get('lost_nights', 0) or 0
            
            velocity.append({
                'booking_month': bm.strftime('%b %Y') if bm else 'Unknown',
                'new_bookings': active_data.get('new_bookings', 0) or 0,
                'new_nights': new_nights,
                'cancellations': lost_data.get('lost_bookings', 0) or 0,
                'cancelled_nights': lost_nights,
                'net_pickup': new_nights,  # Only active bookings count
            })
        
        return velocity

    def _get_room_distribution_detail(self, queryset):
        """Get room night distribution by room type for month detail."""
        from django.db.models import Sum, Count
        
        # Try room_type FK first
        by_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        # Then try room_type_name
        by_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        seen = set()
        
        for row in by_fk:
            name = row['room_type__name'] or 'Unknown'
            if name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        for row in by_name:
            name = row['room_type_name'] or 'Unknown'
            if name and name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_lead_time_distribution_detail(self, queryset):
        """Get lead time distribution (days between booking and arrival)."""
        from django.db.models import F
        
        # Get bookings with lead time calculated
        bookings_with_lead = queryset.filter(
            booking_date__isnull=False,
            arrival_date__isnull=False
        )
        
        # Define buckets
        buckets = [
            ('0-7 days', 0, 7),
            ('8-14 days', 8, 14),
            ('15-30 days', 15, 30),
            ('31-60 days', 31, 60),
            ('61-90 days', 61, 90),
            ('90+ days', 91, 9999),
        ]
        
        distribution = []
        
        for label, min_days, max_days in buckets:
            bucket_data = {
                'bookings': 0,
                'room_nights': 0,
                'revenue': Decimal('0.00'),
            }
            
            for booking in bookings_with_lead:
                if booking.booking_date and booking.arrival_date:
                    days = (booking.arrival_date - booking.booking_date).days
                    if min_days <= days <= max_days:
                        bucket_data['bookings'] += 1
                        bucket_data['room_nights'] += booking.nights or 0
                        bucket_data['revenue'] += booking.total_amount or Decimal('0.00')
            
            avg_adr = 0
            if bucket_data['room_nights'] > 0:
                avg_adr = float(bucket_data['revenue']) / bucket_data['room_nights']
            
            distribution.append({
                'bucket': label,
                'bookings': bucket_data['bookings'],
                'room_nights': bucket_data['room_nights'],
                'revenue': float(bucket_data['revenue']),
                'avg_adr': avg_adr,
            })
        
        return distribution

    def _get_channel_distribution_detail(self, queryset):
        """Get distribution by booking channel for month detail."""
        from django.db.models import Sum, Count
        
        # Try channel FK first
        by_channel = queryset.values(
            'channel__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        for row in by_channel:
            name = row['channel__name'] or 'Direct/Unknown'
            distribution.append({
                'channel': name,
                'room_nights': row['room_nights'] or 0,
                'revenue': float(row['revenue'] or 0),
                'bookings': row['bookings'] or 0,
            })
        
        # If no channel data, try booking_source
        if not distribution or all(d['channel'] == 'Direct/Unknown' for d in distribution):
            by_source = queryset.values(
                'booking_source__name'
            ).annotate(
                room_nights=Sum('nights'),
                revenue=Sum('total_amount'),
                bookings=Count('id')
            ).order_by('-room_nights')
            
            distribution = []
            for row in by_source:
                name = row['booking_source__name'] or 'Unknown'
                distribution.append({
                    'channel': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_country_distribution(self, queryset):
        """Get distribution by guest country."""
        from django.db.models import Sum, Count
        
        by_country = queryset.exclude(
            guest__country__isnull=True
        ).exclude(
            guest__country=''
        ).exclude(
            guest__country='-'
        ).values(
            'guest__country'
        ).annotate(
            room_nights=Sum('nights'),
            bookings=Count('id')
        ).order_by('-room_nights')[:10]  # Top 10 countries
        
        distribution = []
        for row in by_country:
            country = row['guest__country'] or 'Unknown'
            distribution.append({
                'country': country,
                'room_nights': row['room_nights'] or 0,
                'bookings': row['bookings'] or 0,
            })
        
        # If no guest country data, return placeholder
        if not distribution:
            distribution = [{'country': 'Unknown', 'room_nights': 0, 'bookings': 0}]
        
        return distribution