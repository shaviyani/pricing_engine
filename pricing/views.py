"""
Pricing views.
"""

from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from .models import Season, RoomType, RatePlan, Channel
from .services import calculate_final_rate
from dateutil.relativedelta import relativedelta
from datetime import date, timedelta
import json



# pricing/views.py - SIMPLIFIED HomeView for AJAX approach

class HomeView(TemplateView):
    """
    Home page with quick links and rate parity summary.
    Revenue forecast loaded dynamically via AJAX.
    """
    template_name = 'pricing/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Quick stats only
        context['stats'] = {
            'seasons_count': Season.objects.count(),
            'rooms_count': RoomType.objects.count(),
            'rate_plans_count': RatePlan.objects.count(),
            'channels_count': Channel.objects.count(),
        }
        
        # Rate parity summary
        parity_data = []
        parity_season = None
        parity_room = None
        parity_rate_plan = None
        all_seasons = []
        
        try:
            from .services import calculate_final_rate_with_modifier
            from decimal import Decimal
            
            seasons = Season.objects.all().order_by('start_date')
            all_seasons = list(seasons)
            rooms = RoomType.objects.all()
            channels = Channel.objects.all()
            rate_plans = RatePlan.objects.all()
            
            selected_season_id = self.request.GET.get('parity_season')
            
            if seasons.exists() and rooms.exists() and channels.exists() and rate_plans.exists():
                if selected_season_id:
                    try:
                        parity_season = Season.objects.get(id=selected_season_id)
                    except (Season.DoesNotExist, ValueError):
                        parity_season = seasons.first()
                else:
                    parity_season = seasons.first()
                
                parity_room = rooms.first()
                parity_rate_plan = rate_plans.first()
                
                # Calculate BAR
                bar_rate, _ = calculate_final_rate_with_modifier(
                    room_base_rate=parity_room.get_effective_base_rate(),
                    season_index=parity_season.season_index,
                    meal_supplement=parity_rate_plan.meal_supplement,
                    channel_base_discount=Decimal('0.00'),
                    modifier_discount=Decimal('0.00'),
                    commission_percent=Decimal('0.00'),
                    occupancy=2
                )
                
                # Check each channel's rate
                for channel in channels:
                    season_discount = Decimal('0.00')
                    try:
                        from .models import RateModifier
                        modifiers = RateModifier.objects.filter(channel=channel, active=True)
                        
                        if modifiers.exists():
                            modifier = modifiers.filter(discount_percent=0).first()
                            if not modifier:
                                modifier = modifiers.first()
                            season_discount = modifier.get_discount_for_season(parity_season)
                    except:
                        pass
                    
                    channel_rate, breakdown = calculate_final_rate_with_modifier(
                        room_base_rate=parity_room.get_effective_base_rate(),
                        season_index=parity_season.season_index,
                        meal_supplement=parity_rate_plan.meal_supplement,
                        channel_base_discount=channel.base_discount_percent,
                        modifier_discount=season_discount,
                        commission_percent=channel.commission_percent,
                        occupancy=2
                    )
                    
                    difference = channel_rate - bar_rate
                    difference_percent = (difference / bar_rate * 100) if bar_rate > 0 else Decimal('0.00')
                    
                    if abs(difference_percent) < Decimal('1.0'):
                        status = 'good'
                        status_text = 'At Parity'
                    elif difference_percent < 0:
                        status = 'warning'
                        status_text = 'Below BAR'
                    else:
                        status = 'info'
                        status_text = 'Above BAR'
                    
                    parity_data.append({
                        'channel': channel,
                        'rate': channel_rate,
                        'bar_rate': bar_rate,
                        'difference': difference,
                        'difference_percent': difference_percent,
                        'status': status,
                        'status_text': status_text,
                        'net_revenue': breakdown['net_revenue'],
                    })
        
        except Exception as e:
            import traceback
            print(f"Parity calculation error: {e}")
            print(traceback.format_exc())
            parity_data = []
        
        context['parity_data'] = parity_data
        context['parity_season'] = parity_season
        context['parity_room'] = parity_room
        context['parity_rate_plan'] = parity_rate_plan
        context['all_seasons'] = all_seasons
        
        return context


