"""
Pricing models - simplified version.
"""

from django.db import models
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator



class Property(models.Model):
    """
    Property/hotel configuration - singleton model.
    
    This holds property-wide settings including the reference base rate
    used for room index calculations.
    """
    name = models.CharField(
        max_length=200,
        default="My Hotel",
        help_text="Property name"
    )
    
    reference_base_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('100.00'),
        help_text="Reference rate for room index calculations (e.g., Standard Room rate)"
    )
    
    currency_symbol = models.CharField(
        max_length=5,
        default='$',
        help_text="Currency symbol to display"
    )
    
    class Meta:
        verbose_name = "Property Settings"
        verbose_name_plural = "Property Settings"
    
    def __str__(self):
        return self.name
    
    @classmethod
    def get_instance(cls):
        """Get or create the singleton property instance."""
        instance, created = cls.objects.get_or_create(pk=1)
        return instance
    
    def save(self, *args, **kwargs):
        """Ensure only one instance exists."""
        self.pk = 1
        super().save(*args, **kwargs)


class Season(models.Model):
    """
    Pricing season with date range and index multiplier.
    
    Example:
        Low Season: Jan 11 - Mar 30, Index 1.0
        High Season: Jun 1 - Oct 30, Index 1.3
    """
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
        ordering = ['start_date']
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
    
    def __str__(self):
        return f"{self.name} ({self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d')})"
    
    def date_range_display(self):
        """Display formatted date range."""
        return f"{self.start_date.strftime('%b %d, %Y')} - {self.end_date.strftime('%b %d, %Y')}"
    
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
        from decimal import Decimal
        from .services import calculate_final_rate_with_modifier
        
        total_revenue = Decimal('0.00')
        total_weight = Decimal('0.00')
        
        rooms = RoomType.objects.all()
        rate_plans = RatePlan.objects.all()
        channels = Channel.objects.all()
        
        # Default to equal mix if not provided
        if not room_mix:
            room_mix = {room.id: Decimal('1.00') / rooms.count() for room in rooms}
        if not rate_plan_mix:
            rate_plan_mix = {plan.id: Decimal('1.00') / rate_plans.count() for plan in rate_plans}
        if not channel_mix:
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
                    modifiers = RateModifier.objects.filter(channel=channel, active=True)
                    
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
                            # Get season-specific discount (or fall back to base)
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
        
        This shows actual revenue potential considering the season's occupancy.
        
        Returns:
            Decimal: RevPAR for the season
        """
        adr = self.calculate_adr(room_mix, rate_plan_mix, channel_mix)
        occupancy_decimal = self.expected_occupancy / Decimal('100.00')
        return (adr * occupancy_decimal).quantize(Decimal('0.01'))
    
    def get_occupancy_display(self):
        """Display formatted occupancy percentage."""
        return f"{self.expected_occupancy}%"


class RoomType(models.Model):
    """
    Room category with flexible pricing: base rate, multiplier, or fixed adjustment.
    
    Pricing Methods:
    1. Direct base_rate: Simple, each room has its own rate
    2. Index multiplier: base_rate × room_index (e.g., 1.0, 1.3, 2.0)
    3. Fixed adjustment: base_rate + room_adjustment (e.g., +$0, +$30, +$100)
    
    Examples:
        Standard Room: base_rate=$100, room_index=1.0 → $100
        Deluxe Room: base_rate=$100, room_index=1.3 → $130
        Suite: base_rate=$100, room_adjustment=$100 → $200
    """
    name = models.CharField(max_length=100, help_text="e.g., Standard Room, Deluxe Room, Suite")
    
    # Base rate (can be used directly or as reference for index/adjustment)
    base_rate = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Base rate in USD (used directly or as reference for index/adjustment)"
    )
    
    # Room index/multiplier approach
    room_index = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text="Multiplier for base rate (e.g., 1.0=same, 1.3=30% more, 2.0=double)"
    )
    
    # Fixed adjustment approach (alternative to index)
    room_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Fixed amount to add to base rate (alternative to room_index)"
    )
    
    # Pricing method selector
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
    
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Display order"
    )
    
    number_of_rooms = models.PositiveIntegerField(
        default=10,
        help_text="Number of rooms of this type in the property"
    )
    
    class Meta:
        ordering = ['sort_order', 'name']
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
        """
        Calculate the effective base rate for this room type.
        
        Args:
            reference_rate: Optional reference rate for index/adjustment calculations
                          If None, uses Property.reference_base_rate
        
        Returns:
            Decimal: The effective base rate for this room
        """
        if self.pricing_method == 'direct':
            # Use base_rate directly
            return self.base_rate
        
        # Get reference rate from Property if not provided
        if reference_rate is None:
            try:
                property_instance = Property.get_instance()
                ref_rate = property_instance.reference_base_rate
            except:
                ref_rate = self.base_rate
        else:
            ref_rate = reference_rate
        
        if self.pricing_method == 'index':
            # Multiply reference rate by room_index
            return ref_rate * self.room_index
        
        elif self.pricing_method == 'adjustment':
            # Add fixed adjustment to reference rate
            return ref_rate + self.room_adjustment
        
        # Fallback to base_rate
        return self.base_rate


class RatePlan(models.Model):
    """
    Board type with meal supplement per person.
    
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
    
    Pricing Flow:
    1. BAR (Base Available Rate) = already calculated from room + season + meals
    2. Channel Base Rate = BAR - base_discount_percent
    3. Then Rate Modifiers apply additional discounts (see RateModifier model)
    
    Example:
        OTA: base_discount=0%, commission=18%
        DIRECT: base_discount=15%, commission=0%
    """
    name = models.CharField(max_length=100, help_text="e.g., OTA, DIRECT, Agent")
    base_discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Base channel discount from BAR (e.g., 15.00 for 15% off)"
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Commission the channel takes (for revenue analysis)"
    )
    
    distribution_share_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Expected % of bookings from this channel (for revenue forecasting)"
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
        """Display formatted discount."""
        if self.base_discount_percent > 0:
            return f"{self.base_discount_percent}% discount"
        return "No discount"
    
    def commission_display(self):
        """Display formatted commission."""
        if self.commission_percent > 0:
            return f"{self.commission_percent}% commission"
        return "No commission"
    
    def distribution_display(self):
        """Display formatted distribution share."""
        if self.distribution_share_percent > 0:
            return f"{self.distribution_share_percent}% of bookings"
        return "No distribution set"

    @classmethod
    def validate_total_distribution(cls):
        """
        Validate that total distribution shares equal 100%.
        
        Returns:
            tuple: (is_valid: bool, total: Decimal, message: str)
        """
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
            message = f"⚠ Total distribution: {total}% (exceeds 100% by {total - Decimal('100.00')}%)"
        
        return is_valid, total, message
    
    @classmethod
    def get_distribution_mix(cls):
        """
        Get channel distribution as a dictionary for calculations.
        
        Returns:
            dict: {channel_id: share_as_decimal}
            Example: {1: Decimal('0.70'), 2: Decimal('0.30')}
        """
        channels = cls.objects.all()
        return {
            channel.id: channel.distribution_share_percent / Decimal('100.00')
            for channel in channels
            if channel.distribution_share_percent > 0
        }
    
    @classmethod
    def normalize_distribution(cls):
        """
        Auto-normalize distribution shares to sum to 100%.
        
        Proportionally adjusts all shares so they sum to exactly 100%.
        Only affects channels with share > 0.
        """
        channels_with_share = cls.objects.filter(distribution_share_percent__gt=0)
        
        if not channels_with_share.exists():
            return
        
        total = channels_with_share.aggregate(
            total=models.Sum('distribution_share_percent')
        )['total'] or Decimal('0.00')
        
        if total == Decimal('0.00'):
            return
        
        # Calculate normalization factor
        factor = Decimal('100.00') / total
        
        # Apply to each channel
        for channel in channels_with_share:
            channel.distribution_share_percent = (
                channel.distribution_share_percent * factor
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            channel.save()
    
    @classmethod
    def distribute_equally(cls):
        """
        Set equal distribution across all channels.
        
        Each channel gets 100% / number_of_channels.
        """
        channels = cls.objects.all()
        if not channels.exists():
            return
        
        share_per_channel = (Decimal('100.00') / channels.count()).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        for channel in channels:
            channel.distribution_share_percent = share_per_channel
            channel.save()
            
class RateModifier(models.Model):
    """
    Additional discount modifiers for channels (Genius, Mobile App, Newsletter, etc.).
    
    These stack on top of the channel's base_discount_percent.
    
    Calculation Flow:
    1. BAR = Base Rate × Season + Meals
    2. Channel Base Rate = BAR - channel.base_discount_percent
    3. Final Rate = Channel Base Rate - modifier.discount_percent
    
    Example for OTA:
        BAR: $96.50
        Channel Base (OTA -0%): $96.50
        ├─ Standard: $96.50 (0% modifier)
        ├─ Genius Member: $86.85 (-10% modifier)
        └─ Mobile App: $86.85 (-10% modifier)
    """
    channel = models.ForeignKey(
        Channel, 
        on_delete=models.CASCADE,
        related_name='rate_modifiers',
        help_text="Which channel this modifier applies to"
    )
    name = models.CharField(
        max_length=100, 
        help_text="e.g., 'Genius Member', 'Mobile App', 'Newsletter Subscriber'"
    )
    discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Additional discount % from channel base rate"
    )
    active = models.BooleanField(
        default=True,
        help_text="Whether this rate modifier is currently available"
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within channel"
    )
    
    # Optional: categorization for reporting
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
        default='standard',
        help_text="Type of rate modifier"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Optional description (e.g., 'For Booking.com Genius Level 2 members')"
    )
    
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
        """
        Get the discount percentage for a specific season.
        
        Always returns a value from SeasonModifierOverride.
        If entry doesn't exist (shouldn't happen with auto-population), creates it.
        
        Args:
            season: Season object
            
        Returns:
            Decimal: Discount percentage for this season
        """
        # Get or create season discount entry
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
    
    AUTO-POPULATED PANEL SYSTEM:
    - Every season automatically gets entries for ALL modifiers
    - Every modifier automatically gets entries for ALL seasons
    - Defaults to modifier's base discount (is_customized=False)
    - When customized, is_customized=True (won't auto-update)
    - When modifier base changes, auto-updates non-customized entries
    
    Example Season Panel (Low Season):
      ├─ Genius L1: 15% (customized)
      ├─ Genius L2: 20% (customized)  
      ├─ Mobile App: 10% (default)
      ├─ Newsletter: 5% (default)
      └─ Standard: 0% (default)
    """
    modifier = models.ForeignKey(
        RateModifier,
        on_delete=models.CASCADE,
        related_name='season_discounts',
        help_text="Which modifier this applies to"
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name='modifier_discounts',
        help_text="Which season this applies to"
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Discount % for this modifier in this season"
    )
    is_customized = models.BooleanField(
        default=False,
        help_text="True if manually edited, False if using base default"
    )
    notes = models.TextField(
        blank=True,
        help_text="Optional notes explaining customization"
    )
    
    class Meta:
        ordering = ['season', 'modifier__channel', 'modifier__sort_order']
        verbose_name = "Season Modifier Discount"
        verbose_name_plural = "Season Modifier Discounts"
        unique_together = ['modifier', 'season']
    
    def __str__(self):
        status = " (custom)" if self.is_customized else " (default)"
        return f"{self.season.name} - {self.modifier.name}: {self.discount_percent}%{status}"
    
    def save(self, *args, **kwargs):
        """Auto-mark as customized if discount differs from base."""
        if self.pk:  # Existing record
            # Check if discount changed from base
            if self.discount_percent != self.modifier.discount_percent:
                self.is_customized = True
        else:  # New record
            # Default to base discount if not set
            if self.discount_percent == Decimal('0.00'):
                self.discount_percent = self.modifier.discount_percent
        super().save(*args, **kwargs)
    
    def sync_from_base(self):
        """Update to match modifier's base discount if not customized."""
        if not self.is_customized:
            self.discount_percent = self.modifier.discount_percent
            super().save()  # Skip save() to avoid re-marking
    
    def reset_to_base(self):
        """Reset to base discount and mark as not customized."""
        self.discount_percent = self.modifier.discount_percent
        self.is_customized = False
        super().save()
    def __str__(self):
        return f"{self.modifier.name} → {self.season.name}: -{self.discount_percent}%"


