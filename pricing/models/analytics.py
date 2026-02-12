"""
Analytics models: BookingSource, Guest, FileImport, Reservation.
"""

from django.db import models
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date, timedelta
import re

from .core import Property
from .pricing import Season, RoomType, RatePlan, Channel

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
        unique_together = ['hotel', 'confirmation_no','arrival_date', 'room_sequence']
    
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


