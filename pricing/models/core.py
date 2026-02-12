"""
Core models: Organization, Property, and Modifier configuration.
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
    
    service_charge_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('10.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Service charge percentage (e.g., 10.00 for 10%)"
    )
    
    tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('16.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Tax percentage (e.g., 16.00 for 16% GST)"
    )
    
    tax_on_service_charge = models.BooleanField(
        default=True,
        help_text="Whether tax is calculated on subtotal + service charge (True) or just subtotal (False)"
    )
    
    # Warning thresholds
    min_rate_warning = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Warn if any rate falls below this amount"
    )
    
    max_discount_warning = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal('40.00'),
        help_text="Warn if total discount percentage exceeds this value"
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

class ModifierTemplate(models.Model):
    """
    Organization-level modifier templates.
    
    Properties can inherit these templates and customize the values.
    Templates define the structure; properties define the actual values.
    
    Example templates:
    - Season Index (applies to seasons)
    - Channel Discount (applies to channels)
    - Member Discount (applies to guest types)
    - LOS Discount (applies to length of stay)
    """
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='modifier_templates',
        help_text="Organization this template belongs to"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Template name (e.g., 'Season Index', 'Channel Discount')"
    )
    
    code = models.SlugField(
        max_length=50,
        help_text="Unique code (e.g., 'season-index', 'channel-discount')"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Description of what this modifier does"
    )
    
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
        blank=True,
        symmetrical=False,
        related_name='stacked_into',
        help_text="Source modifiers if this is a stacked modifier"
    )
    
    MODIFIER_TYPES = [
        ('index', 'Index/Multiplier'),      # Value like 1.20 means +20%
        ('discount', 'Discount'),            # Value like 10 means -10%
        ('surcharge', 'Surcharge'),          # Value like 5 means +5%
    ]
    modifier_type = models.CharField(
        max_length=20,
        choices=MODIFIER_TYPES,
        help_text="How the value is interpreted"
    )
    
    APPLIES_TO_CHOICES = [
        ('season', 'Season'),
        ('room_type', 'Room Type'),
        ('channel', 'Channel'),
        ('promo', 'Promotion/Offer'),
        ('los', 'Length of Stay'),
        ('booking_window', 'Booking Window'),
        ('guest_type', 'Guest Type'),
    ]
    applies_to = models.CharField(
        max_length=20,
        choices=APPLIES_TO_CHOICES,
        help_text="What entity this modifier is linked to"
    )
    
    default_value = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Default value for new property modifiers"
    )
    
    stack_order = models.PositiveIntegerField(
        default=100,
        help_text="Order in stacking calculation (lower = applied first)"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this template is active"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['organization', 'stack_order', 'name']
        unique_together = ['organization', 'code']
        verbose_name = "Modifier Template"
        verbose_name_plural = "Modifier Templates"
    
    def __str__(self):
        return f"{self.name} ({self.get_modifier_type_display()})"
    
    def get_default_adjustment_display(self):
        """Display-friendly default value."""
        if self.modifier_type == 'index':
            pct = (self.default_value - Decimal('1.00')) * 100
            if pct >= 0:
                return f"+{pct:.0f}%"
            return f"{pct:.0f}%"
        elif self.modifier_type == 'discount':
            return f"-{self.default_value}%"
        else:
            return f"+{self.default_value}%"
        
class PropertyModifier(models.Model):
    """
    Property-specific modifier with actual value.
    
    Can be created from a template (inherits structure) or as a custom
    property-specific modifier.
    
    Examples:
    - Peak Season index ×1.20 for Hotel A
    - OTA channel discount 0% for Hotel A
    - Genius member discount 10% for Hotel A
    """
    hotel = models.ForeignKey(
        'Property',
        on_delete=models.CASCADE,
        related_name='pricing_modifiers',
        help_text="Property this modifier belongs to"
    )
    
    # Link to template (optional)
    template = models.ForeignKey(
        ModifierTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='property_instances',
        help_text="Template this modifier is based on (optional)"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Modifier name (e.g., 'Peak Season', 'OTA Discount')"
    )
    
    code = models.SlugField(
        max_length=50,
        help_text="Unique code within property"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Description or notes"
    )
    
    MODIFIER_TYPES = [
        ('index', 'Index/Multiplier'),
        ('discount', 'Discount'),
        ('surcharge', 'Surcharge'),
    ]
    modifier_type = models.CharField(
        max_length=20,
        choices=MODIFIER_TYPES,
        help_text="How the value is interpreted"
    )
    
    APPLIES_TO_CHOICES = [
        ('season', 'Season'),
        ('room_type', 'Room Type'),
        ('channel', 'Channel'),
        ('promo', 'Promotion/Offer'),
        ('los', 'Length of Stay'),
        ('booking_window', 'Booking Window'),
        ('guest_type', 'Guest Type'),
    ]
    applies_to = models.CharField(
        max_length=20,
        choices=APPLIES_TO_CHOICES,
        help_text="What entity this modifier is linked to"
    )
    
    value = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="For index: multiplier (1.20 = +20%). For discount/surcharge: percentage (10 = 10%)"
    )
    
    stack_order = models.PositiveIntegerField(
        default=100,
        help_text="Order in stacking calculation (lower = applied first)"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this modifier is active"
    )
    
    # ==========================================================================
    # LINKED ENTITIES (for specific modifier types)
    # ==========================================================================
    
    # For season-based modifiers
    season = models.ForeignKey(
        'Season',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pricing_modifiers',
        help_text="Season this modifier applies to (if applies_to='season')"
    )
    
    # For room type modifiers
    room_type = models.ForeignKey(
        'RoomType',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pricing_modifiers',
        help_text="Room type this modifier applies to (if applies_to='room_type')"
    )
    
    # For channel modifiers
    channel = models.ForeignKey(
        'Channel',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pricing_modifiers',
        help_text="Channel this modifier applies to (if applies_to='channel')"
    )
    
    # ==========================================================================
    # LOS / BOOKING WINDOW SETTINGS
    # ==========================================================================
    
    min_nights = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minimum nights for LOS modifier"
    )
    
    max_nights = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum nights for LOS modifier"
    )
    
    min_advance_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minimum days in advance for booking window modifier"
    )
    
    max_advance_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum days in advance for booking window modifier"
    )
    
    # ==========================================================================
    # DATE RANGE (for promos)
    # ==========================================================================
    
    valid_from = models.DateField(
        null=True,
        blank=True,
        help_text="Start date for this modifier (for promos)"
    )
    
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="End date for this modifier (for promos)"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['hotel', 'stack_order', 'name']
        unique_together = ['hotel', 'code']
        verbose_name = "Property Modifier"
        verbose_name_plural = "Property Modifiers"
    
    def __str__(self):
        return f"{self.name} ({self.get_adjustment_display()})"
    
    def save(self, *args, **kwargs):
        """Inherit from template if linked and new."""
        if self.template and not self.pk:
            if not self.name:
                self.name = self.template.name
            if not self.code:
                self.code = self.template.code
            if not self.modifier_type:
                self.modifier_type = self.template.modifier_type
            if not self.applies_to:
                self.applies_to = self.template.applies_to
            if self.stack_order == 100:
                self.stack_order = self.template.stack_order
            if self.value == Decimal('0.00'):
                self.value = self.template.default_value
        super().save(*args, **kwargs)
    
    def get_adjustment(self):
        """
        Get adjustment as a decimal for calculation.
        
        Returns:
            Decimal: Adjustment value
            - Index 1.20 returns +0.20
            - Discount 10% returns -0.10
            - Surcharge 5% returns +0.05
        """
        if self.modifier_type == 'index':
            return self.value - Decimal('1.00')
        elif self.modifier_type == 'discount':
            return -self.value / Decimal('100.00')
        else:  # surcharge
            return self.value / Decimal('100.00')
    
    def get_adjustment_percent(self):
        """Get adjustment as percentage for display."""
        return self.get_adjustment() * Decimal('100.00')
    
    def get_adjustment_display(self):
        """Display-friendly adjustment value."""
        if self.modifier_type == 'index':
            pct = (self.value - Decimal('1.00')) * 100
            if pct >= 0:
                return f"+{pct:.0f}%"
            return f"{pct:.0f}%"
        elif self.modifier_type == 'discount':
            return f"-{self.value}%"
        else:
            return f"+{self.value}%"
    
    def get_value_display(self):
        """Display the raw value."""
        if self.modifier_type == 'index':
            return f"×{self.value}"
        else:
            return f"{self.value}%"
    
    def matches_context(self, context):
        """
        Check if this modifier applies to the given booking context.
        
        Args:
            context: dict with keys like season, room_type, channel, nights,
                     booking_date, arrival_date, guest_type, promos
        
        Returns:
            bool: True if modifier applies
        """
        if not self.is_active:
            return False
        
        # Check date validity for promos
        if self.valid_from or self.valid_until:
            arrival_date = context.get('arrival_date')
            if arrival_date:
                if self.valid_from and arrival_date < self.valid_from:
                    return False
                if self.valid_until and arrival_date > self.valid_until:
                    return False
        
        # Check based on applies_to type
        if self.applies_to == 'season':
            return self.season_id == context.get('season_id')
        
        elif self.applies_to == 'room_type':
            return self.room_type_id == context.get('room_type_id')
        
        elif self.applies_to == 'channel':
            return self.channel_id == context.get('channel_id')
        
        elif self.applies_to == 'los':
            nights = context.get('nights', 1)
            if self.min_nights and nights < self.min_nights:
                return False
            if self.max_nights and nights > self.max_nights:
                return False
            return True
        
        elif self.applies_to == 'booking_window':
            booking_date = context.get('booking_date')
            arrival_date = context.get('arrival_date')
            if booking_date and arrival_date:
                advance_days = (arrival_date - booking_date).days
                if self.min_advance_days and advance_days < self.min_advance_days:
                    return False
                if self.max_advance_days and advance_days > self.max_advance_days:
                    return False
                return True
            return False
        
        elif self.applies_to == 'guest_type':
            return self.code == context.get('guest_type')
        
        elif self.applies_to == 'promo':
            return self.code in context.get('promos', [])
        
        return False


# =============================================================================
# MODIFIER RULES (Combination/Restriction Rules)
# =============================================================================

class ModifierRule(models.Model):
    """
    Rules that control when/how modifiers can be combined.
    
    Examples:
    - Genius discount only applies to OTA channel
    - Early Bird cannot combine with Last Minute
    - Mobile discount requires Member discount
    """
    modifier = models.ForeignKey(
        PropertyModifier,
        on_delete=models.CASCADE,
        related_name='rules',
        help_text="Modifier this rule applies to"
    )
    
    RULE_TYPES = [
        ('channel_only', 'Only for specific channels'),
        ('exclude_channel', 'Exclude from specific channels'),
        ('room_type_only', 'Only for specific room types'),
        ('exclude_room_type', 'Exclude from specific room types'),
        ('not_with', 'Cannot combine with other modifiers'),
        ('requires', 'Requires other modifiers to be active'),
        ('season_only', 'Only for specific seasons'),
        ('exclude_season', 'Exclude from specific seasons'),
    ]
    rule_type = models.CharField(
        max_length=20,
        choices=RULE_TYPES,
        help_text="Type of rule"
    )
    
    # For channel rules
    channels = models.ManyToManyField(
        'Channel',
        blank=True,
        related_name='modifier_rules',
        help_text="Channels this rule references"
    )
    
    # For room type rules
    room_types = models.ManyToManyField(
        'RoomType',
        blank=True,
        related_name='modifier_rules',
        help_text="Room types this rule references"
    )
    
    # For season rules
    seasons = models.ManyToManyField(
        'Season',
        blank=True,
        related_name='modifier_rules',
        help_text="Seasons this rule references"
    )
    
    # For modifier combination rules
    other_modifiers = models.ManyToManyField(
        PropertyModifier,
        blank=True,
        related_name='referenced_by_rules',
        help_text="Other modifiers this rule references"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this rule is active"
    )
    
    error_message = models.CharField(
        max_length=200,
        blank=True,
        help_text="Custom error message when rule fails"
    )
    
    class Meta:
        ordering = ['modifier', 'rule_type']
        verbose_name = "Modifier Rule"
        verbose_name_plural = "Modifier Rules"
    
    def __str__(self):
        return f"{self.modifier.name} - {self.get_rule_type_display()}"
    
    def check_rule(self, context):
        """
        Check if this rule passes for the given context.
        
        Args:
            context: dict with keys like channel, room_type, season,
                     active_modifiers, etc.
        
        Returns:
            tuple: (passes: bool, message: str or None)
        """
        if not self.is_active:
            return True, None
        
        # Channel only
        if self.rule_type == 'channel_only':
            channel = context.get('channel')
            allowed_channels = self.channels.all()
            if allowed_channels.exists() and channel:
                if channel not in allowed_channels:
                    msg = self.error_message or f"Only available for: {', '.join(c.name for c in allowed_channels)}"
                    return False, msg
        
        # Exclude channel
        elif self.rule_type == 'exclude_channel':
            channel = context.get('channel')
            excluded_channels = self.channels.all()
            if channel and channel in excluded_channels:
                msg = self.error_message or f"Not available for {channel.name}"
                return False, msg
        
        # Room type only
        elif self.rule_type == 'room_type_only':
            room_type = context.get('room_type')
            allowed_rooms = self.room_types.all()
            if allowed_rooms.exists() and room_type:
                if room_type not in allowed_rooms:
                    msg = self.error_message or f"Only available for: {', '.join(r.name for r in allowed_rooms)}"
                    return False, msg
        
        # Exclude room type
        elif self.rule_type == 'exclude_room_type':
            room_type = context.get('room_type')
            excluded_rooms = self.room_types.all()
            if room_type and room_type in excluded_rooms:
                msg = self.error_message or f"Not available for {room_type.name}"
                return False, msg
        
        # Season only
        elif self.rule_type == 'season_only':
            season = context.get('season')
            allowed_seasons = self.seasons.all()
            if allowed_seasons.exists() and season:
                if season not in allowed_seasons:
                    msg = self.error_message or f"Only available for: {', '.join(s.name for s in allowed_seasons)}"
                    return False, msg
        
        # Exclude season
        elif self.rule_type == 'exclude_season':
            season = context.get('season')
            excluded_seasons = self.seasons.all()
            if season and season in excluded_seasons:
                msg = self.error_message or f"Not available in {season.name}"
                return False, msg
        
        # Not with (cannot combine)
        elif self.rule_type == 'not_with':
            active_modifiers = context.get('active_modifiers', [])
            active_ids = [m.id for m in active_modifiers]
            blocked = self.other_modifiers.filter(id__in=active_ids)
            if blocked.exists():
                msg = self.error_message or f"Cannot combine with: {', '.join(m.name for m in blocked)}"
                return False, msg
        
        # Requires
        elif self.rule_type == 'requires':
            active_modifiers = context.get('active_modifiers', [])
            active_ids = [m.id for m in active_modifiers]
            required = self.other_modifiers.all()
            missing = required.exclude(id__in=active_ids)
            if missing.exists():
                msg = self.error_message or f"Requires: {', '.join(m.name for m in missing)}"
                return False, msg
        
        return True, None

# =============================================================================
# PROPERTY-SPECIFIC MODELS
# =============================================================================

