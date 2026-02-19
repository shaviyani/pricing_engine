"""
Platform Data Models
====================

Global market intelligence data managed by the platform operator (superuser).
Shared across all organizations and properties by country_code.

Scoping:
    - MarketArrivalData: country_code (e.g., 'MV' for Maldives)
    - MarketEvent: country_code
    - PlatformFileImport: tracks upload history
    - PlatformImportTemplate: saved column mappings for platform imports

Tenant properties access this data via MarketSignalService using their
Property.country_code as the join key.
"""

from decimal import Decimal
from django.db import models
from django.conf import settings


# =============================================================================
# MARKET ARRIVAL DATA
# =============================================================================

class MarketArrivalData(models.Model):
    """
    Country-level tourism arrival statistics.
    
    Source: Tourism ministry reports (e.g., Maldives MoT monthly report).
    Shared across ALL organizations and properties in the same country.
    
    Example:
        country_code: 'MV'
        report_period: 2026-01-01
        origin_country: 'Italy'
        arrivals: 12450
        market_share_pct: 8.2
    """
    country_code = models.CharField(
        max_length=2,
        db_index=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g., 'MV' for Maldives)"
    )
    report_period = models.DateField(
        help_text="First day of the reporting period (e.g., 2026-01-01 for Jan 2026)"
    )
    origin_country = models.CharField(
        max_length=100,
        help_text="Tourist source market (e.g., 'Italy', 'Germany', 'China')"
    )
    arrivals = models.PositiveIntegerField(
        default=0,
        help_text="Number of tourist arrivals from this country"
    )
    market_share_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Market share percentage"
    )
    yoy_change_pct = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        help_text="Year-over-year change percentage"
    )
    source_report = models.CharField(
        max_length=200, blank=True,
        help_text="Source reference (e.g., 'MoT Monthly Report Jan 2026')"
    )
    
    file_import = models.ForeignKey(
        'PlatformFileImport', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='arrival_records'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-report_period', 'origin_country']
        verbose_name = "Market Arrival Data"
        verbose_name_plural = "Market Arrival Data"
        unique_together = ['country_code', 'report_period', 'origin_country']
    
    def __str__(self):
        return f"{self.country_code} {self.report_period:%b %Y} — {self.origin_country}: {self.arrivals:,}"


# =============================================================================
# MARKET EVENTS
# =============================================================================

class MarketEvent(models.Model):
    """
    Global event calendar shared across all properties in a country.
    
    Events that affect demand: religious holidays, festivals, school holidays,
    conferences, sporting events, etc.
    
    Different from EventUplift (property-specific rate multiplier).
    MarketEvent is informational + feeds into demand forecasting.
    Properties can optionally create EventUplifts based on MarketEvents.
    """
    EVENT_TYPE_CHOICES = [
        ('religious', 'Religious Holiday'),
        ('national', 'National Holiday'),
        ('festival', 'Festival'),
        ('school', 'School Holiday'),
        ('sports', 'Sporting Event'),
        ('conference', 'Conference / Exhibition'),
        ('cultural', 'Cultural Event'),
        ('other', 'Other'),
    ]
    
    IMPACT_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    country_code = models.CharField(
        max_length=2, db_index=True,
        help_text="Country this event applies to ('MV', 'LK', 'ALL' for global)"
    )
    name = models.CharField(max_length=200)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, default='other')
    
    start_date = models.DateField()
    end_date = models.DateField()
    
    impact_level = models.CharField(
        max_length=10, choices=IMPACT_CHOICES, default='medium',
        help_text="Expected impact on demand"
    )
    demand_uplift_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Estimated demand uplift percentage"
    )
    
    source_markets = models.CharField(
        max_length=500, blank=True,
        help_text="Comma-separated source markets affected (e.g., 'Italy,Germany' or blank for all)"
    )
    
    recurring = models.BooleanField(
        default=False,
        help_text="Does this event recur annually?"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_date', 'name']
        verbose_name = "Market Event"
        verbose_name_plural = "Market Events"
    
    def __str__(self):
        return f"{self.name} ({self.start_date:%b %d} – {self.end_date:%b %d, %Y}) [{self.country_code}]"
    
    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1
    
    def get_source_markets_list(self):
        if not self.source_markets:
            return []
        return [m.strip() for m in self.source_markets.split(',') if m.strip()]


# =============================================================================
# PLATFORM FILE IMPORT
# =============================================================================

class PlatformFileImport(models.Model):
    """
    Tracks file imports for platform-level data.
    Mirrors pricing.FileImport but for platform data (no hotel FK).
    """
    IMPORT_TYPE_CHOICES = [
        ('arrival_report', 'Country Arrival Report'),
        ('event', 'Market Events'),
        ('economic', 'Economic Indicators'),
        ('benchmark', 'Industry Benchmarks'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with Errors'),
        ('failed', 'Failed'),
    ]
    
    filename = models.CharField(max_length=255)
    import_type = models.CharField(max_length=30, choices=IMPORT_TYPE_CHOICES)
    country_code = models.CharField(max_length=2, blank=True, default='MV')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    
    template = models.ForeignKey(
        'PlatformImportTemplate', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='file_imports'
    )
    
    rows_total = models.PositiveIntegerField(default=0)
    rows_processed = models.PositiveIntegerField(default=0)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    
    errors = models.JSONField(default=list, blank=True)
    column_map_used = models.JSONField(default=dict, blank=True)
    
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True
    )
    
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Platform File Import"
    
    def __str__(self):
        return f"{self.filename} ({self.get_import_type_display()}) — {self.status}"
    
    @property
    def success_rate(self):
        if self.rows_total > 0:
            return round((self.rows_created + self.rows_updated) / self.rows_total * 100, 1)
        return 0


# =============================================================================
# PLATFORM IMPORT TEMPLATE
# =============================================================================

class PlatformImportTemplate(models.Model):
    """
    Saved column mapping for platform data imports.
    Same pattern as pricing.ImportTemplate but for platform-level data.
    """
    IMPORT_TYPE_CHOICES = PlatformFileImport.IMPORT_TYPE_CHOICES
    
    name = models.CharField(max_length=200)
    import_type = models.CharField(max_length=30, choices=IMPORT_TYPE_CHOICES)
    
    column_map = models.JSONField(default=dict)
    value_transforms = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    source_headers = models.JSONField(default=list, blank=True)
    
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    use_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-use_count', 'name']
        verbose_name = "Platform Import Template"
    
    def __str__(self):
        return f"{self.name} ({self.get_import_type_display()})"
    
    def matches_headers(self, csv_headers):
        if not self.source_headers or not csv_headers:
            return 0.0
        template_set = set(h.strip().lower() for h in self.source_headers)
        csv_set = set(h.strip().lower() for h in csv_headers)
        if not template_set:
            return 0.0
        matched = template_set & csv_set
        return len(matched) / len(template_set)
    
    def record_usage(self):
        from django.utils import timezone as tz
        self.last_used_at = tz.now()
        self.use_count += 1
        self.save(update_fields=['last_used_at', 'use_count'])
