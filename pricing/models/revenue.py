"""
Revenue management models: MarketSegment, GroupAllotment, MonthlyBudget, LengthOfStayTier.
"""

from decimal import Decimal
from django.db import models
from .core import Property
from .pricing import PricingMatrixVersion, Season, RoomType, Channel


# =============================================================================
# MARKET SEGMENT
# =============================================================================

class MarketSegment(models.Model):
    """
    Market segment for tracking revenue by customer type.

    Examples: Leisure, Corporate, Group, MICE, Government, Airline Crew.
    """
    hotel = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name='market_segments'
    )
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30)
    description = models.TextField(blank=True)

    SEGMENT_TYPES = [
        ('leisure', 'Leisure'),
        ('corporate', 'Corporate'),
        ('group', 'Group/MICE'),
        ('government', 'Government'),
        ('crew', 'Airline Crew'),
        ('wholesale', 'Wholesale/Tour'),
        ('other', 'Other'),
    ]
    segment_type = models.CharField(
        max_length=20, choices=SEGMENT_TYPES, default='leisure'
    )

    # Rate sensitivity: how much pricing flexibility this segment has
    rate_sensitivity = models.CharField(
        max_length=10,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        default='medium',
        help_text="How price-sensitive this segment is"
    )

    # Default channel affinity (nullable)
    primary_channel = models.ForeignKey(
        Channel, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Primary booking channel for this segment"
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hotel', 'sort_order', 'name']
        unique_together = ['hotel', 'code']

    def __str__(self):
        return f"{self.name} ({self.hotel.name})"


# =============================================================================
# GROUP ALLOTMENT
# =============================================================================

class GroupAllotment(models.Model):
    """
    Block of rooms allocated to a group or tour operator.

    Tracks rooms blocked, pickup, and release dates.
    """
    hotel = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name='group_allotments'
    )

    group_name = models.CharField(max_length=200)
    group_code = models.SlugField(max_length=50, blank=True)
    contact_name = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)

    # Stay dates
    arrival_date = models.DateField()
    departure_date = models.DateField()

    # Room allocation
    rooms_blocked = models.PositiveIntegerField(
        help_text="Total rooms allocated to this group"
    )
    rooms_picked_up = models.PositiveIntegerField(
        default=0, help_text="Rooms confirmed/used from allotment"
    )

    # Rate
    agreed_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Negotiated group rate per room per night"
    )
    rate_plan = models.ForeignKey(
        'RatePlan', on_delete=models.SET_NULL, null=True, blank=True
    )

    # Cutoff
    release_date = models.DateField(
        help_text="Date after which unbooked rooms are released back to inventory"
    )

    STATUS_CHOICES = [
        ('tentative', 'Tentative'),
        ('confirmed', 'Confirmed'),
        ('picked_up', 'Picked Up'),
        ('released', 'Released'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='tentative')

    # Linked segment
    segment = models.ForeignKey(
        MarketSegment, on_delete=models.SET_NULL, null=True, blank=True
    )

    # Agent reference
    agent = models.ForeignKey(
        'TravelAgent', on_delete=models.SET_NULL, null=True, blank=True
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hotel', 'arrival_date']

    def __str__(self):
        return f"{self.group_name} ({self.arrival_date} - {self.departure_date})"

    @property
    def nights(self):
        return (self.departure_date - self.arrival_date).days

    @property
    def rooms_remaining(self):
        return max(0, self.rooms_blocked - self.rooms_picked_up)

    @property
    def pickup_percent(self):
        if self.rooms_blocked == 0:
            return 0
        return round(self.rooms_picked_up / self.rooms_blocked * 100, 1)

    @property
    def total_revenue(self):
        return self.agreed_rate * self.rooms_picked_up * self.nights

    @property
    def is_past_release(self):
        from datetime import date
        return date.today() > self.release_date


# =============================================================================
# MONTHLY BUDGET
# =============================================================================

class MonthlyBudget(models.Model):
    """
    Monthly revenue and occupancy targets for budget tracking.
    """
    hotel = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name='monthly_budgets'
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()  # 1-12

    # Targets
    revenue_target = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        help_text="Target total revenue for the month"
    )
    occupancy_target = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('70.00'),
        help_text="Target occupancy percentage"
    )
    adr_target = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Target Average Daily Rate"
    )
    revpar_target = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Target Revenue Per Available Room"
    )

    # Segment-level targets (optional JSON)
    segment_targets = models.JSONField(
        default=dict, blank=True,
        help_text="Per-segment targets: {segment_id: {revenue: X, rooms: Y}}"
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hotel', 'year', 'month']
        unique_together = ['hotel', 'year', 'month']

    def __str__(self):
        import calendar
        return f"{calendar.month_abbr[self.month]} {self.year} - {self.hotel.name}"

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]


# =============================================================================
# LENGTH OF STAY PRICING TIERS
# =============================================================================

class LengthOfStayTier(models.Model):
    """
    Structured LOS pricing tiers for a property.

    Provides tiered discounts/premiums based on length of stay.
    More structured than generic PropertyModifier with applies_to='los'.
    """
    hotel = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name='los_tiers'
    )
    version = models.ForeignKey(
        PricingMatrixVersion, on_delete=models.CASCADE,
        related_name='los_tiers', null=True, blank=True
    )

    name = models.CharField(
        max_length=100,
        help_text="e.g., 'Short Stay Premium', '7+ Night Discount'"
    )
    min_nights = models.PositiveIntegerField(help_text="Minimum nights (inclusive)")
    max_nights = models.PositiveIntegerField(
        null=True, blank=True, help_text="Maximum nights (inclusive, null = no limit)"
    )

    ADJUSTMENT_TYPES = [
        ('discount', 'Discount (% off)'),
        ('premium', 'Premium (% surcharge)'),
    ]
    adjustment_type = models.CharField(
        max_length=10, choices=ADJUSTMENT_TYPES, default='discount'
    )
    adjustment_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Percentage adjustment (e.g., 10 = 10% off or 10% surcharge)"
    )

    # Optional: restrict to specific room types or seasons
    room_type = models.ForeignKey(
        RoomType, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Apply to specific room type only (null = all)"
    )
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Apply to specific season only (null = all)"
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hotel', 'sort_order', 'min_nights']

    def __str__(self):
        max_label = f"-{self.max_nights}" if self.max_nights else "+"
        return f"{self.name} ({self.min_nights}{max_label} nights)"

    def get_multiplier(self):
        """Return the rate multiplier for this tier."""
        pct = self.adjustment_percent / Decimal('100')
        if self.adjustment_type == 'discount':
            return Decimal('1.00') - pct
        return Decimal('1.00') + pct

    def matches_stay(self, nights, room_type=None, season=None):
        """Check if a given stay length matches this tier."""
        if nights < self.min_nights:
            return False
        if self.max_nights and nights > self.max_nights:
            return False
        if self.room_type and room_type and self.room_type_id != room_type.id:
            return False
        if self.season and season and self.season_id != season.id:
            return False
        return True
