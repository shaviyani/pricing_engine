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
