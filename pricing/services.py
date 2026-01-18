

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