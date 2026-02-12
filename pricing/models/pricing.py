"""
Pricing models: Season, RoomType, RatePlan, Channel, RateModifier,
SeasonModifierOverride, DateRateOverride, DateRateOverridePeriod.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date, timedelta
import re

from .core import Property

# =============================================================================
# PROPERTY-SPECIFIC MODELS
# =============================================================================

class Season(models.Model):
    """
    Pricing season with date range and index multiplier.
    PROPERTY-SPECIFIC: Each property has its own seasons.
    
    Example:
        Low Season: Jan 11 - Mar 30, Index 1.0
        High Season: Jun 1 - Oct 30, Index 1.3
    """
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='seasons',
        help_text="Property this season belongs to"
    )
    name = models.CharField(max_length=100, help_text="e.g., Low Season, High Season")
    start_date = models.DateField()
    end_date = models.DateField()
    season_index = models.DecimalField(
        max_digits=4, 
        decimal_places=2, 
        default=Decimal('1.00'),
        help_text="Multiplier for base rates (e.g., 1.0, 1.3)"
    )
    
    expected_occupancy = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('70.00'),
        help_text="Expected occupancy % for this season (e.g., 70.00 for 70%)"
    )
    
    class Meta:
        ordering = ['hotel', 'start_date']
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
    
    def __str__(self):
        return f"{self.name} ({self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d')})"
    
    def date_range_display(self):
        """Display formatted date range."""
        return f"{self.start_date.strftime('%b %d, %Y')} - {self.end_date.strftime('%b %d, %Y')}"
    
    def get_occupancy_display(self):
        """Display formatted occupancy percentage."""
        return f"{self.expected_occupancy}%"
    
    def calculate_adr(self, room_mix=None, rate_plan_mix=None, channel_mix=None):
        """
        Calculate Average Daily Rate (ADR) for this season.
        
        Args:
            room_mix: Dict of {room_id: percentage} (e.g., {1: 0.4, 2: 0.6})
            rate_plan_mix: Dict of {rate_plan_id: percentage}
            channel_mix: Dict of {channel_id: percentage}
        
        Returns:
            Decimal: Weighted ADR for the season
        """
        from .services import calculate_final_rate_with_modifier
        
        total_revenue = Decimal('0.00')
        total_weight = Decimal('0.00')
        
        # Get property-specific room types
        rooms = self.hotel.room_types.all()
        rate_plans = RatePlan.objects.all()  # Shared
        channels = Channel.objects.all()  # Shared
        
        if not rooms.exists():
            return Decimal('0.00')
        
        # Default to equal mix if not provided
        if not room_mix:
            room_mix = {room.id: Decimal('1.00') / rooms.count() for room in rooms}
        if not rate_plan_mix and rate_plans.exists():
            rate_plan_mix = {plan.id: Decimal('1.00') / rate_plans.count() for plan in rate_plans}
        if not channel_mix and channels.exists():
            channel_mix = {channel.id: Decimal('1.00') / channels.count() for channel in channels}
        
        for room in rooms:
            room_weight = room_mix.get(room.id, Decimal('0.00'))
            if room_weight == 0:
                continue
                
            for rate_plan in rate_plans:
                plan_weight = rate_plan_mix.get(rate_plan.id, Decimal('0.00'))
                if plan_weight == 0:
                    continue
                    
                for channel in channels:
                    channel_weight = channel_mix.get(channel.id, Decimal('0.00'))
                    if channel_weight == 0:
                        continue
                    
                    # Get active modifiers for this channel
                    modifiers = channel.rate_modifiers.filter(active=True)
                    
                    # If no modifiers, calculate with base channel discount
                    if not modifiers.exists():
                        final_rate, _ = calculate_final_rate_with_modifier(
                            room_base_rate=room.get_effective_base_rate(),
                            season_index=self.season_index,
                            meal_supplement=rate_plan.meal_supplement,
                            channel_base_discount=channel.base_discount_percent,
                            modifier_discount=Decimal('0.00'),
                            commission_percent=channel.commission_percent,
                            occupancy=2
                        )
                        
                        weight = room_weight * plan_weight * channel_weight
                        total_revenue += final_rate * weight
                        total_weight += weight
                    else:
                        # Distribute evenly across modifiers
                        modifier_weight = Decimal('1.00') / modifiers.count()
                        
                        for modifier in modifiers:
                            season_discount = modifier.get_discount_for_season(self)
                            
                            final_rate, _ = calculate_final_rate_with_modifier(
                                room_base_rate=room.get_effective_base_rate(),
                                season_index=self.season_index,
                                meal_supplement=rate_plan.meal_supplement,
                                channel_base_discount=channel.base_discount_percent,
                                modifier_discount=season_discount,
                                commission_percent=channel.commission_percent,
                                occupancy=2
                            )
                            
                            weight = room_weight * plan_weight * channel_weight * modifier_weight
                            total_revenue += final_rate * weight
                            total_weight += weight
        
        if total_weight > 0:
            return (total_revenue / total_weight).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def calculate_revpar(self, room_mix=None, rate_plan_mix=None, channel_mix=None):
        """
        Calculate RevPAR (Revenue Per Available Room) for this season.
        RevPAR = ADR × Occupancy Rate
        """
        adr = self.calculate_adr(room_mix, rate_plan_mix, channel_mix)
        occupancy_decimal = self.expected_occupancy / Decimal('100.00')
        return (adr * occupancy_decimal).quantize(Decimal('0.01'))


class RoomType(models.Model):
    """
    Room category with flexible pricing.
    PROPERTY-SPECIFIC: Each property has its own room types.
    
    Pricing Methods:
    1. Direct base_rate: Simple, each room has its own rate
    2. Index multiplier: Property.reference_base_rate × room_index
    3. Fixed adjustment: Property.reference_base_rate + room_adjustment
    """
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='room_types',
        help_text="Property this room type belongs to"
    )
    name = models.CharField(max_length=100, help_text="e.g., Standard Room, Deluxe Room, Suite")
    
    base_rate = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Base rate in USD (used directly or as reference)"
    )
    
    room_index = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text="Multiplier for property reference rate"
    )
    
    room_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Fixed amount to add to property reference rate"
    )
    
    PRICING_METHODS = [
        ('direct', 'Direct Base Rate'),
        ('index', 'Index Multiplier'),
        ('adjustment', 'Fixed Adjustment'),
    ]
    pricing_method = models.CharField(
        max_length=20,
        choices=PRICING_METHODS,
        default='index',
        help_text="How to calculate room rate"
    )
    
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order")
    
    number_of_rooms = models.PositiveIntegerField(
        default=10,
        help_text="Number of rooms of this type"
    )
    
    description = models.TextField(
        blank=True,
        default='',
        help_text="Room features/description (e.g., 'Ocean view, balcony, premium amenities')"
    )
    
    target_occupancy = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('70.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Target occupancy % for this room type (e.g., 75.00 for 75%)"
    )
    
    class Meta:
        ordering = ['hotel', 'sort_order', 'name']
        verbose_name = "Room Type"
        verbose_name_plural = "Room Types"
    
    def __str__(self):
        count_str = f" ({self.number_of_rooms} rooms)" if self.number_of_rooms else ""
        if self.pricing_method == 'index':
            return f"{self.name} (×{self.room_index}){count_str}"
        elif self.pricing_method == 'adjustment':
            return f"{self.name} (+${self.room_adjustment}){count_str}"
        elif self.pricing_method == 'direct':
            return f"{self.name} (${self.base_rate}){count_str}"
        return f"{self.name}{count_str}"
    
    def get_effective_base_rate(self, reference_rate=None):
        """Calculate the effective base rate for this room type."""
        if self.pricing_method == 'direct':
            return self.base_rate
        
        # Get reference rate from Property if not provided
        if reference_rate is None:
            ref_rate = self.hotel.reference_base_rate if self.hotel else self.base_rate
        else:
            ref_rate = reference_rate
        
        if self.pricing_method == 'index':
            return ref_rate * self.room_index
        elif self.pricing_method == 'adjustment':
            return ref_rate + self.room_adjustment
        
        return self.base_rate
    
    def get_premium_percent(self):
        """Calculate premium % vs property reference rate."""
        ref = self.hotel.reference_base_rate if self.hotel else self.base_rate
        if ref and ref > 0:
            effective = self.get_effective_base_rate()
            return ((effective - ref) / ref * Decimal('100')).quantize(Decimal('0.1'))
        return Decimal('0.0')
    
    def get_season_modifier(self, season):
        """
        Get the room-type-specific season modifier for a given season.
        Returns the modifier value (default 1.00 if none set).
        """
        try:
            override = self.season_modifiers.get(season=season)
            return override.modifier
        except RoomTypeSeasonModifier.DoesNotExist:
            return Decimal('1.00')
    
    def get_effective_season_index(self, season):
        """
        Calculate effective season index = season_index × room_type_season_modifier.
        This is the combined multiplier applied to the base rate.
        """
        return (season.season_index * self.get_season_modifier(season)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )


# =============================================================================
# SHARED MODELS (Organization-level or Global)
# =============================================================================

class RatePlan(models.Model):
    """
    Board type with meal supplement per person.
    SHARED: Same rate plans available across all properties.
    
    Example:
        Bed & Breakfast: $6 per person
        Half Board: $12 per person
    """
    name = models.CharField(max_length=100, help_text="e.g., Room Only, Bed & Breakfast")
    meal_supplement = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Meal cost per person in USD"
    )
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Rate Plan"
        verbose_name_plural = "Rate Plans"
    
    def __str__(self):
        if self.meal_supplement > 0:
            return f"{self.name} (+${self.meal_supplement}/person)"
        return f"{self.name} (Room Only)"


class Channel(models.Model):
    """
    Booking channel with discount and commission.
    SHARED: Same channels available across all properties.
    
    Pricing Flow:
    1. BAR (Base Available Rate) = room + season + meals
    2. Channel Base Rate = BAR - base_discount_percent
    3. Final Rate = Channel Base Rate - modifier.discount_percent
    """
    name = models.CharField(max_length=100, help_text="e.g., OTA, DIRECT, Agent")
    base_discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Base channel discount from BAR"
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Commission the channel takes"
    )
    
    distribution_share_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Expected % of bookings from this channel"
    )
    
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Channel"
        verbose_name_plural = "Channels"
    
    def __str__(self):
        parts = [self.name]
        if self.base_discount_percent > 0:
            parts.append(f"-{self.base_discount_percent}% discount")
        if self.commission_percent > 0:
            parts.append(f"({self.commission_percent}% commission)")
        return " ".join(parts)
    
    def discount_display(self):
        if self.base_discount_percent > 0:
            return f"{self.base_discount_percent}% discount"
        return "No discount"
    
    def commission_display(self):
        if self.commission_percent > 0:
            return f"{self.commission_percent}% commission"
        return "No commission"
    
    def distribution_display(self):
        if self.distribution_share_percent > 0:
            return f"{self.distribution_share_percent}% of bookings"
        return "No distribution set"

    @classmethod
    def validate_total_distribution(cls):
        """Validate that total distribution shares equal 100%."""
        total = cls.objects.aggregate(
            total=models.Sum('distribution_share_percent')
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
    
    @classmethod
    def get_distribution_mix(cls):
        """Get channel distribution as a dictionary."""
        return {
            channel.id: channel.distribution_share_percent / Decimal('100.00')
            for channel in cls.objects.filter(distribution_share_percent__gt=0)
        }
    
    @classmethod
    def normalize_distribution(cls):
        """Auto-normalize distribution shares to sum to 100%."""
        channels = cls.objects.filter(distribution_share_percent__gt=0)
        if not channels.exists():
            return
        
        total = channels.aggregate(total=Sum('distribution_share_percent'))['total'] or Decimal('0.00')
        if total == Decimal('0.00'):
            return
        
        factor = Decimal('100.00') / total
        for channel in channels:
            channel.distribution_share_percent = (
                channel.distribution_share_percent * factor
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            channel.save()
    
    @classmethod
    def distribute_equally(cls):
        """Set equal distribution across all channels."""
        channels = cls.objects.all()
        if not channels.exists():
            return
        
        share = (Decimal('100.00') / channels.count()).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        for channel in channels:
            channel.distribution_share_percent = share
            channel.save()


class RateModifier(models.Model):
    """
    Additional discount modifiers for channels.
    SHARED: Linked to shared Channel model.
    
    Example: Genius, Mobile App, Newsletter discounts
    """
    channel = models.ForeignKey(
        Channel, 
        on_delete=models.CASCADE,
        related_name='rate_modifiers',
        help_text="Which channel this modifier applies to"
    )
    name = models.CharField(
        max_length=100, 
        help_text="e.g., 'Genius Member', 'Mobile App'"
    )
    discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Additional discount % from channel base rate"
    )
    
     # Stacking fields
    stackable = models.BooleanField(
        default=False,
        help_text="Can this modifier be stacked with other stackable modifiers?"
    )
    is_stacked = models.BooleanField(
        default=False,
        help_text="Is this a combined/stacked modifier?"
    )
    stacked_from = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='stacked_into',
        help_text="Source modifiers if this is a stacked modifier"
    )
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    MODIFIER_TYPES = [
        ('standard', 'Standard Rate'),
        ('member', 'Member/Loyalty Program'),
        ('mobile', 'Mobile App Exclusive'),
        ('promo', 'Promotional'),
        ('corporate', 'Corporate Rate'),
        ('last_minute', 'Last Minute Deal'),
        ('early_bird', 'Early Bird'),
    ]
    modifier_type = models.CharField(
        max_length=20, 
        choices=MODIFIER_TYPES, 
        default='standard'
    )
    
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['channel', 'sort_order', 'name']
        verbose_name = "Rate Modifier"
        verbose_name_plural = "Rate Modifiers"
        unique_together = ['channel', 'name']
    
    def __str__(self):
        if self.discount_percent > 0:
            return f"{self.channel.name} - {self.name} (-{self.discount_percent}%)"
        return f"{self.channel.name} - {self.name}"
    
    def get_discount_for_season(self, season):
        """Get the discount percentage for a specific season."""
        season_discount, created = SeasonModifierOverride.objects.get_or_create(
            modifier=self,
            season=season,
            defaults={'discount_percent': self.discount_percent}
        )
        return season_discount.discount_percent
    
    def total_discount_from_bar(self):
        """Calculate total discount from BAR including channel base discount."""
        return self.channel.base_discount_percent + self.discount_percent


class SeasonModifierOverride(models.Model):
    """
    Season-specific discount configuration for rate modifiers.
    Links shared RateModifier to property-specific Season.
    """
    modifier = models.ForeignKey(
        RateModifier,
        on_delete=models.CASCADE,
        related_name='season_discounts'
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name='modifier_discounts'
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    is_customized = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['season', 'modifier__channel', 'modifier__sort_order']
        verbose_name = "Season Modifier Override"
        verbose_name_plural = "Season Modifier Overrides"
        unique_together = ['modifier', 'season']
    
    def __str__(self):
        return f"{self.modifier.name} → {self.season.name}: -{self.discount_percent}%"
    
    def save(self, *args, **kwargs):
        if self.pk:
            if self.discount_percent != self.modifier.discount_percent:
                self.is_customized = True
        else:
            if self.discount_percent == Decimal('0.00'):
                self.discount_percent = self.modifier.discount_percent
        super().save(*args, **kwargs)
    
    def sync_from_base(self):
        if not self.is_customized:
            self.discount_percent = self.modifier.discount_percent
            super().save()
    
    def reset_to_base(self):
        self.discount_percent = self.modifier.discount_percent
        self.is_customized = False
        super().save()


class RoomTypeSeasonModifier(models.Model):
    """
    Per-room-type, per-season multiplier that adjusts the season index
    differently for each room type.
    
    This allows premium rooms to have different seasonal sensitivity.
    For example, a Suite might maintain higher rates in low season
    (honeymoon market is less seasonal) while Standard rooms follow
    the base season index more closely.
    
    Calculation:
        effective_index = season.season_index × room_type_season_modifier
    
    Example (December, season_index=1.37):
        Standard: 1.37 × 1.00 = 1.37 (follows base index)
        Deluxe:   1.37 × 1.35 = 1.85 (amplified seasonality)
        Suite:    1.37 × 1.80 = 2.47 (strong premium in peak)
    
    Example (July low season, season_index=0.68):
        Standard: 0.68 × 1.00 = 0.68 (full low-season discount)
        Deluxe:   0.68 × 1.25 = 0.85 (smaller discount, holds value)
        Suite:    0.68 × 1.50 = 1.02 (nearly no discount)
    """
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.CASCADE,
        related_name='season_modifiers',
        help_text="Room type this modifier applies to"
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name='room_type_modifiers',
        help_text="Season this modifier applies to"
    )
    modifier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('5.00'))],
        help_text="Multiplier applied to season index for this room type "
                  "(e.g., 1.35 means 35% amplification of the season index)"
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Optional notes (e.g., 'Honeymoon market less seasonal')"
    )
    
    class Meta:
        ordering = ['season__start_date', 'room_type__sort_order']
        verbose_name = "Room Type Season Modifier"
        verbose_name_plural = "Room Type Season Modifiers"
        unique_together = ['room_type', 'season']
    
    def __str__(self):
        return f"{self.room_type.name} × {self.season.name}: ×{self.modifier}"
    
    def get_effective_index(self):
        """Calculate the effective index: season_index × this modifier."""
        return (self.season.season_index * self.modifier).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )


class DateRateOverride(models.Model):
    """
    Named rate override that applies to specific dates.
    
    The override adjusts the BAR (Best Available Rate) before channel
    and modifier discounts are applied.
    
    Priority system: When multiple overrides apply to the same date,
    the one with the highest priority wins.
    
    Examples:
        - "New Year Premium": +$50 amount, priority 90
        - "Eid Discount": -10% percentage, priority 80
        - "Weekend Boost": +$20 amount, priority 50
    """
    OVERRIDE_TYPE_CHOICES = [
        ('amount', 'Fixed Amount ($)'),
        ('percentage', 'Percentage (%)'),
    ]
    
    hotel = models.ForeignKey(
        'Property',
        on_delete=models.CASCADE,
        related_name='date_rate_overrides',
        help_text="Property this override belongs to"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Descriptive name (e.g., 'New Year Premium', 'Eid Discount')"
    )
    
    override_type = models.CharField(
        max_length=20,
        choices=OVERRIDE_TYPE_CHOICES,
        default='amount',
        help_text="How to apply the adjustment"
    )
    
    adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Adjustment value. Positive = increase, Negative = decrease. "
                  "For amount: dollars (e.g., 50 or -20). "
                  "For percentage: percent (e.g., 10 for +10%, -15 for -15%)"
    )
    
    priority = models.PositiveIntegerField(
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Priority 1-100. Higher priority wins when multiple overrides "
                  "apply to the same date. (e.g., 90 = high priority)"
    )
    
    active = models.BooleanField(
        default=True,
        help_text="Whether this override is currently active"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this override"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-priority', 'name']
        verbose_name = "Date Rate Override"
        verbose_name_plural = "Date Rate Overrides"
    
    def __str__(self):
        sign = '+' if self.adjustment >= 0 else ''
        if self.override_type == 'amount':
            adj_str = f"{sign}${self.adjustment}"
        else:
            adj_str = f"{sign}{self.adjustment}%"
        
        status = "" if self.active else " [INACTIVE]"
        return f"{self.name} ({adj_str}){status}"
    
    def get_adjustment_display(self):
        """Display formatted adjustment."""
        sign = '+' if self.adjustment >= 0 else ''
        if self.override_type == 'amount':
            return f"{sign}${self.adjustment}"
        return f"{sign}{self.adjustment}%"
    
    def get_periods_display(self):
        """Display all date periods for this override."""
        periods = self.periods.all()
        if not periods:
            return "No dates set"
        
        displays = []
        for period in periods:
            if period.start_date == period.end_date:
                displays.append(period.start_date.strftime('%b %d, %Y'))
            else:
                displays.append(
                    f"{period.start_date.strftime('%b %d')} - {period.end_date.strftime('%b %d, %Y')}"
                )
        return ", ".join(displays)
    
    def applies_to_date(self, check_date):
        """Check if this override applies to a specific date."""
        if not self.active:
            return False
        
        return self.periods.filter(
            start_date__lte=check_date,
            end_date__gte=check_date
        ).exists()
    
    def calculate_adjusted_bar(self, base_bar):
        """
        Apply this override to a BAR rate.
        
        Args:
            base_bar: Decimal - The original BAR before override
            
        Returns:
            Decimal - Adjusted BAR
        """
        if self.override_type == 'amount':
            adjusted = base_bar + self.adjustment
        else:  # percentage
            multiplier = Decimal('1.00') + (self.adjustment / Decimal('100.00'))
            adjusted = base_bar * multiplier
        
        # Don't allow negative rates
        if adjusted < Decimal('0.00'):
            adjusted = Decimal('0.00')
        
        return adjusted.quantize(Decimal('0.01'))


class DateRateOverridePeriod(models.Model):
    """
    Date period for a rate override.
    
    One override can have multiple periods, allowing:
    - Single day: start_date = end_date
    - Date range: start_date to end_date
    - Multiple ranges: Multiple period records
    
    Example:
        "Holiday Premium" override might have:
        - Period 1: Dec 24 - Dec 26 (Christmas)
        - Period 2: Dec 31 - Jan 2 (New Year)
    """
    override = models.ForeignKey(
        DateRateOverride,
        on_delete=models.CASCADE,
        related_name='periods',
        help_text="Parent override"
    )
    
    start_date = models.DateField(
        help_text="Start date (inclusive)"
    )
    
    end_date = models.DateField(
        help_text="End date (inclusive). Same as start for single day."
    )
    
    class Meta:
        ordering = ['start_date']
        verbose_name = "Override Period"
        verbose_name_plural = "Override Periods"
    
    def __str__(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime('%b %d, %Y')
        return f"{self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d, %Y')}"
    
    def clean(self):
        """Validate that end_date is not before start_date."""
        from django.core.exceptions import ValidationError
        
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({
                'end_date': 'End date cannot be before start date.'
            })
    
    def get_date_count(self):
        """Return number of days in this period."""
        return (self.end_date - self.start_date).days + 1
    
    def contains_date(self, check_date):
        """Check if a date falls within this period."""
        return self.start_date <= check_date <= self.end_date
    
    def get_all_dates(self):
        """Generator yielding all dates in this period."""
        current = self.start_date
        while current <= self.end_date:
            yield current
            current += timedelta(days=1)


# =============================================================================
# HELPER FUNCTIONS (Add to model managers or as module functions)
# =============================================================================

def get_override_for_date(hotel, check_date):
    """
    Get the highest-priority active override for a specific date.
    
    Args:
        hotel: Property instance
        check_date: date object
        
    Returns:
        DateRateOverride or None
    """
    # Find all active overrides that include this date
    matching_overrides = DateRateOverride.objects.filter(
        hotel=hotel,
        active=True,
        periods__start_date__lte=check_date,
        periods__end_date__gte=check_date
    ).distinct().order_by('-priority')
    
    return matching_overrides.first()


def get_all_overrides_for_date(hotel, check_date):
    """
    Get all active overrides for a specific date, ordered by priority.
    
    Args:
        hotel: Property instance
        check_date: date object
        
    Returns:
        QuerySet of DateRateOverride objects
    """
    return DateRateOverride.objects.filter(
        hotel=hotel,
        active=True,
        periods__start_date__lte=check_date,
        periods__end_date__gte=check_date
    ).distinct().order_by('-priority')


def get_overrides_for_date_range(hotel, start_date, end_date):
    """
    Get all overrides that apply to any date within a range.
    
    Args:
        hotel: Property instance
        start_date: date object
        end_date: date object
        
    Returns:
        Dict mapping dates to their highest-priority override
    """
    from datetime import timedelta
    
    result = {}
    current = start_date
    
    while current <= end_date:
        override = get_override_for_date(hotel, current)
        if override:
            result[current] = override
        current += timedelta(days=1)
    
    return result


def apply_override_to_bar(hotel, check_date, base_bar):
    """
    Apply date override to BAR if one exists.
    
    Args:
        hotel: Property instance
        check_date: date object
        base_bar: Decimal - Original BAR
        
    Returns:
        tuple: (adjusted_bar, override_or_none, was_adjusted)
    """
    override = get_override_for_date(hotel, check_date)
    
    if override:
        adjusted_bar = override.calculate_adjusted_bar(base_bar)
        return adjusted_bar, override, True
    
    return base_bar, None, False