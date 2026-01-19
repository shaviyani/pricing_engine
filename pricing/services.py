

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
import calendar


"""
Pricing calculation services.

Three-step calculation process:
1. Base Rate × Season Index = Seasonal Rate
2. Seasonal Rate + (Meal Supplement × Occupancy) = Rate Plan Price
3. Rate Plan Price × (1 - Discount%) = Final Channel Rate
"""
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


def calculate_final_rate(room_base_rate, season_index, meal_supplement, 
                        discount_percent, occupancy=2):
    """
    Master calculator - combines all three steps (LEGACY - for backward compatibility).
    
    Args:
        room_base_rate: Decimal - Base rate for the room
        season_index: Decimal - Season multiplier
        meal_supplement: Decimal - Meal cost per person
        discount_percent: Decimal - Channel discount percentage
        occupancy: int - Number of people (default 2)
    
    Returns:
        tuple: (final_rate, breakdown_dict)
    
    Example:
        rate, breakdown = calculate_final_rate(
            Decimal('65.00'), 
            Decimal('1.30'), 
            Decimal('6.00'), 
            Decimal('15.00'),
            2
        )
        >>> rate = Decimal('82.03')
        >>> breakdown = {
                'base_rate': Decimal('65.00'),
                'season_index': Decimal('1.30'),
                'seasonal_rate': Decimal('84.50'),
                'meal_supplement_per_person': Decimal('6.00'),
                'occupancy': 2,
                'meal_cost': Decimal('12.00'),
                'rate_plan_price': Decimal('96.50'),
                'discount_percent': Decimal('15.00'),
                'discount_amount': Decimal('14.47'),
                'final_rate': Decimal('82.03'),
            }
    """
    # Step 1: Calculate seasonal rate
    seasonal_rate = calculate_seasonal_rate(room_base_rate, season_index)
    
    # Step 2: Calculate rate plan price with meals
    meal_cost = meal_supplement * occupancy
    rate_plan_price = calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy)
    
    # Step 3: Apply channel discount
    final_rate = calculate_channel_rate(rate_plan_price, discount_percent)
    
    # Calculate discount amount
    discount_amount = rate_plan_price - final_rate
    
    # Build breakdown for display/debugging
    breakdown = {
        'base_rate': room_base_rate,
        'season_index': season_index,
        'seasonal_rate': seasonal_rate,
        'meal_supplement_per_person': meal_supplement,
        'occupancy': occupancy,
        'meal_cost': meal_cost,
        'rate_plan_price': rate_plan_price,
        'discount_percent': discount_percent,
        'discount_amount': discount_amount,
        'final_rate': final_rate,
    }
    
    return final_rate, breakdown


