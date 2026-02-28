"""
Competitive intelligence models: CompetitiveSet, MarketPosition.
"""

from django.db import models
from django.db.models import Avg, Min, Max, Count
from decimal import Decimal
from datetime import date

from .core import Property


class CompetitiveSet(models.Model):
    """
    A competitor property in the same market.
    Updated periodically via CSV upload or manual entry.
    """
    POSITION_CHOICES = [
        ('luxury', 'Luxury'),
        ('premium', 'Premium'),
        ('mid', 'Mid-Range'),
        ('budget', 'Budget'),
    ]

    hotel = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='competitive_set',
        help_text="Your property this competitor is benchmarked against"
    )

    competitor_name = models.CharField(
        max_length=200,
        help_text="Competitor property name"
    )

    # Rates (nullable — not all competitors offer all plans)
    bb_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Bed & Breakfast rate ($)"
    )
    hb_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Half Board rate ($)"
    )
    fb_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Full Board rate ($)"
    )

    # Property info
    rating = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True,
        help_text="Guest rating (e.g. 9.2)"
    )
    total_rooms = models.PositiveIntegerField(
        default=0, help_text="Number of rooms"
    )
    position = models.CharField(
        max_length=20, choices=POSITION_CHOICES, default='mid',
        help_text="Market positioning tier"
    )

    # Context
    notes = models.TextField(
        blank=True,
        help_text="Differentiators, amenities, location notes"
    )
    source = models.CharField(
        max_length=100, default='Booking.com',
        help_text="Where the rate was observed"
    )
    surveyed_date = models.DateField(
        default=date.today,
        help_text="When rates were last checked"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hotel', '-bb_rate']
        unique_together = ['hotel', 'competitor_name']
        verbose_name = "Competitor"
        verbose_name_plural = "Competitive Set"

    def __str__(self):
        rate = f"${self.bb_rate}" if self.bb_rate else "n/a"
        return f"{self.competitor_name} — BB {rate} ({self.get_position_display()})"

    @classmethod
    def get_market_stats(cls, hotel):
        """
        Calculate market statistics from active competitors.
        Returns dict with avg, median, min, max BB rates and count.
        """
        qs = cls.objects.filter(hotel=hotel, is_active=True, bb_rate__isnull=False)
        stats = qs.aggregate(
            avg_bb=Avg('bb_rate'),
            min_bb=Min('bb_rate'),
            max_bb=Max('bb_rate'),
            avg_hb=Avg('hb_rate'),
            avg_fb=Avg('fb_rate'),
            avg_rating=Avg('rating'),
            count=Count('id'),
        )

        # Calculate median BB
        bb_rates = list(qs.values_list('bb_rate', flat=True).order_by('bb_rate'))
        if bb_rates:
            mid = len(bb_rates) // 2
            if len(bb_rates) % 2 == 0:
                median_bb = (bb_rates[mid - 1] + bb_rates[mid]) / 2
            else:
                median_bb = bb_rates[mid]
        else:
            median_bb = None

        return {
            'avg_bb': stats['avg_bb'],
            'median_bb': median_bb,
            'min_bb': stats['min_bb'],
            'max_bb': stats['max_bb'],
            'avg_hb': stats['avg_hb'],
            'avg_fb': stats['avg_fb'],
            'avg_rating': stats['avg_rating'],
            'count': stats['count'],
        }


class MarketPosition(models.Model):
    """
    Property's competitive position configuration.
    Derived from CompetitiveSet data + revenue manager overrides.
    One per property.
    """
    POSITION_STRATEGY = [
        ('undercut', 'Undercut (below market avg)'),
        ('match', 'Match (at market avg)'),
        ('mid_premium', 'Mid-Premium (+10-20% above avg)'),
        ('premium', 'Premium (+20-40% above avg)'),
    ]

    hotel = models.OneToOneField(
        Property,
        on_delete=models.CASCADE,
        related_name='market_position',
        help_text="Property this position belongs to"
    )

    # Auto-calculated from CompetitiveSet (read-only display)
    market_avg_bb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Market average BB rate (auto-calculated)"
    )
    market_median_bb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Market median BB rate (auto-calculated)"
    )
    market_min_bb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    market_max_bb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    competitor_count = models.PositiveIntegerField(default=0)

    # Revenue manager configurable
    strategy = models.CharField(
        max_length=20, choices=POSITION_STRATEGY, default='mid_premium',
        help_text="Your positioning strategy relative to market"
    )
    bb_floor = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('50.00'),
        help_text="Minimum BB rate — never sell below this ($)"
    )
    bb_ceiling = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('80.00'),
        help_text="Maximum BB rate for this market ($)"
    )
    hb_supplement = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('50.00'),
        help_text="HB supplement added to BB rate (total for default occupancy)"
    )
    fb_supplement = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('80.00'),
        help_text="FB supplement added to BB rate (total for default occupancy)"
    )

    last_survey_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Market Position"
        verbose_name_plural = "Market Positions"

    def __str__(self):
        return f"{self.hotel.name} — {self.get_strategy_display()} (${self.bb_floor}–${self.bb_ceiling})"

    def recalculate_from_competitors(self):
        """
        Update market stats from CompetitiveSet and auto-suggest
        floor/ceiling based on strategy.
        """
        stats = CompetitiveSet.get_market_stats(self.hotel)

        self.market_avg_bb = stats['avg_bb']
        self.market_median_bb = stats['median_bb']
        self.market_min_bb = stats['min_bb']
        self.market_max_bb = stats['max_bb']
        self.competitor_count = stats['count']

        # Auto-suggest floor/ceiling based on strategy
        avg = float(stats['avg_bb'] or 60)

        if self.strategy == 'undercut':
            self.bb_floor = Decimal(str(round(avg * 0.75)))
            self.bb_ceiling = Decimal(str(round(avg * 0.95)))
        elif self.strategy == 'match':
            self.bb_floor = Decimal(str(round(avg * 0.85)))
            self.bb_ceiling = Decimal(str(round(avg * 1.10)))
        elif self.strategy == 'mid_premium':
            self.bb_floor = Decimal(str(round(avg * 0.90)))
            self.bb_ceiling = Decimal(str(round(avg * 1.25)))
        elif self.strategy == 'premium':
            self.bb_floor = Decimal(str(round(avg * 1.00)))
            self.bb_ceiling = Decimal(str(round(avg * 1.50)))

        # Update survey date from latest competitor
        latest = CompetitiveSet.objects.filter(
            hotel=self.hotel, is_active=True
        ).order_by('-surveyed_date').values_list('surveyed_date', flat=True).first()
        if latest:
            self.last_survey_date = latest

        self.save()
        return stats