class PricingMatrixView(TemplateView):
    """
    Main pricing matrix showing all rate combinations with modifiers across all seasons.
    
    Display structure:
    - Seasons as columns
    - For each Channel:
        - For each Room Type + Rate Plan:
            - BAR row showing baseline rates
            - Modifier rows showing discounted rates
    """
    template_name = 'pricing/matrix.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all data
        from .models import RateModifier
        from .services import calculate_final_rate_with_modifier
        
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        # Check if we have data
        if not all([seasons.exists(), rooms.exists(), rate_plans.exists(), channels.exists()]):
            context['has_data'] = False
            context['seasons'] = seasons
            context['rooms'] = rooms
            context['rate_plans'] = rate_plans
            context['channels'] = channels
            return context
        
        context['has_data'] = True
        
        # Get selected season (default to first) - kept for compatibility
        season_id = self.request.GET.get('season', seasons.first().id if seasons.exists() else None)
        try:
            selected_season = Season.objects.get(id=season_id)
        except (Season.DoesNotExist, ValueError):
            selected_season = seasons.first()
        
        # Build enhanced matrix with modifiers for ALL seasons
        # Structure: matrix[channel_id][room_id][rate_plan_id] = {
        #   'bar_rate': ...,  (for display purposes - from selected season)
        #   'modifiers': [{
        #       'modifier': obj, 
        #       'seasons': {season_id: {'rate': rate, 'breakdown': breakdown}}
        #   }]
        # }
        matrix = {}
        
        for channel in channels:
            matrix[channel.id] = {}
            # Get all active modifiers for this channel
            modifiers = RateModifier.objects.filter(channel=channel, active=True)
            
            for room in rooms:
                matrix[channel.id][room.id] = {}
                
                for rate_plan in rate_plans:
                    # Calculate BAR for selected season (for display in header)
                    from decimal import Decimal
                    seasonal_rate = room.get_effective_base_rate() * selected_season.season_index
                    meal_cost = rate_plan.meal_supplement * 2
                    bar_rate = seasonal_rate + meal_cost
                    
                    # Calculate rates for each modifier ACROSS ALL SEASONS
                    modifiers_list = []
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        # Calculate rate for EACH season
                        for season in seasons:
                            # Get season-specific discount
                            season_discount = modifier.get_discount_for_season(season)
                            
                            final_rate, breakdown = calculate_final_rate_with_modifier(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                        
                        modifiers_list.append(modifier_data)
                    
                    matrix[channel.id][room.id][rate_plan.id] = {
                        'bar_rate': bar_rate,
                        'modifiers': modifiers_list
                    }
        
        context['seasons'] = seasons
        context['selected_season'] = selected_season
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        
        return context
        context['selected_season'] = selected_season
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        
        return context


class AllSeasonsComparisonView(TemplateView):
    """
    Compare all seasons side-by-side with rate modifiers (enhanced version).
    
    Display structure:
    - Columns: All seasons
    - Rows: Room Type + Rate Plan + Channel + Rate Modifier combinations
    - Cells: Calculated rate for each season
    - Highlights: Min/max rates across all modifiers per channel
    """
    template_name = 'pricing/all_seasons_comparison.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all data
        from .models import RateModifier
        from .services import calculate_final_rate_with_modifier
        
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        # Check if we have data
        if not all([seasons.exists(), rooms.exists(), rate_plans.exists(), channels.exists()]):
            context['has_data'] = False
            context['seasons'] = seasons
            context['rooms'] = rooms
            context['rate_plans'] = rate_plans
            context['channels'] = channels
            return context
        
        context['has_data'] = True
        
        # Get filter parameters
        selected_rate_plan_id = self.request.GET.get('rate_plan')
        
        # Filter rate plans if selected
        if selected_rate_plan_id:
            try:
                rate_plans = RatePlan.objects.filter(id=selected_rate_plan_id)
            except (RatePlan.DoesNotExist, ValueError):
                rate_plans = RatePlan.objects.all()
        
        # Build comprehensive matrix with rate modifiers
        # Structure: matrix[channel_id][room_id][rate_plan_id][modifier_id][season_id] = {rate, breakdown}
        matrix = {}
        channel_stats = {}  # Track min/max for each channel
        
        for channel in channels:
            matrix[channel.id] = {}
            channel_stats[channel.id] = {'all_rates': []}
            
            # Get all active modifiers for this channel
            modifiers = RateModifier.objects.filter(channel=channel, active=True)
            
            for room in rooms:
                matrix[channel.id][room.id] = {}
                
                for rate_plan in rate_plans:
                    matrix[channel.id][room.id][rate_plan.id] = {}
                    
                    for modifier in modifiers:
                        matrix[channel.id][room.id][rate_plan.id][modifier.id] = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        # Calculate rates for ALL seasons with this modifier
                        modifier_rates_list = []
                        for season in seasons:
                            # Get season-specific discount (or fall back to base)
                            season_discount = modifier.get_discount_for_season(season)
                            
                            final_rate, breakdown = calculate_final_rate_with_modifier(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2
                            )
                            
                            matrix[channel.id][room.id][rate_plan.id][modifier.id]['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                            modifier_rates_list.append(final_rate)
                            channel_stats[channel.id]['all_rates'].append(final_rate)
                        
                        # Add min/max info for this modifier across seasons
                        if modifier_rates_list:
                            min_rate = min(modifier_rates_list)
                            max_rate = max(modifier_rates_list)
                            for season in seasons:
                                rate = matrix[channel.id][room.id][rate_plan.id][modifier.id]['seasons'][season.id]['rate']
                                matrix[channel.id][room.id][rate_plan.id][modifier.id]['seasons'][season.id]['is_min'] = (rate == min_rate)
                                matrix[channel.id][room.id][rate_plan.id][modifier.id]['seasons'][season.id]['is_max'] = (rate == max_rate)
        
        # Calculate channel-wide min/max
        for channel_id, stats in channel_stats.items():
            if stats['all_rates']:
                stats['min_rate'] = min(stats['all_rates'])
                stats['max_rate'] = max(stats['all_rates'])
        
        context['seasons'] = seasons
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['all_rate_plans'] = RatePlan.objects.all()  # For filter dropdown
        context['selected_rate_plan_id'] = selected_rate_plan_id
        context['channels'] = channels
        context['matrix'] = matrix
        context['channel_stats'] = channel_stats
        
        # Add stats for display
        total_modifiers = sum(RateModifier.objects.filter(channel=c, active=True).count() for c in channels)
        context['stats'] = {
            'combinations_per_season': rooms.count() * rate_plans.count() * total_modifiers,
            'total_calculations': rooms.count() * rate_plans.count() * total_modifiers * seasons.count(),
        }
        
        return context


class EnhancedPricingMatrixView(TemplateView):
    """
    Enhanced pricing matrix showing BAR and all rate modifiers.
    
    Display structure:
    - Season selector
    - For each Channel:
        - BAR rate (reference)
        - Channel base rate
        - All rate modifiers (Genius, Mobile App, Newsletter, etc.)
        - Net revenue after commission
    """
    template_name = 'pricing/enhanced_matrix.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all data
        from .models import RateModifier
        from .services import calculate_final_rate_with_modifier
        
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        # Check if we have data
        if not all([seasons.exists(), rooms.exists(), rate_plans.exists(), channels.exists()]):
            context['has_data'] = False
            context['seasons'] = seasons
            context['rooms'] = rooms
            context['rate_plans'] = rate_plans
            context['channels'] = channels
            return context
        
        context['has_data'] = True
        
        # Get selected season (default to first)
        season_id = self.request.GET.get('season', seasons.first().id if seasons.exists() else None)
        try:
            selected_season = Season.objects.get(id=season_id)
        except (Season.DoesNotExist, ValueError):
            selected_season = seasons.first()
        
        # Build enhanced matrix with modifiers for ALL seasons
        # Structure: matrix[channel_id][room_id][rate_plan_id] = {
        #   'bar_rate': ...,  (for display purposes - from first season)
        #   'modifiers': [{
        #       'modifier': obj, 
        #       'seasons': {season_id: {'rate': rate, 'breakdown': breakdown}}
        #   }]
        # }
        matrix = {}
        
        for channel in channels:
            matrix[channel.id] = {}
            # Get all active modifiers for this channel
            modifiers = RateModifier.objects.filter(channel=channel, active=True)
            
            for room in rooms:
                matrix[channel.id][room.id] = {}
                
                for rate_plan in rate_plans:
                    # Calculate BAR for selected season (for display in header)
                    from decimal import Decimal
                    seasonal_rate = room.get_effective_base_rate() * selected_season.season_index
                    meal_cost = rate_plan.meal_supplement * 2
                    bar_rate = seasonal_rate + meal_cost
                    
                    # Calculate rates for each modifier ACROSS ALL SEASONS
                    modifiers_list = []
                    for modifier in modifiers:
                        modifier_data = {
                            'modifier': modifier,
                            'seasons': {}
                        }
                        
                        # Calculate rate for EACH season
                        for season in seasons:
                            # Get season-specific discount
                            season_discount = modifier.get_discount_for_season(season)
                            
                            final_rate, breakdown = calculate_final_rate_with_modifier(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=season.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2
                            )
                            
                            modifier_data['seasons'][season.id] = {
                                'rate': final_rate,
                                'breakdown': breakdown
                            }
                        
                        modifiers_list.append(modifier_data)
                    
                    matrix[channel.id][room.id][rate_plan.id] = {
                        'bar_rate': bar_rate,
                        'modifiers': modifiers_list
                    }
        
        context['seasons'] = seasons
        context['selected_season'] = selected_season
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        context['matrix'] = matrix
        
        return context


class ADRAnalysisView(TemplateView):
    """
    ADR (Average Daily Rate) analysis across all seasons.
    
    Shows:
    - ADR for each season (simple average)
    - ADR with different mix scenarios (weighted)
    - Comparison across seasons
    - RevPAR potential with occupancy assumptions
    """
    template_name = 'pricing/adr_analysis.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from decimal import Decimal
        
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        if not all([seasons.exists(), rooms.exists(), rate_plans.exists(), channels.exists()]):
            context['has_data'] = False
            return context
        
        context['has_data'] = True
        
        # Calculate ADR for each season with different scenarios
        adr_data = []
        
        for season in seasons:
            # Scenario 1: Simple Average (Equal Mix)
            simple_adr = season.calculate_adr()
            
            # Scenario 2: OTA Heavy (70% OTA, 30% DIRECT)
            ota = channels.filter(name__icontains='OTA').first()
            direct = channels.filter(name__icontains='DIRECT').first()
            
            ota_heavy_mix = {}
            if ota and direct:
                ota_heavy_mix = {
                    ota.id: Decimal('0.70'),
                    direct.id: Decimal('0.30')
                }
            ota_heavy_adr = season.calculate_adr(channel_mix=ota_heavy_mix) if ota_heavy_mix else simple_adr
            
            # Scenario 3: Direct Heavy (40% OTA, 60% DIRECT)
            direct_heavy_mix = {}
            if ota and direct:
                direct_heavy_mix = {
                    ota.id: Decimal('0.40'),
                    direct.id: Decimal('0.60')
                }
            direct_heavy_adr = season.calculate_adr(channel_mix=direct_heavy_mix) if direct_heavy_mix else simple_adr
            
            # Scenario 4: Budget Mix (60% Room Only + B&B, 40% Half/Full Board)
            room_only = rate_plans.filter(name__icontains='Room Only').first()
            bb = rate_plans.filter(name__icontains='Breakfast').first()
            hb = rate_plans.filter(name__icontains='Half').first()
            fb = rate_plans.filter(name__icontains='Full').first()
            
            budget_mix = {}
            if all([room_only, bb, hb, fb]):
                budget_mix = {
                    room_only.id: Decimal('0.30'),
                    bb.id: Decimal('0.30'),
                    hb.id: Decimal('0.25'),
                    fb.id: Decimal('0.15')
                }
            budget_adr = season.calculate_adr(rate_plan_mix=budget_mix) if budget_mix else simple_adr
            
            # Scenario 5: Premium Mix (20% Room Only, 80% meal plans)
            premium_mix = {}
            if all([room_only, bb, hb, fb]):
                premium_mix = {
                    room_only.id: Decimal('0.20'),
                    bb.id: Decimal('0.30'),
                    hb.id: Decimal('0.30'),
                    fb.id: Decimal('0.20')
                }
            premium_adr = season.calculate_adr(rate_plan_mix=premium_mix) if premium_mix else simple_adr
            
            adr_data.append({
                'season': season,
                'simple_adr': simple_adr,
                'ota_heavy_adr': ota_heavy_adr,
                'direct_heavy_adr': direct_heavy_adr,
                'budget_adr': budget_adr,
                'premium_adr': premium_adr,
                # Calculate RevPAR with season's expected occupancy
                'revpar_expected': season.calculate_revpar(),
                # Also show with different occupancy assumptions
                'revpar_60': simple_adr * Decimal('0.60'),  # 60% occupancy
                'revpar_75': simple_adr * Decimal('0.75'),  # 75% occupancy
                'revpar_90': simple_adr * Decimal('0.90'),  # 90% occupancy
                'occupancy_percent': season.expected_occupancy,
            })
        
        context['seasons'] = seasons
        context['adr_data'] = adr_data
        context['rooms'] = rooms
        context['rate_plans'] = rate_plans
        context['channels'] = channels
        
        # Calculate year-round weighted ADR (by number of days in each season)
        total_days = Decimal('0')
        weighted_adr_sum = Decimal('0')
        
        for data in adr_data:
            season = data['season']
            days = (season.end_date - season.start_date).days + 1
            total_days += days
            weighted_adr_sum += data['simple_adr'] * days
        
        context['annual_adr'] = (weighted_adr_sum / total_days).quantize(Decimal('0.01')) if total_days > 0 else Decimal('0.00')
        
        return context
"""
Revenue Analysis View - Monthly and Seasonal Revenue Projections
"""

from django.views.generic import TemplateView
from pricing.models import Season, RoomType, RatePlan, Channel
from decimal import Decimal
from datetime import timedelta
import calendar


class RevenueAnalysisView(TemplateView):
    """
    Revenue analysis with monthly and seasonal breakdowns.
    
    Calculates projected revenue based on:
    - Available rooms per property
    - Expected occupancy per season
    - ADR per season
    - Days in each month/season
    """
    template_name = 'pricing/revenue_analysis.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.models import Property
        
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        
        if not seasons.exists() or not rooms.exists():
            context['has_data'] = False
            return context
        
        context['has_data'] = True
        
        # Calculate total rooms from room types
        total_rooms = sum(room.number_of_rooms for room in rooms)
        context['total_rooms'] = total_rooms
        context['rooms_by_type'] = [{'name': room.name, 'count': room.number_of_rooms} for room in rooms]
        
        # Calculate seasonal revenue
        seasonal_data = []
        total_annual_revenue = Decimal('0.00')
        total_annual_room_nights = 0
        
        for season in seasons:
            # Calculate days in season
            days_in_season = (season.end_date - season.start_date).days + 1
            
            # Calculate ADR for this season
            adr = season.calculate_adr()
            
            # Calculate RevPAR
            revpar = season.calculate_revpar()
            
            # Calculate available room nights
            available_room_nights = total_rooms * days_in_season
            
            # Calculate occupied room nights
            occupancy_decimal = season.expected_occupancy / Decimal('100.00')
            occupied_room_nights = int(available_room_nights * occupancy_decimal)
            
            # Calculate revenue
            season_revenue = adr * occupied_room_nights
            
            # Calculate revenue per available room
            revenue_per_available_room = season_revenue / available_room_nights if available_room_nights > 0 else Decimal('0.00')
            
            seasonal_data.append({
                'season': season,
                'days': days_in_season,
                'adr': adr,
                'occupancy': season.expected_occupancy,
                'revpar': revpar,
                'available_room_nights': available_room_nights,
                'occupied_room_nights': occupied_room_nights,
                'revenue': season_revenue,
                'revenue_per_day': season_revenue / days_in_season if days_in_season > 0 else Decimal('0.00'),
            })
            
            total_annual_revenue += season_revenue
            total_annual_room_nights += occupied_room_nights
        
        context['seasonal_data'] = seasonal_data
        context['total_annual_revenue'] = total_annual_revenue
        context['total_annual_room_nights'] = total_annual_room_nights
        context['annual_adr'] = (total_annual_revenue / total_annual_room_nights).quantize(Decimal('0.01')) if total_annual_room_nights > 0 else Decimal('0.00')
        
        # Calculate monthly breakdown
        monthly_data = []
        months_in_year = []
        
        # Get year from first season
        if seasons.exists():
            year = seasons.first().start_date.year
            
            for month_num in range(1, 13):
                month_start = seasons.first().start_date.replace(month=month_num, day=1)
                
                # Handle year transition
                if month_num < seasons.first().start_date.month:
                    month_start = month_start.replace(year=year + 1)
                
                # Get last day of month
                last_day = calendar.monthrange(month_start.year, month_start.month)[1]
                month_end = month_start.replace(day=last_day)
                
                month_name = month_start.strftime('%B %Y')
                days_in_month = last_day
                
                # Find which season(s) this month falls into
                month_revenue = Decimal('0.00')
                month_room_nights = 0
                weighted_adr = Decimal('0.00')
                weighted_occupancy = Decimal('0.00')
                total_days_accounted = 0
                
                for season in seasons:
                    # Check if season overlaps with this month
                    overlap_start = max(month_start, season.start_date)
                    overlap_end = min(month_end, season.end_date)
                    
                    if overlap_start <= overlap_end:
                        # Calculate days of overlap
                        overlap_days = (overlap_end - overlap_start).days + 1
                        
                        # Calculate revenue for this overlap period
                        adr = season.calculate_adr()
                        occupancy_decimal = season.expected_occupancy / Decimal('100.00')
                        
                        available_nights = total_rooms * overlap_days
                        occupied_nights = int(available_nights * occupancy_decimal)
                        overlap_revenue = adr * occupied_nights
                        
                        month_revenue += overlap_revenue
                        month_room_nights += occupied_nights
                        
                        # Weight ADR and occupancy by days
                        day_weight = Decimal(str(overlap_days)) / Decimal(str(days_in_month))
                        weighted_adr += adr * day_weight
                        weighted_occupancy += season.expected_occupancy * day_weight
                        total_days_accounted += overlap_days
                
                monthly_data.append({
                    'month': month_name,
                    'month_num': month_num,
                    'year': month_start.year,
                    'days': days_in_month,
                    'adr': weighted_adr,
                    'occupancy': weighted_occupancy,
                    'room_nights': month_room_nights,
                    'revenue': month_revenue,
                    'revenue_per_day': month_revenue / days_in_month if days_in_month > 0 else Decimal('0.00'),
                })
        
        context['monthly_data'] = monthly_data
        
        # Room type contribution analysis (using actual room counts)
        room_contribution = []
        
        for room in rooms:
            room_revenue = Decimal('0.00')
            room_nights = 0
            
            for season_info in seasonal_data:
                season = season_info['season']
                
                # Calculate this room type's contribution based on actual inventory
                room_count = room.number_of_rooms
                room_base_rate = room.get_effective_base_rate()
                
                # Calculate days in season
                days_in_season = (season.end_date - season.start_date).days + 1
                
                # Calculate occupied nights for this room type
                available_nights = room_count * days_in_season
                occupancy_decimal = season.expected_occupancy / Decimal('100.00')
                occupied_nights = int(available_nights * occupancy_decimal)
                
                # Calculate seasonal rate for this room
                seasonal_rate = room_base_rate * season.season_index
                
                # Calculate revenue for this room type in this season
                room_revenue += seasonal_rate * occupied_nights
                room_nights += occupied_nights
            
            room_contribution.append({
                'room': room,
                'room_count': room.number_of_rooms,
                'room_nights': room_nights,
                'revenue': room_revenue,
                'adr': (room_revenue / room_nights).quantize(Decimal('0.01')) if room_nights > 0 else Decimal('0.00'),
                'percentage': (room_revenue / total_annual_revenue * 100).quantize(Decimal('0.1')) if total_annual_revenue > 0 else Decimal('0.0'),
            })
        
        context['room_contribution'] = room_contribution
        context['seasons'] = seasons
        context['rooms'] = rooms
        
        # Calculate some KPIs
        total_available_rooms = total_rooms * 365
        annual_occupancy = (Decimal(str(total_annual_room_nights)) / Decimal(str(total_available_rooms)) * 100).quantize(Decimal('0.1')) if total_available_rooms > 0 else Decimal('0.0')
        
        context['kpis'] = {
            'annual_occupancy': annual_occupancy,
            'total_available_rooms': total_available_rooms,
            'average_daily_revenue': (total_annual_revenue / 365).quantize(Decimal('0.01')),
            'revenue_per_available_room': (total_annual_revenue / total_available_rooms).quantize(Decimal('0.01')) if total_available_rooms > 0 else Decimal('0.00'),
        }
        
        return context


@require_POST
def update_room(request, room_id):
    """
    AJAX endpoint to update room details.
    """
    try:
        room = get_object_or_404(RoomType, id=room_id)
        
        # Update fields
        room.name = request.POST.get('name', room.name)
        room.base_rate = Decimal(request.POST.get('base_rate', room.base_rate))
        room.room_index = Decimal(request.POST.get('room_index', room.room_index))
        room.room_adjustment = Decimal(request.POST.get('room_adjustment', room.room_adjustment))
        room.pricing_method = request.POST.get('pricing_method', room.pricing_method)
        room.number_of_rooms = int(request.POST.get('number_of_rooms', room.number_of_rooms))
        room.sort_order = int(request.POST.get('sort_order', room.sort_order))
        
        room.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Room updated successfully',
            'room': {
                'id': room.id,
                'name': room.name,
                'base_rate': str(room.base_rate),
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)

@require_POST
def update_season(request, season_id):
    """
    AJAX endpoint to update season details.
    """
    try:
        season = get_object_or_404(Season, id=season_id)
        
        # Update fields
        season.name = request.POST.get('name', season.name)
        season.start_date = request.POST.get('start_date', season.start_date)
        season.end_date = request.POST.get('end_date', season.end_date)
        season.season_index = Decimal(request.POST.get('season_index', season.season_index))
        season.expected_occupancy = Decimal(request.POST.get('expected_occupancy', season.expected_occupancy))
        
        season.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Season updated successfully',
            'season': {
                'id': season.id,
                'name': season.name,
                'season_index': str(season.season_index),
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)

def parity_data_ajax(request):
    """
    AJAX endpoint to return parity data for a specific season.
    """
    from django.template.loader import render_to_string
    
    season_id = request.GET.get('season')
    
    try:
        from .services import calculate_final_rate_with_modifier
        
        # Get data
        seasons = Season.objects.all().order_by('start_date')
        rooms = RoomType.objects.all()
        channels = Channel.objects.all()
        rate_plans = RatePlan.objects.all()
        
        if not all([seasons.exists(), rooms.exists(), channels.exists(), rate_plans.exists()]):
            return JsonResponse({'success': False, 'message': 'Missing required data'})
        
        # Get selected season
        if season_id:
            try:
                parity_season = Season.objects.get(id=season_id)
            except (Season.DoesNotExist, ValueError):
                parity_season = seasons.first()
        else:
            parity_season = seasons.first()
        
        parity_room = rooms.first()
        parity_rate_plan = rate_plans.first()
        
        # Calculate BAR
        bar_rate, _ = calculate_final_rate_with_modifier(
            room_base_rate=parity_room.get_effective_base_rate(),
            season_index=parity_season.season_index,
            meal_supplement=parity_rate_plan.meal_supplement,
            channel_base_discount=Decimal('0.00'),
            modifier_discount=Decimal('0.00'),
            commission_percent=Decimal('0.00'),
            occupancy=2
        )
        
        # Calculate parity for each channel
        parity_data = []
        for channel in channels:
            # Try to get modifiers
            season_discount = Decimal('0.00')
            try:
                from .models import RateModifier
                modifiers = RateModifier.objects.filter(channel=channel, active=True)
                
                if modifiers.exists():
                    modifier = modifiers.filter(discount_percent=0).first()
                    if not modifier:
                        modifier = modifiers.first()
                    season_discount = modifier.get_discount_for_season(parity_season)
            except:
                pass
            
            channel_rate, breakdown = calculate_final_rate_with_modifier(
                room_base_rate=parity_room.get_effective_base_rate(),
                season_index=parity_season.season_index,
                meal_supplement=parity_rate_plan.meal_supplement,
                channel_base_discount=channel.base_discount_percent,
                modifier_discount=season_discount,
                commission_percent=channel.commission_percent,
                occupancy=2
            )
            
            # Calculate difference
            difference = channel_rate - bar_rate
            difference_percent = (difference / bar_rate * 100) if bar_rate > 0 else Decimal('0.00')
            
            # Determine status
            if abs(difference_percent) < Decimal('1.0'):
                status = 'good'
                status_text = 'At Parity'
            elif difference_percent < 0:
                status = 'warning'
                status_text = 'Below BAR'
            else:
                status = 'info'
                status_text = 'Above BAR'
            
            parity_data.append({
                'channel': channel,
                'rate': channel_rate,
                'bar_rate': bar_rate,
                'difference': difference,
                'difference_percent': difference_percent,
                'status': status,
                'status_text': status_text,
                'net_revenue': breakdown['net_revenue'],
            })
        
        # Render partial template
        html = render_to_string('pricing/partials/parity_table.html', {
            'parity_data': parity_data,
        })
        
        return JsonResponse({
            'success': True,
            'html': html,
            'season_name': parity_season.name,
            'room_name': parity_room.name,
            'rate_plan_name': parity_rate_plan.name,
        })
    
    except Exception as e:
        import traceback
        print(f"Parity AJAX error: {e}")
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    
@require_GET
def revenue_forecast_ajax(request):
    """
    AJAX endpoint to return revenue AND occupancy forecast data.
    
    Returns JSON with:
    - Revenue forecast HTML (with ADR and room nights)
    - Occupancy forecast HTML
    - Annual totals including ADR and room nights
    - Validation status
    """
    try:
        from pricing.services import RevenueForecastService
        from pricing.models import Channel
        
        forecast_service = RevenueForecastService()
        
        # Get monthly revenue forecast
        monthly_forecast = forecast_service.calculate_monthly_forecast()
        
        # Get occupancy forecast
        occupancy_forecast = forecast_service.calculate_occupancy_forecast()
        
        if not monthly_forecast:
            # Render setup message
            html = render_to_string('pricing/partials/revenue_forecast.html', {
                'has_forecast_data': False,
            })
            
            return JsonResponse({
                'success': True,
                'has_data': False,
                'html': html,
                'message': 'No forecast data available. Please configure channel distribution and room inventory.'
            })
        
        # Prepare revenue chart data
        forecast_months = [f"{item['month_name'][:3]}" for item in monthly_forecast]
        forecast_gross_revenue = [float(item['gross_revenue']) for item in monthly_forecast]
        forecast_net_revenue = [float(item['net_revenue']) for item in monthly_forecast]
        forecast_commission = [float(item['commission_amount']) for item in monthly_forecast]
        
        # Prepare occupancy chart data
        occupancy_months = [item['month_name'] for item in occupancy_forecast['monthly_data']]
        occupancy_percentages = [item['occupancy_percent'] for item in occupancy_forecast['monthly_data']]
        
        # Calculate annual totals
        annual_gross = sum(item['gross_revenue'] for item in monthly_forecast)
        annual_net = sum(item['net_revenue'] for item in monthly_forecast)
        annual_commission = sum(item['commission_amount'] for item in monthly_forecast)
        
        # 🔧 FIX 1: Calculate annual room nights
        annual_room_nights = sum(item['occupied_room_nights'] for item in monthly_forecast)
        
        # 🔧 FIX 2: Calculate annual ADR (Gross Revenue / Room Nights)
        annual_adr = (annual_gross / annual_room_nights) if annual_room_nights > 0 else Decimal('0.00')
        
        # Get channel breakdown
        channels = Channel.objects.all()
        channel_data = []
        for channel in channels:
            channel_gross = sum(
                sum(ch['gross_revenue'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            channel_net = sum(
                sum(ch['net_revenue'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            channel_commission = sum(
                sum(ch['commission_amount'] for ch in item['channel_breakdown'] if ch['channel'].id == channel.id)
                for item in monthly_forecast
            )
            
            if channel_gross > 0:
                channel_data.append({
                    'name': channel.name,
                    'share_percent': float(channel.distribution_share_percent),
                    'gross_revenue': float(channel_gross),
                    'net_revenue': float(channel_net),
                    'commission': float(channel_commission),
                })
        
        # Validate distribution
        is_valid, total_dist, message = forecast_service.validate_channel_distribution()
        
        # Convert to JSON strings for templates
        revenue_chart_data = json.dumps({
            'months': forecast_months,
            'gross_revenue': forecast_gross_revenue,
            'net_revenue': forecast_net_revenue,
            'commission': forecast_commission
        })
        
        occupancy_chart_data = json.dumps({
            'months': occupancy_months,
            'occupancy': occupancy_percentages
        })
        
        # Render revenue forecast HTML
        revenue_html = render_to_string('pricing/partials/revenue_forecast.html', {
            'has_forecast_data': True,
            'annual_gross_revenue': annual_gross,
            'annual_net_revenue': annual_net,
            'annual_commission': annual_commission,
            'annual_adr': annual_adr,  # 🔧 ADDED
            'annual_room_nights': annual_room_nights,  # 🔧 ADDED
            'channel_breakdown': channel_data,
            'forecast_chart_data': revenue_chart_data,
            'distribution_valid': is_valid,
            'distribution_total': total_dist,
            'distribution_message': message,
        })
        
        # Render occupancy forecast HTML
        occupancy_html = render_to_string('pricing/partials/occupancy_forecast.html', {
            'has_occupancy_data': True,
            'occupancy_chart_data': occupancy_chart_data,
            'annual_metrics': occupancy_forecast['annual_metrics'],
            'seasonal_data': occupancy_forecast['seasonal_data'],
        })
        
        return JsonResponse({
            'success': True,
            'has_data': True,
            'revenue_html': revenue_html,
            'occupancy_html': occupancy_html,
            'annual_gross': float(annual_gross),
            'annual_net': float(annual_net),
            'annual_adr': float(annual_adr),  # 🔧 ADDED to JSON response
            'annual_room_nights': int(annual_room_nights),  # 🔧 ADDED to JSON response
            'distribution_valid': is_valid,
        })
    
    except Exception as e:
        import traceback
        print(f"Revenue forecast error: {e}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)
        
        
        
#Pickup Analysis 

class PickupDashboardView(TemplateView):
    """
    Main pickup analysis dashboard.
    
    Shows:
    - KPI cards (velocity, OTB, lead time)
    - Forecast overview table for next 6 months
    - Booking pace chart
    - Lead time distribution
    - Pickup curves by season
    """
    template_name = 'pricing/pickup_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.models import (
            DailyPickupSnapshot, MonthlyPickupSnapshot, 
            PickupCurve, OccupancyForecast, RoomType
        )
        from pricing.services import PickupAnalysisService
        
        service = PickupAnalysisService()
        today = date.today()
        
        # Check if we have any data
        has_data = MonthlyPickupSnapshot.objects.exists()
        context['has_data'] = has_data
        
        if not has_data:
            return context
        
        # =====================================================================
        # KPI CARDS
        # =====================================================================
        
        # Bookings this week
        week_ago = today - timedelta(days=7)
        recent_snapshots = MonthlyPickupSnapshot.objects.filter(
            snapshot_date__gte=week_ago,
            snapshot_date__lte=today
        )
        
        # Calculate total pickup this week across all months
        weekly_pickup = 0
        for target_month in recent_snapshots.values_list('target_month', flat=True).distinct():
            latest = recent_snapshots.filter(
                target_month=target_month, 
                snapshot_date=today
            ).first()
            earliest = MonthlyPickupSnapshot.objects.filter(
                target_month=target_month,
                snapshot_date__lte=week_ago
            ).order_by('-snapshot_date').first()
            
            if latest and earliest:
                weekly_pickup += latest.otb_room_nights - earliest.otb_room_nights
        
        # Total OTB for next 90 days
        next_90_days = today + timedelta(days=90)
        total_otb = MonthlyPickupSnapshot.objects.filter(
            snapshot_date=today,
            target_month__lte=next_90_days
        ).aggregate(
            total_nights=models.Sum('otb_room_nights'),
            total_revenue=models.Sum('otb_revenue')
        )
        
        # Calculate occupancy for next 90 days
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        available_90_days = total_rooms * 90
        otb_occupancy_90 = Decimal('0.00')
        if available_90_days > 0 and total_otb['total_nights']:
            otb_occupancy_90 = (
                Decimal(str(total_otb['total_nights'])) / 
                Decimal(str(available_90_days)) * Decimal('100.00')
            ).quantize(Decimal('0.1'))
        
        # Booking velocity
        velocity_data = {}
        next_month = (today + relativedelta(months=1)).replace(day=1)
        velocity = service.calculate_booking_velocity(next_month)
        
        context['kpis'] = {
            'weekly_pickup': weekly_pickup,
            'total_otb_nights': total_otb.get('total_nights') or 0,
            'total_otb_revenue': total_otb.get('total_revenue') or Decimal('0.00'),
            'otb_occupancy_90': otb_occupancy_90,
            'daily_velocity': velocity.get('daily_room_nights', Decimal('0.00')),
            'velocity_trend': velocity.get('velocity_trend', 'stable'),
        }
        
        # =====================================================================
        # FORECAST OVERVIEW (Next 6 Months)
        # =====================================================================
        forecast_summary = service.get_forecast_summary(months_ahead=6)
        context['forecast_summary'] = forecast_summary
        
        # =====================================================================
        # LEAD TIME ANALYSIS
        # =====================================================================
        # Get lead time distribution for last 3 months
        three_months_ago = today - timedelta(days=90)
        lead_time_data = service.analyze_lead_time_distribution(three_months_ago, today)
        context['lead_time_data'] = lead_time_data
        
        # =====================================================================
        # PICKUP CURVES
        # =====================================================================
        curves = {}
        for season_type in ['peak', 'high', 'shoulder', 'low']:
            curve_data = PickupCurve.objects.filter(
                season_type=season_type,
                season__isnull=True
            ).order_by('-days_out')
            
            if curve_data.exists():
                curves[season_type] = [
                    {'days_out': c.days_out, 'percent': float(c.cumulative_percent)}
                    for c in curve_data
                ]
            else:
                # Use defaults
                default_curves = service.get_default_pickup_curves()
                curves[season_type] = [
                    {'days_out': d, 'percent': p}
                    for d, p in default_curves[season_type]
                ]
        
        context['pickup_curves'] = curves
        
        return context


# =============================================================================
# PICKUP DETAIL VIEW (Monthly)
# =============================================================================

class PickupDetailView(TemplateView):
    """
    Detailed pickup analysis for a specific month.
    
    Shows:
    - Full forecast breakdown (OTB, Pickup, Scenario)
    - Revenue projections
    - Booking pace vs STLY chart
    - Channel breakdown
    - Daily OTB progression table
    """
    template_name = 'pricing/pickup_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.models import (
            DailyPickupSnapshot, MonthlyPickupSnapshot, 
            OccupancyForecast, Season, RoomType
        )
        from pricing.services import PickupAnalysisService
        
        year = self.kwargs.get('year')
        month = self.kwargs.get('month')
        
        target_month = date(year, month, 1)
        context['target_month'] = target_month
        context['month_name'] = target_month.strftime('%B %Y')
        
        today = date.today()
        service = PickupAnalysisService()
        
        # Get or generate forecast
        forecast = service.generate_forecast(target_month)
        context['forecast'] = forecast
        
        if not forecast:
            context['has_data'] = False
            return context
        
        context['has_data'] = True
        
        # Get season info
        season = Season.objects.filter(
            start_date__lte=target_month,
            end_date__gte=target_month
        ).first()
        context['season'] = season
        
        # Calculate month details
        import calendar
        _, last_day = calendar.monthrange(year, month)
        context['days_in_month'] = last_day
        
        total_rooms = sum(room.number_of_rooms for room in RoomType.objects.all())
        context['total_rooms'] = total_rooms
        context['available_room_nights'] = total_rooms * last_day
        
        # =====================================================================
        # BOOKING PACE DATA (for chart)
        # =====================================================================
        # Get historical snapshots for this month
        pace_data = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month
        ).order_by('snapshot_date').values(
            'snapshot_date', 'days_out', 'otb_room_nights', 'otb_occupancy_percent'
        )
        
        context['pace_data'] = list(pace_data)
        
        # Get STLY pace data
        stly_month = target_month - relativedelta(years=1)
        stly_pace_data = MonthlyPickupSnapshot.objects.filter(
            target_month=stly_month
        ).order_by('snapshot_date').values(
            'snapshot_date', 'days_out', 'otb_room_nights', 'otb_occupancy_percent'
        )
        
        context['stly_pace_data'] = list(stly_pace_data)
        
        # =====================================================================
        # CHANNEL BREAKDOWN
        # =====================================================================
        latest_snapshot = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month
        ).order_by('-snapshot_date').first()
        
        if latest_snapshot and latest_snapshot.otb_by_channel:
            channel_breakdown = []
            total_nights = latest_snapshot.otb_room_nights
            
            for channel_name, nights in latest_snapshot.otb_by_channel.items():
                channel_breakdown.append({
                    'channel': channel_name,
                    'room_nights': nights,
                    'percent': (
                        Decimal(str(nights)) / Decimal(str(total_nights)) * 100
                        if total_nights > 0 else Decimal('0.00')
                    ).quantize(Decimal('0.1'))
                })
            
            context['channel_breakdown'] = sorted(
                channel_breakdown, 
                key=lambda x: x['room_nights'], 
                reverse=True
            )
        
        # =====================================================================
        # ROOM TYPE BREAKDOWN
        # =====================================================================
        if latest_snapshot and latest_snapshot.otb_by_room_type:
            room_type_breakdown = []
            total_nights = latest_snapshot.otb_room_nights
            
            for room_type, nights in latest_snapshot.otb_by_room_type.items():
                room_type_breakdown.append({
                    'room_type': room_type,
                    'room_nights': nights,
                    'percent': (
                        Decimal(str(nights)) / Decimal(str(total_nights)) * 100
                        if total_nights > 0 else Decimal('0.00')
                    ).quantize(Decimal('0.1'))
                })
            
            context['room_type_breakdown'] = sorted(
                room_type_breakdown,
                key=lambda x: x['room_nights'],
                reverse=True
            )
        
        # =====================================================================
        # DAILY OTB PROGRESSION (Last 14 days)
        # =====================================================================
        two_weeks_ago = today - timedelta(days=14)
        daily_progression = MonthlyPickupSnapshot.objects.filter(
            target_month=target_month,
            snapshot_date__gte=two_weeks_ago
        ).order_by('-snapshot_date')
        
        progression_list = []
        prev_nights = None
        
        for snapshot in daily_progression:
            pickup = 0
            if prev_nights is not None:
                pickup = prev_nights - snapshot.otb_room_nights
            
            progression_list.append({
                'date': snapshot.snapshot_date,
                'otb_nights': snapshot.otb_room_nights,
                'otb_revenue': snapshot.otb_revenue,
                'days_out': snapshot.days_out,
                'pickup': pickup,
                'occupancy': snapshot.otb_occupancy_percent,
            })
            
            prev_nights = snapshot.otb_room_nights
        
        context['daily_progression'] = progression_list
        
        # =====================================================================
        # FORECAST HISTORY (how forecast evolved)
        # =====================================================================
        forecast_history = OccupancyForecast.objects.filter(
            target_month=target_month
        ).order_by('-forecast_date')[:14]
        
        context['forecast_history'] = forecast_history
        
        return context


# =============================================================================
# AJAX ENDPOINTS
# =============================================================================

@require_GET
def pickup_summary_ajax(request):
    """
    AJAX endpoint for pickup summary card on home dashboard.
    
    Returns HTML partial for the pickup summary section.
    """
    from pricing.services import PickupAnalysisService
    from pricing.models import MonthlyPickupSnapshot
    
    service = PickupAnalysisService()
    
    # Check if we have data
    has_data = MonthlyPickupSnapshot.objects.exists()
    
    if not has_data:
        html = render_to_string('pricing/partials/pickup_summary.html', {
            'has_data': False,
        })
        return JsonResponse({'success': True, 'html': html, 'has_data': False})
    
    # Get forecast summary for next 3 months
    forecast_summary = service.get_forecast_summary(months_ahead=3)
    
    # Get velocity
    today = date.today()
    next_month = (today + relativedelta(months=1)).replace(day=1)
    velocity = service.calculate_booking_velocity(next_month)
    
    # Find any alerts
    alerts = []
    for forecast in forecast_summary:
        if forecast.get('vs_stly_pace') and forecast['vs_stly_pace'] < -5:
            alerts.append({
                'month': forecast['month_name'],
                'message': f"{forecast['month_name']} is {abs(forecast['vs_stly_pace']):.1f}% behind STLY pace",
                'type': 'warning'
            })
        elif forecast.get('variance_percent') and forecast['variance_percent'] < -10:
            alerts.append({
                'month': forecast['month_name'],
                'message': f"{forecast['month_name']} pickup forecast is below scenario target",
                'type': 'info'
            })
    
    html = render_to_string('pricing/partials/pickup_summary.html', {
        'has_data': True,
        'forecast_summary': forecast_summary,
        'velocity': velocity,
        'alerts': alerts[:2],  # Max 2 alerts
    })
    
    return JsonResponse({
        'success': True,
        'html': html,
        'has_data': True,
    })


@require_GET  
def forecast_data_ajax(request, year, month):
    """
    AJAX endpoint for forecast data for a specific month.
    
    Returns JSON with forecast details for charts.
    """
    from pricing.services import PickupAnalysisService
    from pricing.models import MonthlyPickupSnapshot, OccupancyForecast
    
    target_month = date(year, month, 1)
    service = PickupAnalysisService()
    
    # Generate forecast
    forecast = service.generate_forecast(target_month)
    
    if not forecast:
        return JsonResponse({
            'success': False,
            'message': 'Unable to generate forecast'
        })
    
    # Get pace data for chart
    pace_data = MonthlyPickupSnapshot.objects.filter(
        target_month=target_month
    ).order_by('snapshot_date').values(
        'snapshot_date', 'days_out', 'otb_room_nights', 'otb_occupancy_percent'
    )
    
    # Get STLY pace
    stly_month = target_month - relativedelta(years=1)
    stly_pace = MonthlyPickupSnapshot.objects.filter(
        target_month=stly_month
    ).order_by('snapshot_date').values(
        'snapshot_date', 'days_out', 'otb_room_nights', 'otb_occupancy_percent'
    )
    
    return JsonResponse({
        'success': True,
        'forecast': {
            'target_month': target_month.isoformat(),
            'days_out': forecast.days_out,
            'otb_room_nights': forecast.otb_room_nights,
            'otb_occupancy': float(forecast.otb_occupancy_percent),
            'pickup_forecast_nights': forecast.pickup_forecast_nights,
            'pickup_forecast_occupancy': float(forecast.pickup_forecast_occupancy),
            'pickup_forecast_revenue': float(forecast.pickup_forecast_revenue),
            'scenario_occupancy': float(forecast.scenario_occupancy),
            'scenario_room_nights': forecast.scenario_room_nights,
            'variance_nights': forecast.variance_nights,
            'variance_percent': float(forecast.variance_percent),
            'vs_stly_pace': float(forecast.vs_stly_pace_percent) if forecast.vs_stly_pace_percent else None,
            'confidence': forecast.confidence_level,
            'insight': forecast.notes,
        },
        'pace_data': [
            {
                'date': p['snapshot_date'].isoformat(),
                'days_out': p['days_out'],
                'otb_nights': p['otb_room_nights'],
                'otb_occupancy': float(p['otb_occupancy_percent']),
            }
            for p in pace_data
        ],
        'stly_pace_data': [
            {
                'date': p['snapshot_date'].isoformat(),
                'days_out': p['days_out'],
                'otb_nights': p['otb_room_nights'],
                'otb_occupancy': float(p['otb_occupancy_percent']),
            }
            for p in stly_pace
        ],
    })


@require_GET
def pickup_curves_ajax(request):
    """
    AJAX endpoint for pickup curves data.
    
    Returns JSON with curve data for all season types.
    """
    from pricing.models import PickupCurve
    from pricing.services import PickupAnalysisService
    
    service = PickupAnalysisService()
    
    curves = {}
    for season_type in ['peak', 'high', 'shoulder', 'low']:
        curve_data = PickupCurve.objects.filter(
            season_type=season_type,
            season__isnull=True
        ).order_by('-days_out')
        
        if curve_data.exists():
            curves[season_type] = [
                {
                    'days_out': c.days_out, 
                    'percent': float(c.cumulative_percent),
                    'std_dev': float(c.std_deviation),
                }
                for c in curve_data
            ]
        else:
            # Use defaults
            default_curves = service.get_default_pickup_curves()
            curves[season_type] = [
                {'days_out': d, 'percent': p, 'std_dev': 0}
                for d, p in default_curves[season_type]
            ]
    
    return JsonResponse({
        'success': True,
        'curves': curves,
    })
    

"""
Booking Analysis Views.

Add these to your existing pricing/views.py file.
"""

from django.views.generic import TemplateView
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from datetime import date
import json


class BookingAnalysisDashboardView(TemplateView):
    """
    Booking Analysis Dashboard.
    
    Shows:
    - KPI cards (Revenue, Room Nights, ADR, Occupancy, Reservations)
    - Monthly revenue chart
    - Monthly occupancy chart
    - Channel mix pie chart & table
    - Meal plan mix pie chart & table
    - Room type performance table
    - Monthly summary table
    """
    template_name = 'pricing/booking_analysis_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        from pricing.services import BookingAnalysisService
        from pricing.models import Reservation, Property
        
        # Get year from query param or default to current year
        year = self.request.GET.get('year')
        if year:
            try:
                year = int(year)
            except ValueError:
                year = date.today().year
        else:
            year = date.today().year
        
        # Check if we have any data
        has_data = Reservation.objects.exists()
        context['has_data'] = has_data
        
        if not has_data:
            context['year'] = year
            return context
        
        # Get dashboard data
        service = BookingAnalysisService()
        dashboard_data = service.get_dashboard_data(year=year)
        chart_data = service.get_chart_data(year=year)
        
        # Get property info
        try:
            property_obj = Property.get_instance()
            context['property_name'] = property_obj.name
            context['currency_symbol'] = property_obj.currency_symbol
        except:
            context['property_name'] = 'Hotel'
            context['currency_symbol'] = '$'
        
        # Pass data to template
        context['year'] = year
        context['total_rooms'] = dashboard_data['total_rooms']
        context['kpis'] = dashboard_data['kpis']
        context['monthly_data'] = dashboard_data['monthly_data']
        context['channel_mix'] = dashboard_data['channel_mix']
        context['meal_plan_mix'] = dashboard_data['meal_plan_mix']
        context['room_type_performance'] = dashboard_data['room_type_performance']
        
        # Chart data as JSON for JavaScript
        context['chart_data_json'] = json.dumps(chart_data)
        
        # Available years for selector
        years_with_data = Reservation.objects.dates('arrival_date', 'year')
        context['available_years'] = [d.year for d in years_with_data]
        
        # Reservation count for subtitle
        context['reservation_count'] = Reservation.objects.filter(
            arrival_date__year=year,
            status__in=['confirmed', 'checked_in', 'checked_out']
        ).count()
        
        return context


@require_GET
def booking_analysis_data_ajax(request):
    """
    AJAX endpoint to get booking analysis data.
    
    Query params:
        year: Year to filter by (default: current year)
    
    Returns:
        JSON with dashboard data
    """
    from pricing.services import BookingAnalysisService
    
    year = request.GET.get('year')
    if year:
        try:
            year = int(year)
        except ValueError:
            year = date.today().year
    else:
        year = date.today().year
    
    service = BookingAnalysisService()
    dashboard_data = service.get_dashboard_data(year=year)
    chart_data = service.get_chart_data(year=year)
    
    # Convert Decimals to floats for JSON
    kpis = dashboard_data['kpis']
    
    return JsonResponse({
        'success': True,
        'year': year,
        'kpis': {
            'total_revenue': float(kpis['total_revenue']),
            'room_nights': kpis['room_nights'],
            'avg_adr': float(kpis['avg_adr']),
            'avg_occupancy': float(kpis['avg_occupancy']),
            'reservations': kpis['reservations'],
        },
        'chart_data': chart_data,
        'channel_mix': [
            {
                'name': c['name'],
                'bookings': c['bookings'],
                'revenue': float(c['revenue']),
                'percent': float(c['percent']),
            }
            for c in dashboard_data['channel_mix']
        ],
        'meal_plan_mix': [
            {
                'name': m['name'],
                'bookings': m['bookings'],
                'revenue': float(m['revenue']),
                'percent': float(m['percent']),
            }
            for m in dashboard_data['meal_plan_mix']
        ],
        'room_type_performance': [
            {
                'name': r['name'],
                'bookings': r['bookings'],
                'revenue': float(r['revenue']),
                'percent': float(r['percent']),
            }
            for r in dashboard_data['room_type_performance']
        ],
        'monthly_data': [
            {
                'month': m['month'],
                'month_name': m['month_name'],
                'revenue': float(m['revenue']),
                'room_nights': m['room_nights'],
                'available': m['available'],
                'occupancy': float(m['occupancy']),
                'adr': float(m['adr']),
            }
            for m in dashboard_data['monthly_data']
        ],
    })