"""
Forecast services: RevenueForecastService, PickupAnalysisService.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar
import math

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


"""
Updated ReservationImportService - Complete Version
====================================================

Replace the existing ReservationImportService class in pricing_services.py with this.

Key fixes:
1. SynXis Activity Report header detection (skips 3 rows)
2. Type column maps to status: New/Amend -> confirmed, Cancel -> cancelled
3. Multi-room sequence tracking per (confirmation_no + arrival_date)
4. Unique lookup includes arrival_date: (hotel, confirmation_no, arrival_date, room_sequence)
5. Room type code mapping for SynXis short codes
6. Channel mapping from CompanyName/TravelAgent
7. Date parsing for SynXis format: '2025-06-06 2:30 PM'

IMPORTANT: Also update your Reservation model Meta class:
    unique_together = ['hotel', 'confirmation_no', 'arrival_date', 'room_sequence']
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
from collections import defaultdict
import pandas as pd
import hashlib
import re

from django.db import transaction
from django.utils import timezone


