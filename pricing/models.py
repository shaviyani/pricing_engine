"""
Pricing models - Hybrid Multi-Property Architecture.

Property-specific: Season, RoomType, Reservation, Pickup models
Shared: Channel, RatePlan, BookingSource, Guest

Note: ForeignKey to Property model is named 'hotel' to avoid conflict
with Python's built-in @property decorator.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date, timedelta
import re


# =============================================================================
# ORGANIZATION & PROPERTY
# =============================================================================

class Organization(models.Model):
    """
    Top-level organization that owns multiple properties.
    
    Example: "Atoll Resorts Group" owns "Biosphere Inn" and "Thundi Resort"
    """
    name = models.CharField(
        max_length=200,
        help_text="Organization name (e.g., 'Atoll Resorts Group')"
    )
    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="URL-friendly code (e.g., 'atoll-resorts')"
    )
    
    # Settings
    default_currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="Default currency code (e.g., USD, EUR)"
    )
    currency_symbol = models.CharField(
        max_length=5,
        default='$',
        help_text="Currency symbol for display"
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this organization is active"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
    
    def __str__(self):
        return self.name
    
    @property
    def property_count(self):
        """Return count of active properties."""
        return self.properties.filter(is_active=True).count()
    
    @property
    def total_rooms(self):
        """Return total rooms across all properties."""
        return self.properties.filter(
            is_active=True
        ).aggregate(
            total=Sum('room_types__number_of_rooms')
        )['total'] or 0


class Property(models.Model):
    """
    Property/hotel configuration.
    
    This holds property-wide settings including the reference base rate
    used for room index calculations.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='properties',
        help_text="Parent organization"
    )
    
    name = models.CharField(
        max_length=200,
        default="My Hotel",
        help_text="Property name"
    )
    code = models.SlugField(
        max_length=50,
        help_text="URL-friendly code (e.g., 'biosphere-inn')"
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
    
    location = models.CharField(
        max_length=255, 
        blank=True, 
        help_text="e.g., Maldives, Kaafu Atoll"
    )
    
    # Capacity
    total_rooms = models.PositiveIntegerField(
        default=0,
        help_text="Total number of rooms (auto-calculated from room types)"
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this property is active"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['organization', 'name']
        unique_together = ['organization', 'code']
        verbose_name = "Property"
        verbose_name_plural = "Properties"
    
    def __str__(self):
        return f"{self.name} ({self.organization.name})"
    
    def save(self, *args, **kwargs):
        """Auto-calculate total_rooms from room types."""
        super().save(*args, **kwargs)
        self._update_total_rooms()
    
    def _update_total_rooms(self):
        """Update total_rooms from sum of room types."""
        total = self.room_types.aggregate(
            total=Sum('number_of_rooms')
        )['total'] or 0
        
        if self.total_rooms != total:
            Property.objects.filter(pk=self.pk).update(total_rooms=total)
    
    def get_currency_symbol(self):
        """Get currency symbol (property or organization default)."""
        return self.currency_symbol or self.organization.currency_symbol
    
    @property
    def room_count(self):
        """Return count of room types."""
        return self.room_types.count()
    
    def get_absolute_url(self):
        """URL for property dashboard."""
        from django.urls import reverse
        return reverse('pricing:property_dashboard', kwargs={
            'org_code': self.organization.code,
            'prop_code': self.code,
        })


def get_current_property(request):
    """
    Get current property from request (URL kwargs or session).
    
    Usage in views:
        hotel = get_current_property(request)
        rooms = RoomType.objects.filter(hotel=hotel)
    """
    # Try URL kwargs first
    org_code = request.resolver_match.kwargs.get('org_code')
    prop_code = request.resolver_match.kwargs.get('prop_code')
    
    if org_code and prop_code:
        try:
            return Property.objects.select_related('organization').get(
                organization__code=org_code,
                code=prop_code,
                is_active=True
            )
        except Property.DoesNotExist:
            return None
    
    # Fall back to session
    property_id = request.session.get('current_property_id')
    if property_id:
        try:
            return Property.objects.select_related('organization').get(
                pk=property_id,
                is_active=True
            )
        except Property.DoesNotExist:
            return None
    
    return None


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


class BookingSource(models.Model):
    """
    Maps import source values to channels.
    SHARED: Same booking source mappings across all properties.
    """
    name = models.CharField(max_length=100, unique=True)
    
    import_values = models.JSONField(
        default=list,
        help_text="Values to match from import files"
    )
    
    channel = models.ForeignKey(
        Channel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='booking_sources'
    )
    
    is_direct = models.BooleanField(default=False)
    
    user_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text="User names for empty source handling"
    )
    
    commission_override = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
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
        if self.commission_override is not None:
            return self.commission_override
        if self.channel:
            return self.channel.commission_percent
        return Decimal('0.00')
    
    @classmethod
    def find_source(cls, source_value, user_value=None):
        source_value = (source_value or '').strip()
        user_value = (user_value or '').strip()
        
        if source_value:
            for booking_source in cls.objects.filter(active=True):
                import_vals = [v.lower() for v in booking_source.import_values]
                if source_value.lower() in import_vals:
                    return booking_source
        
        if not source_value and user_value:
            for booking_source in cls.objects.filter(active=True):
                user_maps = [u.lower() for u in booking_source.user_mappings]
                if user_value.lower() in user_maps:
                    return booking_source
        
        return None
    
    @classmethod
    def get_or_create_unknown(cls):
        source, created = cls.objects.get_or_create(
            name='Unknown',
            defaults={'import_values': [], 'is_direct': False, 'sort_order': 999}
        )
        return source


class Guest(models.Model):
    """
    Guest record for tracking repeat visitors.
    SHARED: Guests can book across multiple properties (organization-level).
    """
    name = models.CharField(max_length=200, db_index=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    
    # Denormalized stats
    booking_count = models.PositiveIntegerField(default=0)
    total_nights = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    
    first_booking_date = models.DateField(null=True, blank=True)
    last_booking_date = models.DateField(null=True, blank=True)
    
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
        return self.booking_count > 1
    
    @property
    def average_booking_value(self):
        if self.booking_count > 0:
            return (self.total_revenue / self.booking_count).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def update_stats(self):
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
        name = (name or '').strip()
        country = (country or '').strip()
        email = (email or '').strip() or None
        
        if not name:
            return None
        
        if country:
            guest = cls.objects.filter(name__iexact=name, country__iexact=country).first()
            if guest:
                return guest
        
        if email:
            guest = cls.objects.filter(email__iexact=email).first()
            if guest:
                if not guest.country and country:
                    guest.country = country
                    guest.save()
                return guest
        
        if not country:
            guest = cls.objects.filter(name__iexact=name).first()
            if guest:
                return guest
        
        return cls.objects.create(name=name, country=country, email=email)


# =============================================================================
# FILE IMPORT & RESERVATION (Property-Specific)
# =============================================================================

class FileImport(models.Model):
    """
    Tracks file import history.
    PROPERTY-SPECIFIC: Each import is for a specific property.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with Errors'),
        ('failed', 'Failed'),
    ]
    
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='file_imports',
        null=True,
        blank=True,
        help_text="Property this import belongs to"
    )
    
    filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    rows_total = models.PositiveIntegerField(default=0)
    rows_processed = models.PositiveIntegerField(default=0)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    
    errors = models.JSONField(default=list, blank=True)
    
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    imported_by = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "File Import"
        verbose_name_plural = "File Imports"
    
    def __str__(self):
        hotel_str = f" ({self.hotel.name})" if self.hotel else ""
        return f"{self.filename}{hotel_str} - {self.get_status_display()}"
    
    @property
    def success_rate(self):
        if self.rows_total > 0:
            successful = self.rows_created + self.rows_updated
            return (Decimal(str(successful)) / Decimal(str(self.rows_total)) * 100).quantize(Decimal('0.1'))
        return Decimal('0.0')
    
    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def add_error(self, row_num, message):
        if self.errors is None:
            self.errors = []
        self.errors.append({'row': row_num, 'message': str(message)})
        self.save(update_fields=['errors'])


class Reservation(models.Model):
    """
    Core reservation/booking record.
    PROPERTY-SPECIFIC: Each reservation belongs to a property.
    """
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('no_show', 'No Show'),
    ]
    
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='reservations',
        null=True,
        blank=True,
        help_text="Property this reservation is for"
    )
    
    confirmation_no = models.CharField(max_length=50, db_index=True)
    original_confirmation_no = models.CharField(max_length=50, blank=True)
    
    booking_date = models.DateField(db_index=True)
    arrival_date = models.DateField(db_index=True)
    departure_date = models.DateField()
    cancellation_date = models.DateField(null=True, blank=True)
    
    nights = models.PositiveIntegerField(default=1)
    adults = models.PositiveIntegerField(default=2)
    children = models.PositiveIntegerField(default=0)
    
    lead_time_days = models.IntegerField(default=0, db_index=True)
    
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    room_type_name = models.CharField(max_length=100, blank=True)
    
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    rate_plan_name = models.CharField(max_length=100, blank=True)
    
    booking_source = models.ForeignKey(
        BookingSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    
    channel = models.ForeignKey(
        Channel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    
    guest = models.ForeignKey(
        Guest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    adr = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed', db_index=True)
    
    parent_reservation = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_rooms'
    )
    room_sequence = models.PositiveSmallIntegerField(default=1)
    is_multi_room = models.BooleanField(default=False)
    
    file_import = models.ForeignKey(
        FileImport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations'
    )
    
    raw_data = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-booking_date', '-arrival_date']
        verbose_name = "Reservation"
        verbose_name_plural = "Reservations"
        indexes = [
            models.Index(fields=['hotel', 'arrival_date', 'status']),
            models.Index(fields=['hotel', 'booking_date', 'arrival_date']),
            models.Index(fields=['lead_time_days']),
            models.Index(fields=['confirmation_no', 'room_sequence']),
        ]
        unique_together = ['hotel', 'confirmation_no', 'room_sequence']
    
    def __str__(self):
        return f"{self.original_confirmation_no or self.confirmation_no} - {self.arrival_date}"
    
    def save(self, *args, **kwargs):
        if self.arrival_date and self.booking_date:
            self.lead_time_days = (self.arrival_date - self.booking_date).days
        
        if self.nights and self.nights > 0 and self.total_amount:
            self.adr = (self.total_amount / self.nights).quantize(Decimal('0.01'))
        
        if self.booking_source and self.booking_source.channel:
            self.channel = self.booking_source.channel
        
        # Auto-set hotel from room_type if not set
        if not self.hotel and self.room_type and self.room_type.hotel:
            self.hotel = self.room_type.hotel
        
        super().save(*args, **kwargs)
    
    @property
    def total_guests(self):
        return self.adults + self.children
    
    @property
    def lead_time_bucket(self):
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
        if self.parent_reservation:
            return self.parent_reservation.linked_rooms.count() + 1
        return self.linked_rooms.count() + 1 if self.is_multi_room else 1
    
    @classmethod
    def parse_confirmation_no(cls, raw_confirmation):
        raw = str(raw_confirmation or '').strip()
        if not raw:
            return ('', 1)
        
        match = re.match(r'^(.+)-(\d+)$', raw)
        if match:
            return (match.group(1), int(match.group(2)))
        
        return (raw, 1)
    
    @classmethod
    def get_lead_time_distribution(cls, hotel=None, start_date=None, end_date=None, channel=None):
        """Get lead time distribution for analysis."""
        queryset = cls.objects.filter(status__in=['confirmed', 'checked_in', 'checked_out'])
        
        if hotel:
            queryset = queryset.filter(hotel=hotel)
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


# =============================================================================
# PICKUP ANALYSIS MODELS (Property-Specific)
# =============================================================================

class DailyPickupSnapshot(models.Model):
    """
    Daily snapshot of on-the-books (OTB) position.
    PROPERTY-SPECIFIC: Each property tracks its own pickup.
    """
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='daily_snapshots',
        help_text="Property this snapshot belongs to"
    )
    
    snapshot_date = models.DateField(db_index=True)
    arrival_date = models.DateField(db_index=True)
    days_out = models.PositiveIntegerField()
    
    otb_room_nights = models.PositiveIntegerField(default=0)
    otb_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    otb_reservations = models.PositiveIntegerField(default=0)
    
    otb_by_channel = models.JSONField(default=dict, blank=True)
    otb_by_room_type = models.JSONField(default=dict, blank=True)
    otb_by_rate_plan = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-snapshot_date', 'arrival_date']
        unique_together = ['hotel', 'snapshot_date', 'arrival_date']
        verbose_name = "Daily Pickup Snapshot"
        verbose_name_plural = "Daily Pickup Snapshots"
        indexes = [
            models.Index(fields=['hotel', 'arrival_date', 'days_out']),
            models.Index(fields=['hotel', 'snapshot_date']),
        ]
    
    def __str__(self):
        return f"{self.hotel.name}: {self.snapshot_date} → {self.arrival_date} ({self.days_out}d): {self.otb_room_nights} RN"
    
    @property
    def otb_adr(self):
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def save(self, *args, **kwargs):
        if self.arrival_date and self.snapshot_date:
            self.days_out = (self.arrival_date - self.snapshot_date).days
        super().save(*args, **kwargs)
    
    @classmethod
    def get_pickup_for_date(cls, hotel, arrival_date, from_days_out=90):
        return cls.objects.filter(
            hotel=hotel,
            arrival_date=arrival_date,
            days_out__lte=from_days_out
        ).order_by('-days_out')
    
    @classmethod
    def get_latest_otb(cls, hotel, arrival_date):
        return cls.objects.filter(
            hotel=hotel,
            arrival_date=arrival_date
        ).order_by('-snapshot_date').first()


class MonthlyPickupSnapshot(models.Model):
    """
    Aggregated monthly OTB snapshot.
    PROPERTY-SPECIFIC.
    """
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='monthly_snapshots'
    )
    
    snapshot_date = models.DateField(db_index=True)
    target_month = models.DateField(db_index=True)
    days_out = models.PositiveIntegerField()
    
    otb_room_nights = models.PositiveIntegerField(default=0)
    otb_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    otb_reservations = models.PositiveIntegerField(default=0)
    otb_occupancy_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    available_room_nights = models.PositiveIntegerField(default=0)
    
    otb_by_channel = models.JSONField(default=dict, blank=True)
    otb_by_room_type = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-snapshot_date', 'target_month']
        unique_together = ['hotel', 'snapshot_date', 'target_month']
        verbose_name = "Monthly Pickup Snapshot"
        verbose_name_plural = "Monthly Pickup Snapshots"
        indexes = [
            models.Index(fields=['hotel', 'target_month', 'days_out']),
        ]
    
    def __str__(self):
        month_str = self.target_month.strftime('%b %Y')
        return f"{self.hotel.name}: {self.snapshot_date} → {month_str} ({self.days_out}d): {self.otb_room_nights} RN"
    
    @property
    def otb_adr(self):
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def save(self, *args, **kwargs):
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
    def get_stly(cls, hotel, target_month, days_out):
        from dateutil.relativedelta import relativedelta
        
        stly_month = target_month - relativedelta(years=1)
        
        return cls.objects.filter(
            hotel=hotel,
            target_month=stly_month,
            days_out__gte=days_out - 3,
            days_out__lte=days_out + 3
        ).order_by('days_out').first()


class PickupCurve(models.Model):
    """
    Historical pickup curve showing booking patterns.
    PROPERTY-SPECIFIC.
    """
    SEASON_TYPES = [
        ('peak', 'Peak Season'),
        ('high', 'High Season'),
        ('shoulder', 'Shoulder Season'),
        ('low', 'Low Season'),
    ]
    
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='pickup_curves'
    )
    
    season_type = models.CharField(max_length=20, choices=SEASON_TYPES, db_index=True)
    season = models.ForeignKey(
        Season,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pickup_curves'
    )
    
    days_out = models.PositiveIntegerField()
    cumulative_percent = models.DecimalField(max_digits=5, decimal_places=2)
    
    sample_size = models.PositiveIntegerField(default=0)
    std_deviation = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    curve_version = models.PositiveIntegerField(default=1)
    built_from_start = models.DateField(null=True, blank=True)
    built_from_end = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['hotel', 'season_type', '-days_out']
        unique_together = ['hotel', 'season_type', 'season', 'days_out', 'curve_version']
        verbose_name = "Pickup Curve"
        verbose_name_plural = "Pickup Curves"
        indexes = [
            models.Index(fields=['hotel', 'season_type', 'days_out']),
        ]
    
    def __str__(self):
        season_name = self.season.name if self.season else self.get_season_type_display()
        return f"{self.hotel.name} - {season_name} @ {self.days_out}d: {self.cumulative_percent}%"
    
    @classmethod
    def get_curve_for_season(cls, hotel, season_type, season=None):
        filters = {'hotel': hotel, 'season_type': season_type}
        if season:
            filters['season'] = season
        else:
            filters['season__isnull'] = True
        
        return cls.objects.filter(**filters).order_by('-days_out')
    
    @classmethod
    def get_expected_percent_at_days_out(cls, hotel, season_type, days_out, season=None):
        curve = cls.get_curve_for_season(hotel, season_type, season)
        
        if not curve.exists():
            return None
        
        point_before = curve.filter(days_out__gte=days_out).order_by('days_out').first()
        point_after = curve.filter(days_out__lte=days_out).order_by('-days_out').first()
        
        if point_before and point_before.days_out == days_out:
            return point_before.cumulative_percent
        
        if point_before and point_after and point_before != point_after:
            days_range = point_before.days_out - point_after.days_out
            pct_range = point_after.cumulative_percent - point_before.cumulative_percent
            
            if days_range > 0:
                days_from_before = point_before.days_out - days_out
                interpolated = point_before.cumulative_percent + (
                    pct_range * Decimal(str(days_from_before)) / Decimal(str(days_range))
                )
                return interpolated.quantize(Decimal('0.01'))
        
        if point_before:
            return point_before.cumulative_percent
        if point_after:
            return point_after.cumulative_percent
        
        return None


class OccupancyForecast(models.Model):
    """
    Generated occupancy and revenue forecast.
    PROPERTY-SPECIFIC.
    """
    CONFIDENCE_LEVELS = [
        ('very_low', 'Very Low'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='forecasts'
    )
    
    target_month = models.DateField(db_index=True)
    forecast_date = models.DateField(db_index=True)
    days_out = models.PositiveIntegerField()
    
    season = models.ForeignKey(
        Season,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='forecasts'
    )
    
    available_room_nights = models.PositiveIntegerField(default=0)
    
    # Current OTB
    otb_room_nights = models.PositiveIntegerField(default=0)
    otb_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    otb_occupancy_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Pickup Forecast
    pickup_forecast_nights = models.PositiveIntegerField(default=0)
    pickup_forecast_occupancy = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    pickup_forecast_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    pickup_expected_additional = models.PositiveIntegerField(default=0)
    
    forecast_from_curve = models.PositiveIntegerField(default=0)
    forecast_from_stly = models.PositiveIntegerField(default=0)
    forecast_from_velocity = models.PositiveIntegerField(default=0)
    
    confidence_level = models.CharField(max_length=20, choices=CONFIDENCE_LEVELS, default='medium')
    confidence_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('50.00'))
    
    # Scenario Forecast
    scenario_occupancy = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    scenario_room_nights = models.PositiveIntegerField(default=0)
    scenario_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Variance
    variance_nights = models.IntegerField(default=0)
    variance_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    
    # STLY
    stly_occupancy = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    stly_otb_at_same_point = models.PositiveIntegerField(null=True, blank=True)
    vs_stly_pace_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    
    # Revenue Details
    forecast_adr = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    forecast_revpar = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    forecast_commission = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    forecast_net_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['hotel', 'target_month', '-forecast_date']
        unique_together = ['hotel', 'target_month', 'forecast_date']
        verbose_name = "Occupancy Forecast"
        verbose_name_plural = "Occupancy Forecasts"
        indexes = [
            models.Index(fields=['hotel', 'target_month', 'days_out']),
        ]
    
    def __str__(self):
        month_str = self.target_month.strftime('%b %Y')
        return f"{self.hotel.name} - {month_str}: {self.pickup_forecast_occupancy}% / {self.scenario_occupancy}%"
    
    def save(self, *args, **kwargs):
        if self.target_month and self.forecast_date:
            self.days_out = (self.target_month - self.forecast_date).days
        
        if self.available_room_nights > 0:
            self.otb_occupancy_percent = (
                Decimal(str(self.otb_room_nights)) / 
                Decimal(str(self.available_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
            
            self.pickup_forecast_occupancy = (
                Decimal(str(self.pickup_forecast_nights)) / 
                Decimal(str(self.available_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
        
        self.variance_nights = self.pickup_forecast_nights - self.scenario_room_nights
        if self.scenario_room_nights > 0:
            self.variance_percent = (
                Decimal(str(self.variance_nights)) / 
                Decimal(str(self.scenario_room_nights)) * 
                Decimal('100.00')
            ).quantize(Decimal('0.01'))
        
        if self.available_room_nights > 0:
            self.forecast_revpar = (
                self.pickup_forecast_revenue / 
                Decimal(str(self.available_room_nights))
            ).quantize(Decimal('0.01'))
        
        self.forecast_net_revenue = self.pickup_forecast_revenue - self.forecast_commission
        
        # Set confidence level
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
        if self.otb_room_nights > 0:
            return (self.otb_revenue / self.otb_room_nights).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    @property
    def is_ahead_of_stly(self):
        if self.vs_stly_pace_percent is not None:
            return self.vs_stly_pace_percent > 0
        return None
    
    @property
    def is_ahead_of_scenario(self):
        return self.variance_nights > 0
    
    @classmethod
    def get_latest_forecast(cls, hotel, target_month):
        return cls.objects.filter(
            hotel=hotel,
            target_month=target_month
        ).order_by('-forecast_date').first()
    
    @classmethod
    def get_forecast_history(cls, hotel, target_month, limit=30):
        return cls.objects.filter(
            hotel=hotel,
            target_month=target_month
        ).order_by('-forecast_date')[:limit]
    
    def generate_insight(self):
        insights = []
        
        if self.variance_nights > 0:
            insights.append(
                f"Pickup forecast is {self.variance_nights} room nights "
                f"({abs(self.variance_percent):.1f}%) above scenario target."
            )
        elif self.variance_nights < 0:
            insights.append(
                f"Pickup forecast is {abs(self.variance_nights)} room nights "
                f"({abs(self.variance_percent):.1f}%) below scenario target."
            )
        
        if self.vs_stly_pace_percent is not None:
            if self.vs_stly_pace_percent > 5:
                insights.append(
                    f"You're {self.vs_stly_pace_percent:.1f}% ahead of last year's pace."
                )
            elif self.vs_stly_pace_percent < -5:
                insights.append(
                    f"You're {abs(self.vs_stly_pace_percent):.1f}% behind last year's pace."
                )
        
        if self.days_out > 60:
            insights.append(
                f"Confidence: {self.confidence_level} ({self.confidence_percent:.0f}%) at {self.days_out} days out."
            )
        
        return " ".join(insights) if insights else "Forecast is on track."