#pickup analysis models  
class DailyPickupSnapshot(models.Model):
    """
    Daily snapshot of on-the-books (OTB) position for a future arrival date.
    
    Captured once per day (via scheduled job or manual import).
    Tracks how bookings accumulate over time for each arrival date.
    
    Example:
        snapshot_date=Jan 15, arrival_date=Mar 1, days_out=45
        otb_room_nights=23, otb_revenue=4140, otb_adr=180
        
        Next day:
        snapshot_date=Jan 16, arrival_date=Mar 1, days_out=44
        otb_room_nights=25, otb_revenue=4500, otb_adr=180
        (picked up 2 room nights overnight)
    """
    # When this snapshot was taken
    snapshot_date = models.DateField(
        db_index=True,
        help_text="Date when this OTB position was recorded"
    )
    
    # What future date we're tracking
    arrival_date = models.DateField(
        db_index=True,
        help_text="The future arrival date being tracked"
    )
    
    # Calculated field for easy querying
    days_out = models.PositiveIntegerField(
        help_text="Days between snapshot_date and arrival_date"
    )
    
    # On-the-books metrics
    otb_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Total room nights booked for this arrival date"
    )
    otb_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total revenue booked for this arrival date"
    )
    otb_reservations = models.PositiveIntegerField(
        default=0,
        help_text="Number of reservations for this arrival date"
    )
    
    # Breakdown by segment (stored as JSON for flexibility)
    otb_by_channel = models.JSONField(
        default=dict,
        blank=True,
        help_text="Room nights breakdown by channel: {'OTA': 15, 'DIRECT': 8}"
    )
    otb_by_room_type = models.JSONField(
        default=dict,
        blank=True,
        help_text="Room nights breakdown by room type"
    )
    otb_by_rate_plan = models.JSONField(
        default=dict,
        blank=True,
        help_text="Room nights breakdown by rate plan"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-snapshot_date', 'arrival_date']
        unique_together = ['snapshot_date', 'arrival_date']
        verbose_name = "Daily Pickup Snapshot"
        verbose_name_plural = "Daily Pickup Snapshots"
        indexes = [
            models.Index(fields=['arrival_date', 'days_out']),
            models.Index(fields=['snapshot_date']),
            models.Index(fields=['arrival_date', 'snapshot_date']),
        ]
    
    def __str__(self):
        return f"{self.snapshot_date} → {self.arrival_date} ({self.days_out}d out): {self.otb_room_nights} RN"
    
    @property
    def otb_adr(self):
        """Calculate ADR from booked revenue and room nights."""
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def save(self, *args, **kwargs):
        """Auto-calculate days_out before saving."""
        if self.arrival_date and self.snapshot_date:
            self.days_out = (self.arrival_date - self.snapshot_date).days
        super().save(*args, **kwargs)
    
    @classmethod
    def get_pickup_for_date(cls, arrival_date, from_days_out=90):
        """
        Get pickup progression for a specific arrival date.
        
        Returns list of snapshots showing how OTB grew over time.
        """
        return cls.objects.filter(
            arrival_date=arrival_date,
            days_out__lte=from_days_out
        ).order_by('-days_out')
    
    @classmethod
    def get_latest_otb(cls, arrival_date):
        """Get the most recent OTB snapshot for an arrival date."""
        return cls.objects.filter(
            arrival_date=arrival_date
        ).order_by('-snapshot_date').first()


class MonthlyPickupSnapshot(models.Model):
    """
    Aggregated monthly OTB snapshot.
    
    Summarizes all daily snapshots for a target month as of a specific date.
    Used for month-level tracking and STLY comparisons.
    
    Example:
        snapshot_date=Jan 15, target_month=Mar 2026, days_out=45
        otb_room_nights=156, otb_revenue=28080, otb_occupancy=25.2%
    """
    # When this snapshot was taken
    snapshot_date = models.DateField(
        db_index=True,
        help_text="Date when this snapshot was recorded"
    )
    
    # Target month (stored as first day of month)
    target_month = models.DateField(
        db_index=True,
        help_text="First day of the target month (e.g., 2026-03-01 for March 2026)"
    )
    
    # Days until target month starts
    days_out = models.PositiveIntegerField(
        help_text="Days between snapshot_date and start of target_month"
    )
    
    # Aggregated OTB metrics
    otb_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Total room nights booked for this month"
    )
    otb_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total revenue booked for this month"
    )
    otb_reservations = models.PositiveIntegerField(
        default=0,
        help_text="Number of reservations for this month"
    )
    
    # Calculated occupancy (requires knowing total available rooms)
    otb_occupancy_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="OTB occupancy percentage"
    )
    
    # Available room nights for this month (for occupancy calculation)
    available_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Total available room nights for this month"
    )
    
    # Breakdown by segment
    otb_by_channel = models.JSONField(
        default=dict,
        blank=True,
        help_text="Room nights by channel"
    )
    otb_by_room_type = models.JSONField(
        default=dict,
        blank=True,
        help_text="Room nights by room type"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-snapshot_date', 'target_month']
        unique_together = ['snapshot_date', 'target_month']
        verbose_name = "Monthly Pickup Snapshot"
        verbose_name_plural = "Monthly Pickup Snapshots"
        indexes = [
            models.Index(fields=['target_month', 'days_out']),
            models.Index(fields=['target_month', 'snapshot_date']),
        ]
    
    def __str__(self):
        month_str = self.target_month.strftime('%b %Y')
        return f"{self.snapshot_date} → {month_str} ({self.days_out}d out): {self.otb_room_nights} RN ({self.otb_occupancy_percent}%)"
    
    @property
    def otb_adr(self):
        """Calculate ADR from booked revenue and room nights."""
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def save(self, *args, **kwargs):
        """Auto-calculate days_out and occupancy before saving."""
        if self.target_month and self.snapshot_date:
            self.days_out = (self.target_month - self.snapshot_date).days
        
        if self.available_room_nights > 0:
            self.otb_occupancy_percent = (
                Decimal(str(self.otb_room_nights)) / 
                Decimal(str(self.available_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
        
        super().save(*args, **kwargs)
    
    @classmethod
    def get_stly(cls, target_month, days_out):
        """
        Get Same Time Last Year snapshot for comparison.
        
        Args:
            target_month: First day of target month
            days_out: How many days before month we want to compare
            
        Returns:
            MonthlyPickupSnapshot from same month last year at similar days_out
        """
        from dateutil.relativedelta import relativedelta
        
        stly_month = target_month - relativedelta(years=1)
        
        # Find closest days_out (within 3 days tolerance)
        return cls.objects.filter(
            target_month=stly_month,
            days_out__gte=days_out - 3,
            days_out__lte=days_out + 3
        ).order_by('days_out').first()


class PickupCurve(models.Model):
    """
    Historical pickup curve showing booking patterns by season type.
    
    Built from historical data, shows what percentage of final occupancy
    is typically booked at X days out.
    
    Example (High Season curve):
        days_out=90: cumulative_percent=15% (15% booked at 90 days out)
        days_out=60: cumulative_percent=35%
        days_out=30: cumulative_percent=65%
        days_out=14: cumulative_percent=85%
        days_out=7:  cumulative_percent=95%
        days_out=0:  cumulative_percent=100%
    """
    SEASON_TYPES = [
        ('peak', 'Peak Season'),
        ('high', 'High Season'),
        ('shoulder', 'Shoulder Season'),
        ('low', 'Low Season'),
    ]
    
    # What season type this curve represents
    season_type = models.CharField(
        max_length=20,
        choices=SEASON_TYPES,
        db_index=True,
        help_text="Season type this curve applies to"
    )
    
    # Optional: link to specific Season for more granular curves
    season = models.ForeignKey(
        'Season',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pickup_curves',
        help_text="Specific season (optional - if null, applies to all seasons of this type)"
    )
    
    # Days before arrival
    days_out = models.PositiveIntegerField(
        help_text="Days before arrival date"
    )
    
    # What percentage is typically booked at this point
    cumulative_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Percentage of final occupancy typically booked at this days_out"
    )
    
    # Statistical confidence
    sample_size = models.PositiveIntegerField(
        default=0,
        help_text="Number of historical periods used to build this data point"
    )
    std_deviation = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Standard deviation of the cumulative_percent"
    )
    
    # Curve metadata
    curve_version = models.PositiveIntegerField(
        default=1,
        help_text="Version number for tracking curve updates"
    )
    built_from_start = models.DateField(
        null=True,
        blank=True,
        help_text="Start date of historical data used to build curve"
    )
    built_from_end = models.DateField(
        null=True,
        blank=True,
        help_text="End date of historical data used to build curve"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['season_type', '-days_out']
        unique_together = ['season_type', 'season', 'days_out', 'curve_version']
        verbose_name = "Pickup Curve"
        verbose_name_plural = "Pickup Curves"
        indexes = [
            models.Index(fields=['season_type', 'days_out']),
        ]
    
    def __str__(self):
        season_name = self.season.name if self.season else self.get_season_type_display()
        return f"{season_name} @ {self.days_out}d out: {self.cumulative_percent}%"
    
    @classmethod
    def get_curve_for_season(cls, season_type, season=None):
        """
        Get the full pickup curve for a season type.
        
        Returns QuerySet ordered by days_out (descending - furthest out first).
        """
        filters = {'season_type': season_type}
        if season:
            filters['season'] = season
        else:
            filters['season__isnull'] = True
        
        return cls.objects.filter(**filters).order_by('-days_out')
    
    @classmethod
    def get_expected_percent_at_days_out(cls, season_type, days_out, season=None):
        """
        Get expected cumulative percentage at a specific days_out.
        
        Interpolates if exact days_out not in curve.
        """
        curve = cls.get_curve_for_season(season_type, season)
        
        if not curve.exists():
            return None
        
        # Find surrounding points for interpolation
        point_before = curve.filter(days_out__gte=days_out).order_by('days_out').first()
        point_after = curve.filter(days_out__lte=days_out).order_by('-days_out').first()
        
        if point_before and point_before.days_out == days_out:
            return point_before.cumulative_percent
        
        if point_before and point_after and point_before != point_after:
            # Linear interpolation
            days_range = point_before.days_out - point_after.days_out
            pct_range = point_after.cumulative_percent - point_before.cumulative_percent
            
            if days_range > 0:
                days_from_before = point_before.days_out - days_out
                interpolated = point_before.cumulative_percent + (
                    pct_range * Decimal(str(days_from_before)) / Decimal(str(days_range))
                )
                return interpolated.quantize(Decimal('0.01'))
        
        # Fallback to nearest point
        if point_before:
            return point_before.cumulative_percent
        if point_after:
            return point_after.cumulative_percent
        
        return None


class OccupancyForecast(models.Model):
    """
    Generated occupancy and revenue forecast for a future month.
    
    Contains TWO types of forecasts:
    1. Pickup Forecast: Data-driven prediction from booking patterns
    2. Scenario Forecast: Manual estimate from Season.expected_occupancy
    
    This allows comparison between actual booking pace and planning targets.
    """
    # Target month (stored as first day of month)
    target_month = models.DateField(
        db_index=True,
        help_text="First day of the target month"
    )
    
    # When this forecast was generated
    forecast_date = models.DateField(
        db_index=True,
        help_text="Date when this forecast was generated"
    )
    
    # Days until target month
    days_out = models.PositiveIntegerField(
        help_text="Days between forecast_date and start of target_month"
    )
    
    # Link to season for context
    season = models.ForeignKey(
        'Season',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='forecasts',
        help_text="Season this month falls into"
    )
    
    # Available inventory
    available_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Total available room nights for this month"
    )
    
    # =========================================================================
    # CURRENT POSITION (OTB)
    # =========================================================================
    otb_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Room nights currently on the books"
    )
    otb_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Revenue currently on the books"
    )
    otb_occupancy_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current OTB occupancy percentage"
    )
    
    # =========================================================================
    # PICKUP FORECAST (Data-Driven)
    # =========================================================================
    pickup_forecast_nights = models.PositiveIntegerField(
        default=0,
        help_text="Forecasted total room nights (OTB + expected pickup)"
    )
    pickup_forecast_occupancy = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted occupancy percentage"
    )
    pickup_forecast_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted gross revenue"
    )
    pickup_expected_additional = models.PositiveIntegerField(
        default=0,
        help_text="Expected additional room nights to be picked up"
    )
    
    # Forecast methodology breakdown
    forecast_from_curve = models.PositiveIntegerField(
        default=0,
        help_text="Room nights forecast from pickup curve (50% weight)"
    )
    forecast_from_stly = models.PositiveIntegerField(
        default=0,
        help_text="Room nights forecast from STLY comparison (30% weight)"
    )
    forecast_from_velocity = models.PositiveIntegerField(
        default=0,
        help_text="Room nights forecast from recent velocity (20% weight)"
    )
    
    # Confidence indicator
    CONFIDENCE_LEVELS = [
        ('very_low', 'Very Low (< 30 days data)'),
        ('low', 'Low (30-60 days data)'),
        ('medium', 'Medium (60-90 days data)'),
        ('high', 'High (90+ days data)'),
    ]
    confidence_level = models.CharField(
        max_length=20,
        choices=CONFIDENCE_LEVELS,
        default='medium',
        help_text="Confidence level based on data availability"
    )
    confidence_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('50.00'),
        help_text="Confidence percentage (25-95%)"
    )
    
    # =========================================================================
    # SCENARIO FORECAST (Manual - from Season.expected_occupancy)
    # =========================================================================
    scenario_occupancy = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Manual scenario occupancy (from Season.expected_occupancy)"
    )
    scenario_room_nights = models.PositiveIntegerField(
        default=0,
        help_text="Room nights based on scenario occupancy"
    )
    scenario_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Revenue based on scenario occupancy"
    )
    
    # =========================================================================
    # VARIANCE ANALYSIS
    # =========================================================================
    # Pickup vs Scenario
    variance_nights = models.IntegerField(
        default=0,
        help_text="Pickup forecast - Scenario (can be negative)"
    )
    variance_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Percentage difference from scenario"
    )
    
    # vs STLY (Same Time Last Year)
    stly_occupancy = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="STLY final occupancy (if available)"
    )
    stly_otb_at_same_point = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="STLY OTB at same days_out"
    )
    vs_stly_pace_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentage ahead/behind STLY pace"
    )
    
    # =========================================================================
    # REVENUE DETAILS
    # =========================================================================
    forecast_adr = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted ADR"
    )
    forecast_revpar = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted RevPAR"
    )
    forecast_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted commission (based on channel mix)"
    )
    forecast_net_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Forecasted net revenue after commission"
    )
    
    # =========================================================================
    # METADATA
    # =========================================================================
    notes = models.TextField(
        blank=True,
        help_text="Auto-generated insights or manual notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['target_month', '-forecast_date']
        unique_together = ['target_month', 'forecast_date']
        verbose_name = "Occupancy Forecast"
        verbose_name_plural = "Occupancy Forecasts"
        indexes = [
            models.Index(fields=['target_month', 'days_out']),
            models.Index(fields=['forecast_date']),
        ]
    
    def __str__(self):
        month_str = self.target_month.strftime('%b %Y')
        return f"{month_str} forecast ({self.forecast_date}): {self.pickup_forecast_occupancy}% pickup / {self.scenario_occupancy}% scenario"
    
    def save(self, *args, **kwargs):
        """Auto-calculate derived fields before saving."""
        # Calculate days_out
        if self.target_month and self.forecast_date:
            self.days_out = (self.target_month - self.forecast_date).days
        
        # Calculate OTB occupancy
        if self.available_room_nights > 0:
            self.otb_occupancy_percent = (
                Decimal(str(self.otb_room_nights)) / 
                Decimal(str(self.available_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
            
            # Calculate pickup forecast occupancy
            self.pickup_forecast_occupancy = (
                Decimal(str(self.pickup_forecast_nights)) / 
                Decimal(str(self.available_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
        
        # Calculate variance
        self.variance_nights = self.pickup_forecast_nights - self.scenario_room_nights
        if self.scenario_room_nights > 0:
            self.variance_percent = (
                Decimal(str(self.variance_nights)) / 
                Decimal(str(self.scenario_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
        
        # Calculate RevPAR
        if self.available_room_nights > 0:
            self.forecast_revpar = (
                self.pickup_forecast_revenue / 
                Decimal(str(self.available_room_nights))
            ).quantize(Decimal('0.01'))
        
        # Calculate net revenue
        self.forecast_net_revenue = self.pickup_forecast_revenue - self.forecast_commission
        
        # Set confidence level based on days_out
        if self.days_out <= 14:
            self.confidence_level = 'high'
            self.confidence_percent = Decimal('90.00')
        elif self.days_out <= 30:
            self.confidence_level = 'high'
            self.confidence_percent = Decimal('85.00')
        elif self.days_out <= 60:
            self.confidence_level = 'medium'
            self.confidence_percent = Decimal('70.00')
        elif self.days_out <= 90:
            self.confidence_level = 'low'
            self.confidence_percent = Decimal('55.00')
        else:
            self.confidence_level = 'very_low'
            self.confidence_percent = Decimal('35.00')
        
        super().save(*args, **kwargs)
    
    @property
    def otb_adr(self):
        """Current OTB ADR."""
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    @property
    def is_ahead_of_stly(self):
        """Check if current pace is ahead of STLY."""
        if self.vs_stly_pace_percent is not None:
            return self.vs_stly_pace_percent > 0
        return None
    
    @property
    def is_ahead_of_scenario(self):
        """Check if pickup forecast exceeds scenario."""
        return self.variance_nights > 0
    
    @classmethod
    def get_latest_forecast(cls, target_month):
        """Get the most recent forecast for a month."""
        return cls.objects.filter(
            target_month=target_month
        ).order_by('-forecast_date').first()
    
    @classmethod
    def get_forecast_history(cls, target_month, limit=30):
        """Get forecast progression over time for a month."""
        return cls.objects.filter(
            target_month=target_month
        ).order_by('-forecast_date')[:limit]
    
    def generate_insight(self):
        """Generate a human-readable insight about this forecast."""
        insights = []
        
        # Compare to scenario
        if self.variance_nights > 0:
            insights.append(
                f"Pickup forecast is {self.variance_nights} room nights "
                f"({abs(self.variance_percent):.1f}%) above your scenario target."
            )
        elif self.variance_nights < 0:
            insights.append(
                f"Pickup forecast is {abs(self.variance_nights)} room nights "
                f"({abs(self.variance_percent):.1f}%) below your scenario target."
            )
        
        # Compare to STLY
        if self.vs_stly_pace_percent is not None:
            if self.vs_stly_pace_percent > 5:
                insights.append(
                    f"You're {self.vs_stly_pace_percent:.1f}% ahead of last year's pace. "
                    "Consider rate increases."
                )
            elif self.vs_stly_pace_percent < -5:
                insights.append(
                    f"You're {abs(self.vs_stly_pace_percent):.1f}% behind last year's pace. "
                    "Consider promotional activity."
                )
        
        # Confidence note
        if self.days_out > 60:
            insights.append(
                f"Forecast confidence is {self.confidence_level} ({self.confidence_percent:.0f}%) "
                f"at {self.days_out} days out."
            )
        
        return " ".join(insights) if insights else "Forecast is on track."
    
    
    
    """
Reservation and Import Models for Booking Data Analysis.

These models support:
- Importing reservation data from Excel/CSV
- Tracking booking sources and mapping to channels
- Guest tracking for repeat analysis
- Multi-room booking linking
- Lead time calculations

Add these to your existing pricing/models.py file.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal
from datetime import date, timedelta
import re


class BookingSource(models.Model):
    """
    Maps import source values to channels.
    
    Handles the mapping between what appears in your reservation export
    (e.g., "Booking.com", "Walk-in", empty cell with user "Reekko")
    and your existing Channel model.
    
    Example mappings:
        - "Booking.com" → OTA channel
        - "Walk-in", empty+Reekko, empty+Maais → Direct channel
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Display name (e.g., 'Booking.com', 'Direct - Walk-in')"
    )
    
    # Values to match from import file (case-insensitive)
    import_values = models.JSONField(
        default=list,
        help_text="List of values to match from import (e.g., ['Booking.com', 'booking.com'])"
    )
    
    # Map to existing Channel
    channel = models.ForeignKey(
        'Channel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='booking_sources',
        help_text="Map to existing channel for analysis"
    )
    
    # Special handling flags
    is_direct = models.BooleanField(
        default=False,
        help_text="Is this a direct booking source?"
    )
    
    # For empty source with specific user mapping
    user_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text="User names that indicate this source when Source is empty (e.g., ['Reekko', 'Maais'])"
    )
    
    # Commission override (if different from channel)
    commission_override = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Override commission % (if different from channel)"
    )
    
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Booking Source"
        verbose_name_plural = "Booking Sources"
    
    def __str__(self):
        channel_str = f" → {self.channel.name}" if self.channel else ""
        return f"{self.name}{channel_str}"
    
    @property
    def effective_commission(self):
        """Get commission rate (override or channel default)."""
        if self.commission_override is not None:
            return self.commission_override
        if self.channel:
            return self.channel.commission_percent
        return Decimal('0.00')
    
    @classmethod
    def find_source(cls, source_value, user_value=None):
        """
        Find matching BookingSource for import values.
        
        Args:
            source_value: Value from 'Source' column (may be empty)
            user_value: Value from 'User' column (for empty source handling)
        
        Returns:
            BookingSource or None
        """
        source_value = (source_value or '').strip()
        user_value = (user_value or '').strip()
        
        # First, try to match by source value
        if source_value:
            for booking_source in cls.objects.filter(active=True):
                import_vals = [v.lower() for v in booking_source.import_values]
                if source_value.lower() in import_vals:
                    return booking_source
        
        # If source is empty, check user mappings
        if not source_value and user_value:
            for booking_source in cls.objects.filter(active=True):
                user_maps = [u.lower() for u in booking_source.user_mappings]
                if user_value.lower() in user_maps:
                    return booking_source
        
        return None
    
    @classmethod
    def get_or_create_unknown(cls):
        """Get or create an 'Unknown' source for unmapped values."""
        source, created = cls.objects.get_or_create(
            name='Unknown',
            defaults={
                'import_values': [],
                'is_direct': False,
                'sort_order': 999,
            }
        )
        return source


class Guest(models.Model):
    """
    Guest record for tracking repeat visitors.
    
    Created from reservation imports, allows analysis of:
    - Repeat guest rate
    - Guest lifetime value
    - Booking patterns per guest
    """
    name = models.CharField(
        max_length=200,
        db_index=True,
        help_text="Guest name from reservation"
    )
    
    email = models.EmailField(
        blank=True,
        null=True,
        help_text="Guest email (if available)"
    )
    
    phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Guest phone (if available)"
    )
    
    country = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Guest country from reservation"
    )
    
    # Denormalized stats for quick queries
    booking_count = models.PositiveIntegerField(
        default=0,
        help_text="Total number of bookings"
    )
    total_nights = models.PositiveIntegerField(
        default=0,
        help_text="Total room nights stayed"
    )
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Lifetime revenue from this guest"
    )
    
    first_booking_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of first booking"
    )
    last_booking_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of most recent booking"
    )
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-last_booking_date', 'name']
        verbose_name = "Guest"
        verbose_name_plural = "Guests"
        indexes = [
            models.Index(fields=['name', 'country']),
            models.Index(fields=['booking_count']),
        ]
    
    def __str__(self):
        country_str = f" ({self.country})" if self.country else ""
        return f"{self.name}{country_str}"
    
    @property
    def is_repeat_guest(self):
        """Check if guest has multiple bookings."""
        return self.booking_count > 1
    
    @property
    def average_booking_value(self):
        """Calculate average revenue per booking."""
        if self.booking_count > 0:
            return (self.total_revenue / self.booking_count).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def update_stats(self):
        """Recalculate denormalized stats from reservations."""
        from django.db.models import Min, Max
        
        stats = self.reservations.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        ).aggregate(
            count=Count('id'),
            nights=Sum('nights'),
            revenue=Sum('total_amount'),
            first=Min('booking_date'),
            last=Max('booking_date'),
        )
        
        self.booking_count = stats['count'] or 0
        self.total_nights = stats['nights'] or 0
        self.total_revenue = stats['revenue'] or Decimal('0.00')
        self.first_booking_date = stats['first']
        self.last_booking_date = stats['last']
        self.save()
    
    @classmethod
    def find_or_create(cls, name, country=None, email=None):
        """
        Find existing guest or create new one.
        
        Matching logic:
        1. Exact name + country match
        2. Exact email match (if provided)
        3. Create new guest
        """
        name = (name or '').strip()
        country = (country or '').strip()
        email = (email or '').strip() or None
        
        if not name:
            return None
        
        # Try exact match on name + country
        if country:
            guest = cls.objects.filter(
                name__iexact=name,
                country__iexact=country
            ).first()
            if guest:
                return guest
        
        # Try email match
        if email:
            guest = cls.objects.filter(email__iexact=email).first()
            if guest:
                # Update name/country if needed
                if not guest.country and country:
                    guest.country = country
                    guest.save()
                return guest
        
        # Try just name match (if no country provided)
        if not country:
            guest = cls.objects.filter(name__iexact=name).first()
            if guest:
                return guest
        
        # Create new guest
        return cls.objects.create(
            name=name,
            country=country,
            email=email,
        )


class FileImport(models.Model):
    """
    Tracks file import history.
    
    Keeps record of all imports for:
    - Audit trail
    - Error tracking
    - Duplicate prevention
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with Errors'),
        ('failed', 'Failed'),
    ]
    
    filename = models.CharField(
        max_length=255,
        help_text="Original filename"
    )
    
    file_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="SHA256 hash for duplicate detection"
    )
    
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Stats
    rows_total = models.PositiveIntegerField(default=0)
    rows_processed = models.PositiveIntegerField(default=0)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    
    # Error tracking
    errors = models.JSONField(
        default=list,
        blank=True,
        help_text="List of error messages with row numbers"
    )
    
    # Date range of imported data
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    
    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # User who initiated import (optional)
    imported_by = models.CharField(max_length=100, blank=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "File Import"
        verbose_name_plural = "File Imports"
    
    def __str__(self):
        return f"{self.filename} ({self.get_status_display()})"
    
    @property
    def success_rate(self):
        """Calculate import success rate."""
        if self.rows_total > 0:
            successful = self.rows_created + self.rows_updated
            return (Decimal(str(successful)) / Decimal(str(self.rows_total)) * 100).quantize(Decimal('0.1'))
        return Decimal('0.0')
    
    @property
    def duration_seconds(self):
        """Calculate import duration."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def add_error(self, row_num, message):
        """Add an error to the errors list."""
        if self.errors is None:
            self.errors = []
        self.errors.append({
            'row': row_num,
            'message': str(message),
        })
        self.save(update_fields=['errors'])


class Reservation(models.Model):
    """
    Core reservation/booking record.
    
    Imported from PMS exports, used for:
    - Pickup analysis (booking pace)
    - Lead time analysis
    - Channel performance
    - Revenue tracking
    - Multi-room booking analysis
    """
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('no_show', 'No Show'),
    ]
    
    # Primary identifier
    confirmation_no = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Confirmation number (base number, without room suffix)"
    )
    
    # For display - the original confirmation with suffix
    original_confirmation_no = models.CharField(
        max_length=50,
        blank=True,
        help_text="Original confirmation number from import (e.g., 286-1)"
    )
    
    # Dates
    booking_date = models.DateField(
        db_index=True,
        help_text="Date when booking was made"
    )
    arrival_date = models.DateField(
        db_index=True,
        help_text="Check-in date"
    )
    departure_date = models.DateField(
        help_text="Check-out date"
    )
    
    # Stay details
    nights = models.PositiveIntegerField(
        default=1,
        help_text="Number of nights"
    )
    adults = models.PositiveIntegerField(default=2)
    children = models.PositiveIntegerField(default=0)
    
    # Calculated field
    lead_time_days = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Days between booking and arrival (arrival - booking)"
    )
    
    # Links to reference data
    room_type = models.ForeignKey(
        'RoomType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Room type booked"
    )
    
    # Store original room type name for unmatched types
    room_type_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Original room type name from import"
    )
    
    rate_plan = models.ForeignKey(
        'RatePlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Rate plan / meal plan"
    )
    
    # Store original rate plan name
    rate_plan_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Original rate plan name from import"
    )
    
    booking_source = models.ForeignKey(
        'BookingSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Booking source"
    )
    
    # Denormalized channel for easier querying
    channel = models.ForeignKey(
        'Channel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Channel (from booking source)"
    )
    
    guest = models.ForeignKey(
        'Guest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Guest record"
    )
    
    # Revenue
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total booking amount"
    )
    
    # Calculated ADR for this booking
    adr = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Average Daily Rate (total / nights)"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='confirmed',
        db_index=True
    )
    
    # Multi-room booking support
    parent_reservation = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_rooms',
        help_text="Parent reservation for multi-room bookings"
    )
    
    room_sequence = models.PositiveSmallIntegerField(
        default=1,
        help_text="Room sequence in multi-room booking (1, 2, 3...)"
    )
    
    is_multi_room = models.BooleanField(
        default=False,
        help_text="Is this part of a multi-room booking?"
    )
    
    # Import tracking
    file_import = models.ForeignKey(
        'FileImport',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        help_text="Import batch this came from"
    )
    
    # Raw data storage for reference
    raw_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Original row data from import"
    )
    
    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-booking_date', '-arrival_date']
        verbose_name = "Reservation"
        verbose_name_plural = "Reservations"
        indexes = [
            models.Index(fields=['arrival_date', 'status']),
            models.Index(fields=['booking_date', 'arrival_date']),
            models.Index(fields=['lead_time_days']),
            models.Index(fields=['confirmation_no', 'room_sequence']),
        ]
        # Allow same confirmation_no for multi-room, but unique per sequence
        unique_together = ['confirmation_no', 'room_sequence']
    
    def __str__(self):
        return f"{self.original_confirmation_no or self.confirmation_no} - {self.arrival_date}"
    
    def save(self, *args, **kwargs):
        """Auto-calculate fields before saving."""
        # Calculate lead time
        if self.arrival_date and self.booking_date:
            self.lead_time_days = (self.arrival_date - self.booking_date).days
        
        # Calculate ADR
        if self.nights and self.nights > 0 and self.total_amount:
            self.adr = (self.total_amount / self.nights).quantize(Decimal('0.01'))
        
        # Set channel from booking source
        if self.booking_source and self.booking_source.channel:
            self.channel = self.booking_source.channel
        
        super().save(*args, **kwargs)
    
    @property
    def total_guests(self):
        """Total number of guests."""
        return self.adults + self.children
    
    @property
    def lead_time_bucket(self):
        """Get lead time bucket for analysis."""
        days = self.lead_time_days
        if days <= 0:
            return 'Same Day'
        elif days <= 7:
            return '1-7 days'
        elif days <= 14:
            return '8-14 days'
        elif days <= 30:
            return '15-30 days'
        elif days <= 60:
            return '31-60 days'
        elif days <= 90:
            return '61-90 days'
        else:
            return '90+ days'
    
    @property
    def linked_room_count(self):
        """Count of linked rooms for multi-room bookings."""
        if self.parent_reservation:
            return self.parent_reservation.linked_rooms.count() + 1
        return self.linked_rooms.count() + 1 if self.is_multi_room else 1
    
    @classmethod
    def parse_confirmation_no(cls, raw_confirmation):
        """
        Parse confirmation number to extract base and sequence.
        
        Examples:
            "286" → ("286", 1)
            "286-1" → ("286", 1)
            "286-2" → ("286", 2)
            "ABC123-3" → ("ABC123", 3)
        
        Returns:
            tuple: (base_confirmation, sequence_number)
        """
        raw = str(raw_confirmation or '').strip()
        
        if not raw:
            return ('', 1)
        
        # Pattern: base-number at the end
        match = re.match(r'^(.+)-(\d+)$', raw)
        if match:
            return (match.group(1), int(match.group(2)))
        
        return (raw, 1)
    
    @classmethod
    def get_lead_time_distribution(cls, start_date=None, end_date=None, channel=None):
        """
        Get lead time distribution for analysis.
        
        Returns dict with bucket counts and revenue.
        """
        queryset = cls.objects.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        if start_date:
            queryset = queryset.filter(arrival_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(arrival_date__lte=end_date)
        if channel:
            queryset = queryset.filter(channel=channel)
        
        buckets = {
            'Same Day': {'min': -999, 'max': 0, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '1-7 days': {'min': 1, 'max': 7, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '8-14 days': {'min': 8, 'max': 14, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '15-30 days': {'min': 15, 'max': 30, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '31-60 days': {'min': 31, 'max': 60, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '61-90 days': {'min': 61, 'max': 90, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
            '90+ days': {'min': 91, 'max': 9999, 'count': 0, 'nights': 0, 'revenue': Decimal('0.00')},
        }
        
        for res in queryset:
            for bucket_name, bucket_data in buckets.items():
                if bucket_data['min'] <= res.lead_time_days <= bucket_data['max']:
                    bucket_data['count'] += 1
                    bucket_data['nights'] += res.nights
                    bucket_data['revenue'] += res.total_amount
                    break
        
        # Calculate percentages
        total_count = sum(b['count'] for b in buckets.values())
        total_revenue = sum(b['revenue'] for b in buckets.values())
        
        result = []
        for bucket_name, bucket_data in buckets.items():
            result.append({
                'bucket': bucket_name,
                'count': bucket_data['count'],
                'nights': bucket_data['nights'],
                'revenue': bucket_data['revenue'],
                'count_percent': (
                    Decimal(str(bucket_data['count'])) / Decimal(str(total_count)) * 100
                    if total_count > 0 else Decimal('0.0')
                ).quantize(Decimal('0.1')),
                'revenue_percent': (
                    bucket_data['revenue'] / total_revenue * 100
                    if total_revenue > 0 else Decimal('0.0')
                ).quantize(Decimal('0.1')),
                'avg_adr': (
                    bucket_data['revenue'] / bucket_data['nights']
                    if bucket_data['nights'] > 0 else Decimal('0.00')
                ).quantize(Decimal('0.01')),
            })
        
        return result