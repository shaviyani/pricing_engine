"""
Forecast models: DailyPickupSnapshot, MonthlyPickupSnapshot,
PickupCurve, OccupancyForecast.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date, timedelta
import re

from .core import Property
from .pricing import Season, RoomType

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
    
    
