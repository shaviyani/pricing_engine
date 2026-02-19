"""
Pricing models: PricingMatrixVersion, Season, RoomType, RatePlan, Channel,
TravelAgent, RateModifier, SeasonModifierOverride, RoomTypeSeasonModifier,
DateRateOverride, DateRateOverridePeriod,
BookingWindowConfig, BookingWindowBand, DynamicPricingRule,
DynamicPricingBand, DynamicPricingMultiplier, EventUplift.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date, timedelta
import re

from .core import Property


# =============================================================================
# PRICING MATRIX VERSION
# =============================================================================

class PricingMatrixVersion(models.Model):
    """
    A complete snapshot of all pricing configuration for a property.
    
    At any time there is exactly ONE published version per property.
    The pricing matrix reads from the published version.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]
    
    hotel = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='pricing_versions',
    )
    version_number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft', db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=100, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-version_number']
        unique_together = ['hotel', 'version_number']
        verbose_name = "Pricing Matrix Version"
        verbose_name_plural = "Pricing Matrix Versions"
    
    def __str__(self):
        return f"v{self.version_number} {self.name} ({self.get_status_display()})"
    
    @classmethod
    def get_published(cls, hotel):
        return cls.objects.filter(hotel=hotel, status='published').first()
    
    @classmethod
    def get_draft(cls, hotel):
        return cls.objects.filter(hotel=hotel, status='draft').first()
    
    @classmethod
    def get_next_version_number(cls, hotel):
        last = cls.objects.filter(hotel=hotel).order_by('-version_number').first()
        return (last.version_number + 1) if last else 1


# =============================================================================
# PROPERTY-SPECIFIC MODELS (versioned)
# =============================================================================