def calculate_final_rate_with_modifier(room_base_rate, season_index, meal_supplement, 
                                       channel_base_discount, modifier_discount=Decimal('0.00'),
                                       commission_percent=Decimal('0.00'), occupancy=2):
    """
    Enhanced calculator with BAR, channel base discount, and rate modifier support.
    
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
    
    Example:
        # OTA Genius Member Rate
        rate, breakdown = calculate_final_rate_with_modifier(
            room_base_rate=Decimal('65.00'),
            season_index=Decimal('1.30'),
            meal_supplement=Decimal('6.00'),
            channel_base_discount=Decimal('0.00'),  # OTA has no base discount
            modifier_discount=Decimal('10.00'),     # Genius gets 10% off
            commission_percent=Decimal('18.00'),    # OTA takes 18% commission
            occupancy=2
        )
        >>> rate = Decimal('86.85')  # Guest pays this
        >>> breakdown['net_revenue'] = Decimal('71.22')  # You receive this
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


def format_currency(amount, currency_symbol='$'):
    """
    Format Decimal amount as currency string.
    
    Args:
        amount: Decimal - Amount to format
        currency_symbol: str - Currency symbol (default '$')
    
    Returns:
        str - Formatted currency string
    
    Example:
        format_currency(Decimal('82.03'))
        >>> '$82.03'
    """
    return f"{currency_symbol}{amount:,.2f}"


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
    """
    
    def __init__(self):
        """Initialize forecast service."""
        pass
    
    def calculate_seasonal_forecast(self):
        """
        Calculate revenue forecast by season with channel breakdown.
        
        Returns:
            list of dicts with season data
        """
        from pricing.models import Season, RoomType
        
        seasons = Season.objects.all().order_by('start_date')
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        
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
        
        🐛 FIX: Now properly handles seasons that span across years
        (e.g., Peak Season: Dec 2025 → Jan 2026)
        
        Args:
            year: Optional year (defaults to current calendar year if most seasons are in it)
        
        Returns:
            list of dicts with monthly data
        """
        from pricing.models import Season, RoomType
        
        seasons = Season.objects.all().order_by('start_date')
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        
        if not seasons.exists() or total_rooms == 0:
            return []
        
        # 🔧 FIX: Determine the main year based on where most season days fall
        if year is None:
            # Count days per year across all seasons
            year_days = defaultdict(int)
            for season in seasons:
                current_date = season.start_date
                while current_date <= season.end_date:
                    year_days[current_date.year] += 1
                    current_date += timedelta(days=1)
            
            # Use the year with the most days
            year = max(year_days.items(), key=lambda x: x[1])[0] if year_days else seasons.first().start_date.year
        
        monthly_data = []
        
        # Iterate through all 12 months of the target year
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
        """
        Calculate revenue for a specific season.
        
        Args:
            season: Season object
            total_rooms: Total number of rooms across all room types
        
        Returns:
            dict with season revenue breakdown
        """
        from pricing.models import Channel
        
        # Calculate basic metrics
        days = (season.end_date - season.start_date).days + 1
        available_room_nights = total_rooms * days
        occupancy_rate = season.expected_occupancy / Decimal('100.00')
        occupied_room_nights = int(available_room_nights * occupancy_rate)
        
        # Get channel distribution
        channels = Channel.objects.all()
        channel_breakdown = []
        
        total_gross_revenue = Decimal('0.00')
        total_net_revenue = Decimal('0.00')
        total_commission = Decimal('0.00')
        total_weighted_room_nights = 0
        
        for channel in channels:
            if channel.distribution_share_percent == 0:
                continue
            
            # Calculate channel's share of room nights
            channel_share = channel.distribution_share_percent / Decimal('100.00')
            channel_room_nights = int(occupied_room_nights * channel_share)
            
            if channel_room_nights == 0:
                continue
            
            # Calculate channel ADR (average across all room types, rate plans, modifiers)
            channel_adr = self._calculate_channel_adr(channel, season)
            
            # Calculate revenues
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
        
        # Calculate weighted ADR
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
    
    def calculate_occupancy_forecast(self, year=None):
        """
        Calculate monthly occupancy forecast.
        
        Uses the same logic as calculate_monthly_forecast but focuses on
        occupancy metrics rather than revenue.
        
        Args:
            year: Optional year (defaults to main season year)
        
        Returns:
            dict with:
            - monthly_data: List of monthly occupancy info
            - annual_metrics: Annual occupancy KPIs
            - seasonal_data: Occupancy breakdown by season
        """
        from pricing.models import Season, RoomType
        
        seasons = Season.objects.all().order_by('start_date')
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        
        if not seasons.exists() or total_rooms == 0:
            return None
        
        # Get monthly forecast data (already has occupancy info)
        monthly_forecast = self.calculate_monthly_forecast(year)
        
        if not monthly_forecast:
            return None
        
        # Extract monthly occupancy data
        monthly_data = []
        total_available_nights = 0
        total_occupied_nights = 0
        occupancy_days_80_plus = 0
        
        for month in monthly_forecast:
            monthly_data.append({
                'month': month['month'],
                'month_name': month['month_name'][:3],  # Short name (Jan, Feb, etc.)
                'occupancy_percent': float(month['occupancy_percent']),
                'available_room_nights': month['available_room_nights'],
                'occupied_room_nights': month['occupied_room_nights'],
                'days': month['days'],
            })
            
            total_available_nights += month['available_room_nights']
            total_occupied_nights += month['occupied_room_nights']
            
            # Count days with 80%+ occupancy
            if month['occupancy_percent'] >= Decimal('80.00'):
                occupancy_days_80_plus += month['days']
        
        # Calculate annual metrics
        annual_occupancy = (
            Decimal(str(total_occupied_nights)) / Decimal(str(total_available_nights)) * Decimal('100.00')
            if total_available_nights > 0 else Decimal('0.00')
        )
        
        # Find peak and low months
        peak_month = max(monthly_data, key=lambda x: x['occupancy_percent'])
        low_month = min(monthly_data, key=lambda x: x['occupancy_percent'])
        
        # Calculate seasonal occupancy breakdown
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
        
    def _calculate_month_revenue(self, month_start, month_end, seasons, total_rooms):
        """
        Calculate revenue for a specific month.
        
        A month may overlap with multiple seasons, so we proportion the revenue
        based on how many days of each season fall within the month.
        
        Args:
            month_start: date object (first day of month)
            month_end: date object (last day of month)
            seasons: QuerySet of Season objects
            total_rooms: Total number of rooms
        
        Returns:
            dict with monthly revenue breakdown
        """
        days_in_month = (month_end - month_start).days + 1
        
        # Find overlapping seasons and calculate their contribution
        month_revenue = Decimal('0.00')
        month_gross = Decimal('0.00')
        month_commission = Decimal('0.00')
        month_room_nights = 0
        channel_contributions = defaultdict(lambda: {
            'room_nights': 0,
            'gross_revenue': Decimal('0.00'),
            'commission': Decimal('0.00'),
            'net_revenue': Decimal('0.00'),
        })
        
        for season in seasons:
            # Check if season overlaps with this month
            overlap_start = max(month_start, season.start_date)
            overlap_end = min(month_end, season.end_date)
            
            if overlap_start <= overlap_end:
                # Calculate days of overlap
                overlap_days = (overlap_end - overlap_start).days + 1
                
                # Get season revenue data
                season_data = self._calculate_season_revenue(season, total_rooms)
                
                # Proportion revenue by overlap days
                proportion = Decimal(str(overlap_days)) / Decimal(str(season_data['days']))
                
                # Add proportional contribution
                month_gross += season_data['gross_revenue'] * proportion
                month_commission += season_data['commission_amount'] * proportion
                month_revenue += season_data['net_revenue'] * proportion
                month_room_nights += int(season_data['occupied_room_nights'] * proportion)
                
                # Proportional channel breakdown
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
        
        # Build channel breakdown
        from pricing.models import Channel
        channel_breakdown = []
        for channel in Channel.objects.all():
            if channel.id in channel_contributions:
                contrib = channel_contributions[channel.id]
                channel_breakdown.append({
                    'channel': channel,
                    'share_percent': channel.distribution_share_percent,
                    'room_nights': contrib['room_nights'],
                    'gross_revenue': contrib['gross_revenue'],
                    'commission_amount': contrib['commission'],
                    'net_revenue': contrib['net_revenue'],
                })
        
        # Calculate metrics
        available_room_nights = total_rooms * days_in_month
        occupancy_percent = (
            Decimal(str(month_room_nights)) / Decimal(str(available_room_nights)) * Decimal('100.00')
            if available_room_nights > 0 else Decimal('0.00')
        )
        weighted_adr = (
            month_gross / Decimal(str(month_room_nights))
            if month_room_nights > 0 else Decimal('0.00')
        )
        
        return {
            'month': month_start.month,
            'month_name': month_start.strftime('%B %Y'),
            'year': month_start.year,
            'days': days_in_month,
            'available_room_nights': available_room_nights,
            'occupied_room_nights': month_room_nights,
            'occupancy_percent': occupancy_percent,
            'weighted_adr': weighted_adr,
            'gross_revenue': month_gross,
            'commission_amount': month_commission,
            'net_revenue': month_revenue,
            'channel_breakdown': channel_breakdown,
        }
    
    def _calculate_channel_adr(self, channel, season):
        """
        Calculate average daily rate (ADR) for a channel in a season.
        
        This is the average rate across:
        - All room types (weighted by number_of_rooms)
        - All rate plans (equal weight)
        - All active rate modifiers for this channel (equal weight)
        
        Args:
            channel: Channel object
            season: Season object
        
        Returns:
            Decimal: Weighted ADR for the channel
        """
        from pricing.models import RoomType, RatePlan, RateModifier
        from pricing.services import calculate_final_rate_with_modifier
        
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        modifiers = RateModifier.objects.filter(channel=channel, active=True)
        
        if not all([rooms.exists(), rate_plans.exists(), modifiers.exists()]):
            return Decimal('0.00')
        
        total_rate = Decimal('0.00')
        total_weight = 0
        
        for room in rooms:
            room_weight = room.number_of_rooms  # Weight by inventory
            
            for rate_plan in rate_plans:
                for modifier in modifiers:
                    # Get season-specific discount
                    season_discount = modifier.get_discount_for_season(season)
                    
                    # Calculate final rate
                    final_rate, _ = calculate_final_rate_with_modifier(
                        room_base_rate=room.get_effective_base_rate(),
                        season_index=season.season_index,
                        meal_supplement=rate_plan.meal_supplement,
                        channel_base_discount=channel.base_discount_percent,
                        modifier_discount=season_discount,
                        commission_percent=channel.commission_percent,
                        occupancy=2
                    )
                    
                    total_rate += final_rate * room_weight
                    total_weight += room_weight
        
        return (total_rate / total_weight).quantize(Decimal('0.01')) if total_weight > 0 else Decimal('0.00')
    
    def validate_channel_distribution(self):
        """
        Validate that channel distribution percentages total 100%.
        
        Returns:
            tuple: (is_valid: bool, total_percent: Decimal, message: str)
        """
        from pricing.models import Channel
        
        channels = Channel.objects.all()
        
        if not channels.exists():
            return False, Decimal('0.00'), "No channels configured"
        
        total_percent = sum(c.distribution_share_percent for c in channels)
        
        is_valid = total_percent == Decimal('100.00')
        
        if is_valid:
            message = f"Channel distribution is valid ({total_percent}%)"
        else:
            message = f"Channel distribution totals {total_percent}% (must be 100.00%)"
        
        return is_valid, total_percent, message
    
    
    
#Pickup Analysis

class PickupAnalysisService:
    """
    Service for pickup analysis, curve building, and forecasting.
    
    Forecast Methodology:
    - 50% weight: Historical pickup curve for season type
    - 30% weight: STLY (Same Time Last Year) comparison
    - 20% weight: Recent booking velocity trend
    
    This provides a data-driven forecast independent of manual estimates.
    """
    
    def __init__(self):
        """Initialize service with model references."""
        pass
    
    # =========================================================================
    # SNAPSHOT CAPTURE
    # =========================================================================
    
    def capture_daily_snapshot(self, arrival_date, otb_data):
        """
        Record today's OTB position for a specific arrival date.
        
        Args:
            arrival_date: The future arrival date
            otb_data: Dict with keys:
                - room_nights: int
                - revenue: Decimal
                - reservations: int
                - by_channel: dict (optional)
                - by_room_type: dict (optional)
                - by_rate_plan: dict (optional)
        
        Returns:
            DailyPickupSnapshot instance
        """
        from pricing.models import DailyPickupSnapshot
        
        today = date.today()
        
        snapshot, created = DailyPickupSnapshot.objects.update_or_create(
            snapshot_date=today,
            arrival_date=arrival_date,
            defaults={
                'otb_room_nights': otb_data.get('room_nights', 0),
                'otb_revenue': otb_data.get('revenue', Decimal('0.00')),
                'otb_reservations': otb_data.get('reservations', 0),
                'otb_by_channel': otb_data.get('by_channel', {}),
                'otb_by_room_type': otb_data.get('by_room_type', {}),
                'otb_by_rate_plan': otb_data.get('by_rate_plan', {}),
            }
        )
        
        return snapshot
    
    def capture_monthly_snapshot(self, target_month, snapshot_date=None):
        """
        Capture aggregated OTB snapshot for an entire month.
        
        Args:
            target_month: date object (any day in target month)
            snapshot_date: date to record as (defaults to today)
        
        Returns:
            MonthlyPickupSnapshot instance
        """
        from pricing.models import (
            MonthlyPickupSnapshot, DailyPickupSnapshot, RoomType
        )
        
        if snapshot_date is None:
            snapshot_date = date.today()
        
        # Normalize target_month to first day
        target_month_start = target_month.replace(day=1)
        
        # Calculate last day of month
        _, last_day = calendar.monthrange(target_month.year, target_month.month)
        target_month_end = target_month.replace(day=last_day)
        
        # Get all daily snapshots for this month from the snapshot_date
        daily_snapshots = DailyPickupSnapshot.objects.filter(
            snapshot_date=snapshot_date,
            arrival_date__gte=target_month_start,
            arrival_date__lte=target_month_end
        )
        
        # Aggregate metrics
        total_room_nights = 0
        total_revenue = Decimal('0.00')
        total_reservations = 0
        channel_breakdown = defaultdict(int)
        room_type_breakdown = defaultdict(int)
        
        for snapshot in daily_snapshots:
            total_room_nights += snapshot.otb_room_nights
            total_revenue += snapshot.otb_revenue
            total_reservations += snapshot.otb_reservations
            
            # Aggregate channel breakdown
            for channel, nights in snapshot.otb_by_channel.items():
                channel_breakdown[channel] += nights
            
            # Aggregate room type breakdown
            for room_type, nights in snapshot.otb_by_room_type.items():
                room_type_breakdown[room_type] += nights
        
        # Calculate available room nights for this month
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        days_in_month = last_day
        available_room_nights = total_rooms * days_in_month
        
        # Create or update monthly snapshot
        monthly_snapshot, created = MonthlyPickupSnapshot.objects.update_or_create(
            snapshot_date=snapshot_date,
            target_month=target_month_start,
            defaults={
                'otb_room_nights': total_room_nights,
                'otb_revenue': total_revenue,
                'otb_reservations': total_reservations,
                'available_room_nights': available_room_nights,
                'otb_by_channel': dict(channel_breakdown),
                'otb_by_room_type': dict(room_type_breakdown),
            }
        )
        
        return monthly_snapshot
    
    # =========================================================================
    # PICKUP CURVE BUILDING
    # =========================================================================
    
    def build_pickup_curve(self, season_type, historical_months, days_out_points=None):
        """
        Build a pickup curve from historical data.
        
        Args:
            season_type: 'peak', 'high', 'shoulder', or 'low'
            historical_months: List of date objects (first day of each month to include)
            days_out_points: List of days_out values to calculate (default: standard set)
        
        Returns:
            List of PickupCurve objects created/updated
        """
        from pricing.models import PickupCurve, MonthlyPickupSnapshot
        
        if days_out_points is None:
            days_out_points = [90, 75, 60, 45, 30, 21, 14, 7, 3, 0]
        
        curves_created = []
        
        for days_out in days_out_points:
            # Collect cumulative percentages at this days_out across all historical months
            percentages = []
            
            for month in historical_months:
                # Get snapshot at this days_out
                snapshot = MonthlyPickupSnapshot.objects.filter(
                    target_month=month,
                    days_out__gte=days_out - 2,
                    days_out__lte=days_out + 2
                ).order_by('days_out').first()
                
                # Get final occupancy for this month (snapshot at or after month started)
                final_snapshot = MonthlyPickupSnapshot.objects.filter(
                    target_month=month,
                    days_out__lte=0
                ).order_by('days_out').first()
                
                if snapshot and final_snapshot and final_snapshot.otb_room_nights > 0:
                    cumulative_pct = (
                        Decimal(str(snapshot.otb_room_nights)) /
                        Decimal(str(final_snapshot.otb_room_nights)) *
                        Decimal('100.00')
                    )
                    percentages.append(cumulative_pct)
            
            if percentages:
                # Calculate average and std deviation
                avg_pct = sum(percentages) / len(percentages)
                
                if len(percentages) > 1:
                    variance = sum((p - avg_pct) ** 2 for p in percentages) / len(percentages)
                    std_dev = variance ** Decimal('0.5')
                else:
                    std_dev = Decimal('0.00')
                
                # Get current version
                current_version = PickupCurve.objects.filter(
                    season_type=season_type,
                    season__isnull=True
                ).order_by('-curve_version').values_list('curve_version', flat=True).first() or 0
                
                # Create curve point
                curve, created = PickupCurve.objects.update_or_create(
                    season_type=season_type,
                    season=None,
                    days_out=days_out,
                    curve_version=current_version + 1,
                    defaults={
                        'cumulative_percent': avg_pct.quantize(Decimal('0.01')),
                        'sample_size': len(percentages),
                        'std_deviation': std_dev.quantize(Decimal('0.01')),
                        'built_from_start': min(historical_months),
                        'built_from_end': max(historical_months),
                    }
                )
                curves_created.append(curve)
        
        return curves_created
    
    def get_default_pickup_curves(self):
        """
        Return default pickup curves if no historical data is available.
        
        These are industry-standard patterns for different season types.
        """
        default_curves = {
            'peak': [
                (90, 25), (75, 35), (60, 50), (45, 65), (30, 80), 
                (21, 88), (14, 94), (7, 98), (3, 99), (0, 100)
            ],
            'high': [
                (90, 20), (75, 30), (60, 42), (45, 55), (30, 70),
                (21, 80), (14, 90), (7, 96), (3, 98), (0, 100)
            ],
            'shoulder': [
                (90, 15), (75, 22), (60, 32), (45, 45), (30, 60),
                (21, 72), (14, 85), (7, 94), (3, 97), (0, 100)
            ],
            'low': [
                (90, 10), (75, 15), (60, 25), (45, 38), (30, 52),
                (21, 65), (14, 80), (7, 92), (3, 96), (0, 100)
            ],
        }
        return default_curves
    
    # =========================================================================
    # BOOKING VELOCITY
    # =========================================================================
    
    def calculate_booking_velocity(self, target_month, days=7):
        """
        Calculate recent booking velocity for a target month.
        
        Args:
            target_month: date object (first day of month)
            days: Number of days to look back (default 7)
        
        Returns:
            dict with velocity metrics
        """
        from pricing.models import MonthlyPickupSnapshot
        
        today = date.today()
        week_ago = today - timedelta(days=days)
        
        # Get snapshots for this period
        recent_snapshot = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month,
            snapshot_date=today
        ).first()
        
        past_snapshot = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month,
            snapshot_date__lte=week_ago
        ).order_by('-snapshot_date').first()
        
        if not recent_snapshot or not past_snapshot:
            return {
                'daily_room_nights': Decimal('0.00'),
                'daily_revenue': Decimal('0.00'),
                'daily_bookings': Decimal('0.00'),
                'total_pickup': 0,
                'days_measured': 0,
                'velocity_trend': 'unknown',
            }
        
        # Calculate pickup over period
        days_between = (recent_snapshot.snapshot_date - past_snapshot.snapshot_date).days
        
        if days_between <= 0:
            return {
                'daily_room_nights': Decimal('0.00'),
                'daily_revenue': Decimal('0.00'),
                'daily_bookings': Decimal('0.00'),
                'total_pickup': 0,
                'days_measured': 0,
                'velocity_trend': 'unknown',
            }
        
        nights_pickup = recent_snapshot.otb_room_nights - past_snapshot.otb_room_nights
        revenue_pickup = recent_snapshot.otb_revenue - past_snapshot.otb_revenue
        reservations_pickup = recent_snapshot.otb_reservations - past_snapshot.otb_reservations
        
        daily_nights = Decimal(str(nights_pickup)) / Decimal(str(days_between))
        daily_revenue = revenue_pickup / Decimal(str(days_between))
        daily_bookings = Decimal(str(reservations_pickup)) / Decimal(str(days_between))
        
        # Determine trend (compare to previous period)
        # This is a simplified version - could be enhanced
        velocity_trend = 'stable'
        if daily_nights > Decimal('2.0'):
            velocity_trend = 'accelerating'
        elif daily_nights < Decimal('0.5'):
            velocity_trend = 'slowing'
        
        return {
            'daily_room_nights': daily_nights.quantize(Decimal('0.01')),
            'daily_revenue': daily_revenue.quantize(Decimal('0.01')),
            'daily_bookings': daily_bookings.quantize(Decimal('0.01')),
            'total_pickup': nights_pickup,
            'days_measured': days_between,
            'velocity_trend': velocity_trend,
        }
    
    # =========================================================================
    # FORECAST GENERATION
    # =========================================================================
    
    def generate_forecast(self, target_month, force_refresh=False):
        """
        Generate occupancy and revenue forecast for a future month.
        
        Uses weighted blend:
        - 50% Historical pickup curve
        - 30% STLY comparison
        - 20% Recent velocity
        
        Args:
            target_month: date object (any day in target month)
            force_refresh: If True, regenerate even if recent forecast exists
        
        Returns:
            OccupancyForecast instance
        """
        from pricing.models import (
            OccupancyForecast, MonthlyPickupSnapshot, PickupCurve,
            Season, RoomType, Channel
        )
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        target_month_start = target_month.replace(day=1)
        
        # Check for existing recent forecast
        if not force_refresh:
            existing = OccupancyForecast.objects.filter(
                target_month=target_month_start,
                forecast_date=today
            ).first()
            if existing:
                return existing
        
        # Get current OTB position
        current_otb = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month_start,
            snapshot_date=today
        ).first()
        
        # If no current snapshot, try to capture one
        if not current_otb:
            current_otb = self.capture_monthly_snapshot(target_month_start, today)
        
        # Calculate days out
        days_out = (target_month_start - today).days
        
        # Get season for this month
        season = Season.objects.filter(
            start_date__lte=target_month_start,
            end_date__gte=target_month_start
        ).first()
        
        # Determine season type
        season_type = self._get_season_type(season)
        
        # Calculate available room nights
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        _, last_day = calendar.monthrange(target_month.year, target_month.month)
        available_room_nights = total_rooms * last_day
        
        # =====================================================================
        # COMPONENT 1: Pickup Curve Forecast (50% weight)
        # =====================================================================
        curve_forecast = self._forecast_from_curve(
            current_otb, days_out, season_type, available_room_nights
        )
        
        # =====================================================================
        # COMPONENT 2: STLY Forecast (30% weight)
        # =====================================================================
        stly_forecast, stly_data = self._forecast_from_stly(
            current_otb, target_month_start, days_out
        )
        
        # =====================================================================
        # COMPONENT 3: Velocity Forecast (20% weight)
        # =====================================================================
        velocity_forecast = self._forecast_from_velocity(
            current_otb, target_month_start, days_out, available_room_nights
        )
        
        # =====================================================================
        # WEIGHTED BLEND
        # =====================================================================
        # Weights
        curve_weight = Decimal('0.50')
        stly_weight = Decimal('0.30') if stly_forecast else Decimal('0.00')
        velocity_weight = Decimal('0.20')
        
        # If no STLY, redistribute weight
        if not stly_forecast:
            curve_weight = Decimal('0.65')
            velocity_weight = Decimal('0.35')
        
        total_weight = curve_weight + stly_weight + velocity_weight
        
        blended_forecast = (
            (Decimal(str(curve_forecast or 0)) * curve_weight) +
            (Decimal(str(stly_forecast or 0)) * stly_weight) +
            (Decimal(str(velocity_forecast or 0)) * velocity_weight)
        ) / total_weight
        
        # Cap at available room nights (can't exceed 100% occupancy)
        forecast_nights = min(int(blended_forecast), available_room_nights)
        
        # =====================================================================
        # REVENUE CALCULATIONS
        # =====================================================================
        otb_room_nights = current_otb.otb_room_nights if current_otb else 0
        otb_revenue = current_otb.otb_revenue if current_otb else Decimal('0.00')
        
        # Calculate ADR from OTB
        if otb_room_nights > 0:
            otb_adr = otb_revenue / otb_room_nights
        else:
            # Use weighted average ADR from pricing system
            otb_adr = self._calculate_weighted_adr(season)
        
        # Forecast revenue
        forecast_revenue = otb_adr * Decimal(str(forecast_nights))
        
        # Calculate commission based on channel mix
        channel_mix = self._get_channel_mix()
        forecast_commission = self._calculate_commission(forecast_revenue, channel_mix)
        
        # =====================================================================
        # SCENARIO DATA (from Season.expected_occupancy)
        # =====================================================================
        scenario_occupancy = season.expected_occupancy if season else Decimal('70.00')
        scenario_room_nights = int(
            available_room_nights * (scenario_occupancy / Decimal('100.00'))
        )
        scenario_revenue = otb_adr * Decimal(str(scenario_room_nights))
        
        # =====================================================================
        # CREATE/UPDATE FORECAST
        # =====================================================================
        forecast, created = OccupancyForecast.objects.update_or_create(
            target_month=target_month_start,
            forecast_date=today,
            defaults={
                'season': season,
                'available_room_nights': available_room_nights,
                
                # Current OTB
                'otb_room_nights': otb_room_nights,
                'otb_revenue': otb_revenue,
                
                # Pickup forecast
                'pickup_forecast_nights': forecast_nights,
                'pickup_forecast_revenue': forecast_revenue,
                'pickup_expected_additional': max(0, forecast_nights - otb_room_nights),
                
                # Methodology breakdown
                'forecast_from_curve': curve_forecast or 0,
                'forecast_from_stly': stly_forecast or 0,
                'forecast_from_velocity': velocity_forecast or 0,
                
                # Scenario
                'scenario_occupancy': scenario_occupancy,
                'scenario_room_nights': scenario_room_nights,
                'scenario_revenue': scenario_revenue,
                
                # STLY
                'stly_occupancy': stly_data.get('final_occupancy') if stly_data else None,
                'stly_otb_at_same_point': stly_data.get('otb_at_point') if stly_data else None,
                'vs_stly_pace_percent': stly_data.get('pace_percent') if stly_data else None,
                
                # Revenue
                'forecast_adr': otb_adr,
                'forecast_commission': forecast_commission,
            }
        )
        
        # Generate insight note
        forecast.notes = forecast.generate_insight()
        forecast.save()
        
        return forecast
    
    def _get_season_type(self, season):
        """Map Season to season_type for pickup curve lookup."""
        if not season:
            return 'shoulder'
        
        index = season.season_index
        
        if index >= Decimal('1.30'):
            return 'peak'
        elif index >= Decimal('1.20'):
            return 'high'
        elif index >= Decimal('1.05'):
            return 'shoulder'
        else:
            return 'low'
    
    def _forecast_from_curve(self, current_otb, days_out, season_type, available_room_nights):
        """
        Calculate forecast using pickup curve.
        
        Logic: If curve shows 35% is typically booked at 60 days out,
        and we have 200 room nights OTB, then forecast = 200 / 0.35 = 571
        """
        from pricing.models import PickupCurve
        
        if not current_otb or current_otb.otb_room_nights == 0:
            return None
        
        # Get expected percentage at this days_out from curve
        expected_pct = PickupCurve.get_expected_percent_at_days_out(
            season_type, days_out
        )
        
        if not expected_pct:
            # Use default curves
            defaults = self.get_default_pickup_curves()
            curve_points = defaults.get(season_type, defaults['shoulder'])
            
            # Find closest point
            for d, pct in sorted(curve_points, key=lambda x: abs(x[0] - days_out)):
                expected_pct = Decimal(str(pct))
                break
        
        if expected_pct and expected_pct > 0:
            # Calculate forecast: OTB / (expected_pct / 100)
            forecast = (
                Decimal(str(current_otb.otb_room_nights)) / 
                (expected_pct / Decimal('100.00'))
            )
            
            # Cap at available
            return min(int(forecast), available_room_nights)
        
        return None
    
    def _forecast_from_stly(self, current_otb, target_month, days_out):
        """
        Calculate forecast using STLY comparison.
        
        Logic: If STLY had 150 nights at 60 days out and ended at 500,
        ratio = 500/150 = 3.33. Current OTB of 180 → forecast = 180 * 3.33 = 600
        """
        from pricing.models import MonthlyPickupSnapshot
        from dateutil.relativedelta import relativedelta
        
        if not current_otb or current_otb.otb_room_nights == 0:
            return None, None
        
        # Get STLY month
        stly_month = target_month - relativedelta(years=1)
        
        # Get STLY snapshot at similar days_out
        stly_snapshot = MonthlyPickupSnapshot.get_stly(target_month, days_out)
        
        # Get STLY final position
        stly_final = MonthlyPickupSnapshot.objects.filter(
            target_month=stly_month,
            days_out__lte=0
        ).order_by('days_out').first()
        
        if not stly_snapshot or not stly_final or stly_snapshot.otb_room_nights == 0:
            return None, None
        
        # Calculate STLY ratio
        stly_ratio = (
            Decimal(str(stly_final.otb_room_nights)) / 
            Decimal(str(stly_snapshot.otb_room_nights))
        )
        
        # Apply ratio to current OTB
        forecast = current_otb.otb_room_nights * stly_ratio
        
        # Calculate pace comparison
        pace_percent = (
            (Decimal(str(current_otb.otb_room_nights)) - 
             Decimal(str(stly_snapshot.otb_room_nights))) /
            Decimal(str(stly_snapshot.otb_room_nights)) *
            Decimal('100.00')
        )
        
        stly_data = {
            'otb_at_point': stly_snapshot.otb_room_nights,
            'final_occupancy': stly_final.otb_occupancy_percent,
            'final_room_nights': stly_final.otb_room_nights,
            'ratio': stly_ratio,
            'pace_percent': pace_percent.quantize(Decimal('0.01')),
        }
        
        return int(forecast), stly_data
    
    def _forecast_from_velocity(self, current_otb, target_month, days_out, available_room_nights):
        """
        Calculate forecast using recent booking velocity.
        
        Logic: If picking up 3 room nights/day and have 45 days left,
        expect 3 * 45 = 135 additional room nights
        """
        if not current_otb or days_out <= 0:
            return None
        
        velocity = self.calculate_booking_velocity(target_month)
        
        daily_nights = velocity.get('daily_room_nights', Decimal('0.00'))
        
        if daily_nights <= 0:
            return None
        
        # Apply decay factor (velocity typically decreases as arrival approaches)
        # Simple decay: reduce velocity by 20% for each 30-day period closer to arrival
        decay_factor = Decimal('1.00')
        if days_out <= 30:
            decay_factor = Decimal('0.60')
        elif days_out <= 60:
            decay_factor = Decimal('0.80')
        elif days_out <= 90:
            decay_factor = Decimal('0.90')
        
        # Project remaining pickup
        expected_pickup = daily_nights * Decimal(str(days_out)) * decay_factor
        
        forecast = current_otb.otb_room_nights + int(expected_pickup)
        
        return min(forecast, available_room_nights)
    
    def _calculate_weighted_adr(self, season):
        """Calculate weighted ADR from pricing setup."""
        from pricing.services import calculate_final_rate_with_modifier
        from pricing.models import RoomType, RatePlan, Channel, RateModifier
        
        if not season:
            return Decimal('150.00')  # Default fallback
        
        total_rate = Decimal('0.00')
        total_weight = 0
        
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        for room in rooms:
            room_weight = room.number_of_rooms
            
            for rate_plan in rate_plans:
                for channel in channels:
                    # Get standard modifier (or first active one)
                    modifier = RateModifier.objects.filter(
                        channel=channel, active=True
                    ).first()
                    
                    modifier_discount = Decimal('0.00')
                    if modifier:
                        modifier_discount = modifier.get_discount_for_season(season)
                    
                    rate, _ = calculate_final_rate_with_modifier(
                        room_base_rate=room.get_effective_base_rate(),
                        season_index=season.season_index,
                        meal_supplement=rate_plan.meal_supplement,
                        channel_base_discount=channel.base_discount_percent,
                        modifier_discount=modifier_discount,
                        commission_percent=Decimal('0.00'),  # Gross ADR
                        occupancy=2
                    )
                    
                    total_rate += rate * room_weight
                    total_weight += room_weight
        
        if total_weight > 0:
            return (total_rate / total_weight).quantize(Decimal('0.01'))
        
        return Decimal('150.00')
    
    def _get_channel_mix(self):
        """Get channel distribution mix from Channel model."""
        from pricing.models import Channel
        
        channels = Channel.objects.all()
        mix = {}
        
        for channel in channels:
            if channel.distribution_share_percent > 0:
                mix[channel.id] = {
                    'share': channel.distribution_share_percent / Decimal('100.00'),
                    'commission': channel.commission_percent,
                }
        
        return mix
    
    def _calculate_commission(self, gross_revenue, channel_mix):
        """Calculate expected commission based on channel mix."""
        if not channel_mix:
            return Decimal('0.00')
        
        total_commission = Decimal('0.00')
        
        for channel_id, data in channel_mix.items():
            channel_revenue = gross_revenue * data['share']
            channel_commission = channel_revenue * (data['commission'] / Decimal('100.00'))
            total_commission += channel_commission
        
        return total_commission.quantize(Decimal('0.01'))
    
    # =========================================================================
    # LEAD TIME ANALYSIS
    # =========================================================================
    
    def analyze_lead_time_distribution(self, start_date, end_date):
        """
        Analyze lead time distribution from historical snapshots.
        
        Returns breakdown of bookings by lead time bucket.
        """
        from pricing.models import DailyPickupSnapshot
        
        buckets = {
            '0-7': {'min': 0, 'max': 7, 'count': 0, 'revenue': Decimal('0.00')},
            '8-14': {'min': 8, 'max': 14, 'count': 0, 'revenue': Decimal('0.00')},
            '15-30': {'min': 15, 'max': 30, 'count': 0, 'revenue': Decimal('0.00')},
            '31-60': {'min': 31, 'max': 60, 'count': 0, 'revenue': Decimal('0.00')},
            '61-90': {'min': 61, 'max': 90, 'count': 0, 'revenue': Decimal('0.00')},
            '90+': {'min': 91, 'max': 999, 'count': 0, 'revenue': Decimal('0.00')},
        }
        
        # Get snapshots and calculate pickup between consecutive days
        snapshots = DailyPickupSnapshot.objects.filter(
            arrival_date__gte=start_date,
            arrival_date__lte=end_date
        ).order_by('arrival_date', 'snapshot_date')
        
        # Group by arrival date
        by_arrival = defaultdict(list)
        for snapshot in snapshots:
            by_arrival[snapshot.arrival_date].append(snapshot)
        
        # Calculate daily pickup and assign to buckets
        for arrival_date, arrival_snapshots in by_arrival.items():
            arrival_snapshots.sort(key=lambda x: x.snapshot_date)
            
            for i in range(1, len(arrival_snapshots)):
                prev = arrival_snapshots[i-1]
                curr = arrival_snapshots[i]
                
                # Pickup that occurred
                nights_pickup = curr.otb_room_nights - prev.otb_room_nights
                revenue_pickup = curr.otb_revenue - prev.otb_revenue
                
                if nights_pickup > 0:
                    # Assign to bucket based on days_out when pickup occurred
                    days_out = curr.days_out
                    
                    for bucket_name, bucket_data in buckets.items():
                        if bucket_data['min'] <= days_out <= bucket_data['max']:
                            bucket_data['count'] += nights_pickup
                            bucket_data['revenue'] += revenue_pickup
                            break
        
        # Calculate percentages
        total_nights = sum(b['count'] for b in buckets.values())
        total_revenue = sum(b['revenue'] for b in buckets.values())
        
        result = []
        for bucket_name, bucket_data in buckets.items():
            result.append({
                'bucket': bucket_name,
                'room_nights': bucket_data['count'],
                'revenue': bucket_data['revenue'],
                'nights_percent': (
                    Decimal(str(bucket_data['count'])) / Decimal(str(total_nights)) * 100
                    if total_nights > 0 else Decimal('0.00')
                ).quantize(Decimal('0.1')),
                'revenue_percent': (
                    bucket_data['revenue'] / total_revenue * 100
                    if total_revenue > 0 else Decimal('0.00')
                ).quantize(Decimal('0.1')),
            })
        
        return result
    
    # =========================================================================
    # FORECAST SUMMARY
    # =========================================================================
    
    def get_forecast_summary(self, months_ahead=6):
        """
        Get forecast summary for the next N months.
        
        Returns list of forecasts for dashboard display.
        """
        from pricing.models import OccupancyForecast
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        summaries = []
        
        for i in range(months_ahead):
            target_month = (today + relativedelta(months=i)).replace(day=1)
            
            # Generate or get existing forecast
            forecast = self.generate_forecast(target_month)
            
            if forecast:
                summaries.append({
                    'month': target_month,
                    'month_name': target_month.strftime('%b %Y'),
                    'days_out': forecast.days_out,
                    'otb_occupancy': forecast.otb_occupancy_percent,
                    'otb_room_nights': forecast.otb_room_nights,
                    'pickup_forecast_occupancy': forecast.pickup_forecast_occupancy,
                    'pickup_forecast_nights': forecast.pickup_forecast_nights,
                    'scenario_occupancy': forecast.scenario_occupancy,
                    'scenario_room_nights': forecast.scenario_room_nights,
                    'variance_nights': forecast.variance_nights,
                    'variance_percent': forecast.variance_percent,
                    'vs_stly_pace': forecast.vs_stly_pace_percent,
                    'confidence': forecast.confidence_level,
                    'forecast_revenue': forecast.pickup_forecast_revenue,
                    'forecast_net_revenue': forecast.forecast_net_revenue,
                    'insight': forecast.notes,
                })
        
        return summaries