class Season(models.Model):
    """Pricing season with date range and index multiplier. VERSIONED."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='seasons')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='seasons', null=True, blank=True)
    name = models.CharField(max_length=100)
    
    SEASON_TYPE_CHOICES = [
        ('peak', 'Peak Season'),
        ('shoulder', 'Shoulder Season'),
        ('low', 'Low Season'),
    ]
    season_type = models.CharField(max_length=10, choices=SEASON_TYPE_CHOICES, default='shoulder')
    
    start_date = models.DateField()
    end_date = models.DateField()
    season_index = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1.00'))
    expected_occupancy = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('70.00'))
    
    class Meta:
        ordering = ['hotel', 'start_date']
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
    
    def __str__(self):
        return f"{self.name} ({self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d')})"
    
    def date_range_display(self):
        return f"{self.start_date.strftime('%b %d, %Y')} - {self.end_date.strftime('%b %d, %Y')}"
    
    def get_occupancy_display(self):
        return f"{self.expected_occupancy}%"
    
    def get_day_count(self):
        return (self.end_date - self.start_date).days + 1


class RoomType(models.Model):
    """Room category with flexible pricing. VERSIONED."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='room_types')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='room_types', null=True, blank=True)
    name = models.CharField(max_length=100)
    base_rate = models.DecimalField(max_digits=10, decimal_places=2)
    room_index = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    room_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    PRICING_METHODS = [('direct', 'Direct Base Rate'), ('index', 'Index Multiplier'), ('adjustment', 'Fixed Adjustment')]
    pricing_method = models.CharField(max_length=20, choices=PRICING_METHODS, default='index')
    sort_order = models.PositiveIntegerField(default=0)
    number_of_rooms = models.PositiveIntegerField(default=10)
    description = models.TextField(blank=True, default='')
    target_occupancy = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('70.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    class Meta:
        ordering = ['hotel', 'sort_order', 'name']
        verbose_name = "Room Type"
        verbose_name_plural = "Room Types"
    
    def __str__(self):
        count_str = f" ({self.number_of_rooms} rooms)" if self.number_of_rooms else ""
        if self.pricing_method == 'index':
            return f"{self.name} (x{self.room_index}){count_str}"
        elif self.pricing_method == 'adjustment':
            return f"{self.name} (+${self.room_adjustment}){count_str}"
        elif self.pricing_method == 'direct':
            return f"{self.name} (${self.base_rate}){count_str}"
        return f"{self.name}{count_str}"
    
    def get_effective_base_rate(self, reference_rate=None):
        if self.pricing_method == 'direct':
            return self.base_rate
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
        ref = self.hotel.reference_base_rate if self.hotel else self.base_rate
        if ref and ref > 0:
            effective = self.get_effective_base_rate()
            return ((effective - ref) / ref * Decimal('100')).quantize(Decimal('0.1'))
        return Decimal('0.0')
    
    def get_season_modifier(self, season):
        try:
            override = self.season_modifiers.get(season=season)
            return override.modifier
        except RoomTypeSeasonModifier.DoesNotExist:
            return Decimal('1.00')
    
    def get_effective_season_index(self, season):
        return (season.season_index * self.get_season_modifier(season)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)


# =============================================================================
# RATE PLANS & CHANNELS (property-scoped + versioned)
# =============================================================================

class RatePlan(models.Model):
    """Board type with meal supplement. PROPERTY-SPECIFIC + VERSIONED."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='rate_plans')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='rate_plans', null=True, blank=True)
    name = models.CharField(max_length=100)
    meal_supplement = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sort_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Rate Plan"
        verbose_name_plural = "Rate Plans"
    
    def __str__(self):
        if self.meal_supplement > 0:
            return f"{self.name} (+${self.meal_supplement}/person)"
        return f"{self.name} (Room Only)"


class Channel(models.Model):
    """Booking channel with discount and commission. PROPERTY-SPECIFIC + VERSIONED."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='channels')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='channels', null=True, blank=True)
    name = models.CharField(max_length=100)
    base_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    distribution_share_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    sort_order = models.PositiveIntegerField(default=0)
    
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
    
    @classmethod
    def validate_total_distribution(cls, hotel=None, version=None):
        qs = cls.objects.all()
        if hotel: qs = qs.filter(hotel=hotel)
        if version: qs = qs.filter(version=version)
        total = qs.aggregate(total=models.Sum('distribution_share_percent'))['total'] or Decimal('0.00')
        is_valid = abs(total - Decimal('100.00')) < Decimal('0.01')
        if is_valid:
            message = f"Total distribution: {total}%"
        elif total == Decimal('0.00'):
            message = "No distribution shares set"
        elif total < Decimal('100.00'):
            message = f"Total distribution: {total}% (missing {Decimal('100.00') - total}%)"
        else:
            message = f"Total distribution: {total}% (exceeds by {total - Decimal('100.00')}%)"
        return is_valid, total, message
    
    @classmethod
    def get_distribution_mix(cls, hotel=None, version=None):
        qs = cls.objects.filter(distribution_share_percent__gt=0)
        if hotel: qs = qs.filter(hotel=hotel)
        if version: qs = qs.filter(version=version)
        return {c.id: c.distribution_share_percent / Decimal('100.00') for c in qs}
    
    @classmethod
    def normalize_distribution(cls, hotel=None, version=None):
        qs = cls.objects.filter(distribution_share_percent__gt=0)
        if hotel: qs = qs.filter(hotel=hotel)
        if version: qs = qs.filter(version=version)
        channels = list(qs)
        if not channels: return
        total = sum(c.distribution_share_percent for c in channels)
        if total == Decimal('0.00'): return
        factor = Decimal('100.00') / total
        for channel in channels:
            channel.distribution_share_percent = (channel.distribution_share_percent * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            channel.save()
    
    @classmethod
    def distribute_equally(cls, hotel=None, version=None):
        qs = cls.objects.all()
        if hotel: qs = qs.filter(hotel=hotel)
        if version: qs = qs.filter(version=version)
        channels = list(qs)
        if not channels: return
        share = (Decimal('100.00') / len(channels)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        for channel in channels:
            channel.distribution_share_percent = share
            channel.save()


# =============================================================================
# TRAVEL AGENT
# =============================================================================

def generate_agent_token():
    """Generate a unique 8-character alphanumeric token."""
    import string
    import secrets
    alphabet = string.ascii_letters + string.digits
    for _ in range(100):  # max attempts
        token = ''.join(secrets.choice(alphabet) for _ in range(8))
        if not TravelAgent.objects.filter(token=token).exists():
            return token
    raise RuntimeError('Could not generate unique agent token')


class TravelAgent(models.Model):
    """
    Individual travel agent company with a unique URL token.

    Each agent links to a Property and optionally to a Channel.
    The token generates a unique public URL for this agent's rate card.
    NOT versioned — operational entity like DateRateOverride.
    """
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='travel_agents',
    )
    channel = models.ForeignKey(
        'Channel', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='travel_agents',
        help_text="Channel with this agent's rates. Leave blank for default agent channel."
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    token = models.CharField(
        max_length=8, unique=True, editable=False,
        default=generate_agent_token,
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['property', 'name']

    def __str__(self):
        return f"{self.name} ({self.property.name})"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('pricing:agent_rate_card', kwargs={'token': self.token})

    def get_channel(self):
        """Return linked channel or fall back to property's agent channel."""
        if self.channel_id:
            return self.channel
        version = PricingMatrixVersion.get_published(self.property)
        qs = Channel.objects.filter(hotel=self.property)
        if version:
            qs = qs.filter(version=version)
        return qs.filter(name__icontains='agent').first()


class RateModifier(models.Model):
    """Additional discount modifiers for channels. VERSIONED."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='rate_modifiers')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='rate_modifiers', null=True, blank=True)
    name = models.CharField(max_length=100)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    stackable = models.BooleanField(default=False)
    is_stacked = models.BooleanField(default=False)
    stacked_from = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='stacked_into')
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    MODIFIER_TYPES = [
        ('standard', 'Standard Rate'), ('member', 'Member/Loyalty Program'),
        ('mobile', 'Mobile App Exclusive'), ('promo', 'Promotional'),
        ('corporate', 'Corporate Rate'), ('last_minute', 'Last Minute Deal'),
        ('early_bird', 'Early Bird'),
    ]
    modifier_type = models.CharField(max_length=20, choices=MODIFIER_TYPES, default='standard')
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['channel', 'sort_order', 'name']
        verbose_name = "Rate Modifier"
        verbose_name_plural = "Rate Modifiers"
    
    def __str__(self):
        if self.discount_percent > 0:
            return f"{self.channel.name} - {self.name} (-{self.discount_percent}%)"
        return f"{self.channel.name} - {self.name}"
    
    def get_discount_for_season(self, season):
        season_discount, created = SeasonModifierOverride.objects.get_or_create(
            modifier=self, season=season,
            defaults={'discount_percent': self.discount_percent})
        return season_discount.discount_percent
    
    def total_discount_from_bar(self):
        return self.channel.base_discount_percent + self.discount_percent


class SeasonModifierOverride(models.Model):
    """Season-specific discount for rate modifiers. Versioned through modifier chain."""
    modifier = models.ForeignKey(RateModifier, on_delete=models.CASCADE, related_name='season_discounts')
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='modifier_discounts')
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    is_customized = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['season', 'modifier__channel', 'modifier__sort_order']
        verbose_name = "Season Modifier Override"
        verbose_name_plural = "Season Modifier Overrides"
        unique_together = ['modifier', 'season']
    
    def __str__(self):
        return f"{self.modifier.name} -> {self.season.name}: -{self.discount_percent}%"
    
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
    """Per-room-type, per-season multiplier. Versioned through room_type and season."""
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name='season_modifiers')
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='room_type_modifiers')
    modifier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('5.00'))])
    notes = models.CharField(max_length=200, blank=True, default='')
    
    class Meta:
        ordering = ['season__start_date', 'room_type__sort_order']
        verbose_name = "Room Type Season Modifier"
        verbose_name_plural = "Room Type Season Modifiers"
        unique_together = ['room_type', 'season']
    
    def __str__(self):
        return f"{self.room_type.name} x {self.season.name}: x{self.modifier}"
    
    def get_effective_index(self):
        return (self.season.season_index * self.modifier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# =============================================================================
# DATE RATE OVERRIDES (NOT versioned - operational)
# =============================================================================

class DateRateOverride(models.Model):
    OVERRIDE_TYPE_CHOICES = [('amount', 'Fixed Amount ($)'), ('percentage', 'Percentage (%)')]
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='date_rate_overrides')
    name = models.CharField(max_length=100)
    override_type = models.CharField(max_length=20, choices=OVERRIDE_TYPE_CHOICES, default='amount')
    adjustment = models.DecimalField(max_digits=10, decimal_places=2)
    priority = models.PositiveIntegerField(default=50, validators=[MinValueValidator(1), MaxValueValidator(100)])
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-priority', 'name']
        verbose_name = "Date Rate Override"
        verbose_name_plural = "Date Rate Overrides"
    
    def __str__(self):
        sign = '+' if self.adjustment >= 0 else ''
        adj_str = f"{sign}${self.adjustment}" if self.override_type == 'amount' else f"{sign}{self.adjustment}%"
        status = "" if self.active else " [INACTIVE]"
        return f"{self.name} ({adj_str}){status}"
    
    def get_adjustment_display(self):
        sign = '+' if self.adjustment >= 0 else ''
        return f"{sign}${self.adjustment}" if self.override_type == 'amount' else f"{sign}{self.adjustment}%"
    
    def get_periods_display(self):
        periods = self.periods.all()
        if not periods: return "No dates set"
        displays = []
        for p in periods:
            if p.start_date == p.end_date:
                displays.append(p.start_date.strftime('%b %d, %Y'))
            else:
                displays.append(f"{p.start_date.strftime('%b %d')} - {p.end_date.strftime('%b %d, %Y')}")
        return ", ".join(displays)
    
    def applies_to_date(self, check_date):
        if not self.active: return False
        return self.periods.filter(start_date__lte=check_date, end_date__gte=check_date).exists()
    
    def calculate_adjusted_bar(self, base_bar):
        if self.override_type == 'amount':
            adjusted = base_bar + self.adjustment
        else:
            adjusted = base_bar * (Decimal('1.00') + self.adjustment / Decimal('100.00'))
        return max(adjusted, Decimal('0.00')).quantize(Decimal('0.01'))


class DateRateOverridePeriod(models.Model):
    override = models.ForeignKey(DateRateOverride, on_delete=models.CASCADE, related_name='periods')
    start_date = models.DateField()
    end_date = models.DateField()
    
    class Meta:
        ordering = ['start_date']
    
    def __str__(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime('%b %d, %Y')
        return f"{self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d, %Y')}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date cannot be before start date.'})
    
    def get_date_count(self):
        return (self.end_date - self.start_date).days + 1
    
    def contains_date(self, check_date):
        return self.start_date <= check_date <= self.end_date
    
    def get_all_dates(self):
        current = self.start_date
        while current <= self.end_date:
            yield current
            current += timedelta(days=1)


# =============================================================================
# DYNAMIC PRICING (versioned)
# =============================================================================

class BookingWindowConfig(models.Model):
    """Configurable booking window bands. System defaults: 90+, 60-89, 30-59, 7-29."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='booking_window_configs')
    name = models.CharField(max_length=100, default="Default Windows")
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['hotel', '-is_default', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.hotel.name})"
    
    @classmethod
    def get_or_create_default(cls, hotel):
        config, created = cls.objects.get_or_create(
            hotel=hotel, is_default=True, defaults={'name': 'Default Windows'})
        if created:
            for label, min_d, max_d, order in [
                ('7-29 Days', 7, 29, 1), ('30-59 Days', 30, 59, 2),
                ('60-89 Days', 60, 89, 3), ('90+ Days', 90, None, 4),
            ]:
                BookingWindowBand.objects.create(
                    config=config, label=label, min_days=min_d, max_days=max_d, sort_order=order)
        return config


class BookingWindowBand(models.Model):
    """A single booking window band."""
    config = models.ForeignKey(BookingWindowConfig, on_delete=models.CASCADE, related_name='bands')
    label = models.CharField(max_length=50)
    min_days = models.PositiveIntegerField()
    max_days = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['config', 'sort_order']
    
    def __str__(self):
        return self.label
    
    def contains_days(self, days_out):
        if days_out < self.min_days: return False
        if self.max_days is not None and days_out > self.max_days: return False
        return True


class DynamicPricingRule(models.Model):
    """Dynamic pricing lookup table for a season. VERSIONED."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='dynamic_pricing_rules')
    version = models.ForeignKey(PricingMatrixVersion, on_delete=models.CASCADE, related_name='dynamic_pricing_rules', null=True, blank=True)
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='dynamic_pricing_rules')
    booking_window_config = models.ForeignKey(BookingWindowConfig, on_delete=models.CASCADE, related_name='dynamic_pricing_rules')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['hotel', 'season__start_date']
    
    def __str__(self):
        return f"Dynamic Pricing: {self.season.name}"


class DynamicPricingBand(models.Model):
    """Occupancy band within a dynamic pricing rule."""
    rule = models.ForeignKey(DynamicPricingRule, on_delete=models.CASCADE, related_name='bands')
    min_occupancy = models.DecimalField(max_digits=5, decimal_places=2)
    max_occupancy = models.DecimalField(max_digits=5, decimal_places=2)
    rationale = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['rule', '-min_occupancy']
    
    def __str__(self):
        if self.max_occupancy >= 999:
            return f">{self.min_occupancy}%"
        return f"{self.min_occupancy}-{self.max_occupancy}%"
    
    def contains_occupancy(self, occupancy_pct):
        return self.min_occupancy <= occupancy_pct < self.max_occupancy


class DynamicPricingMultiplier(models.Model):
    """Cell value: intersection of occupancy band x booking window band."""
    band = models.ForeignKey(DynamicPricingBand, on_delete=models.CASCADE, related_name='multipliers')
    window_band = models.ForeignKey(BookingWindowBand, on_delete=models.CASCADE, related_name='multipliers')
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.50')), MaxValueValidator(Decimal('2.00'))])
    
    class Meta:
        ordering = ['band', 'window_band__sort_order']
        unique_together = ['band', 'window_band']
    
    def __str__(self):
        return f"{self.band} x {self.window_band}: x{self.multiplier}"


class EventUplift(models.Model):
    """Manual event-based rate uplift. NOT versioned - operational."""
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='event_uplifts')
    name = models.CharField(max_length=100)
    uplift_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_date']
    
    def __str__(self):
        return f"{self.name} (+{self.uplift_percent}%)"
    
    def applies_to_date(self, check_date):
        return self.is_active and self.start_date <= check_date <= self.end_date


class DynamicPricingSuggestion(models.Model):
    """
    AI-generated suggestion to adjust a dynamic pricing multiplier cell.
    
    Generated by DynamicPricingOptimizer based on actual reservation data.
    Revenue manager reviews and accepts/rejects each suggestion.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    CONFIDENCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    DIRECTION_CHOICES = [
        ('increase', 'Increase'),
        ('decrease', 'Decrease'),
        ('unchanged', 'No Change'),
    ]
    
    hotel = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='dp_suggestions')
    
    # Which cell this applies to
    season_type = models.CharField(max_length=10, choices=Season.SEASON_TYPE_CHOICES)
    occupancy_band_label = models.CharField(max_length=50)
    window_band_label = models.CharField(max_length=50)
    
    # FK to the actual multiplier cell (for applying the change)
    band = models.ForeignKey(DynamicPricingBand, on_delete=models.SET_NULL, null=True, blank=True)
    window_band = models.ForeignKey(BookingWindowBand, on_delete=models.SET_NULL, null=True, blank=True)
    
    # The suggestion
    current_multiplier = models.DecimalField(max_digits=4, decimal_places=2)
    suggested_multiplier = models.DecimalField(max_digits=4, decimal_places=2)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    
    # Supporting data
    sample_size = models.PositiveIntegerField(default=0)
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='low')
    actual_adr = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    actual_occupancy_pct = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    actual_revpar = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    optimal_revpar = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    revpar_improvement_pct = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    reasoning = models.TextField(blank=True)
    
    # Analysis metadata
    analysis_period_start = models.DateField(null=True, blank=True)
    analysis_period_end = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    generated_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-generated_at']
        verbose_name = "Dynamic Pricing Suggestion"
        verbose_name_plural = "Dynamic Pricing Suggestions"
    
    def __str__(self):
        arrow = '↑' if self.direction == 'increase' else '↓' if self.direction == 'decrease' else '→'
        return f"{self.season_type} {self.occupancy_band_label} {self.window_band_label}: {self.current_multiplier} {arrow} {self.suggested_multiplier}"
    
    def get_change_display(self):
        diff = self.suggested_multiplier - self.current_multiplier
        if diff > 0:
            return f"+{diff:.2f}"
        return f"{diff:.2f}"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_override_for_date(hotel, check_date):
    matching = DateRateOverride.objects.filter(
        hotel=hotel, active=True,
        periods__start_date__lte=check_date, periods__end_date__gte=check_date
    ).distinct().order_by('-priority')
    return matching.first()


def get_all_overrides_for_date(hotel, check_date):
    return DateRateOverride.objects.filter(
        hotel=hotel, active=True,
        periods__start_date__lte=check_date, periods__end_date__gte=check_date
    ).distinct().order_by('-priority')


def get_overrides_for_date_range(hotel, start_date, end_date):
    result = {}
    current = start_date
    while current <= end_date:
        override = get_override_for_date(hotel, current)
        if override: result[current] = override
        current += timedelta(days=1)
    return result


def apply_override_to_bar(hotel, check_date, base_bar):
    override = get_override_for_date(hotel, check_date)
    if override:
        return override.calculate_adjusted_bar(base_bar), override, True
    return base_bar, None, False
