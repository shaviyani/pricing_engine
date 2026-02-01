"""
Pricing admin configuration - Multi-Property Architecture.

Supports:
- Organization management (hotel chains)
- Property management with nested inlines
- Property-scoped data (Season, RoomType, Reservation, etc.)
- Shared data (Channel, RatePlan, BookingSource, Guest)
"""

from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import Sum, Count, Avg
from decimal import Decimal
import tempfile
import os

from .models import (
    Organization, Property,
    Season, RoomType, RatePlan, Channel, RateModifier, SeasonModifierOverride,
    BookingSource, Guest, Reservation, FileImport,
    DailyPickupSnapshot, MonthlyPickupSnapshot, PickupCurve, OccupancyForecast,
    DateRateOverride, DateRateOverridePeriod
)


# =============================================================================
# ORGANIZATION & PROPERTY ADMIN
# =============================================================================

class PropertyInline(admin.TabularInline):
    """Inline for properties within an organization."""
    model = Property
    extra = 0
    fields = ['name', 'code', 'location', 'total_rooms', 'is_active']
    readonly_fields = ['total_rooms']
    show_change_link = True


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin for hotel chain/organization management."""
    list_display = ['name', 'code', 'property_count_display', 'total_rooms_display', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    prepopulated_fields = {'code': ('name',)}
    ordering = ['name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'code', 'is_active')
        }),
        ('Currency Settings', {
            'fields': ('default_currency', 'currency_symbol'),
        }),
    )
    
    inlines = [PropertyInline]
    
    def property_count_display(self, obj):
        """Display count of active properties."""
        count = obj.property_count
        if count > 0:
            url = reverse('admin:pricing_property_changelist') + f'?organization__id__exact={obj.id}'
            return format_html('<a href="{}">{} properties</a>', url, count)
        return '0'
    property_count_display.short_description = 'Properties'
    
    def total_rooms_display(self, obj):
        """Display total rooms across all properties."""
        return obj.total_rooms
    total_rooms_display.short_description = 'Total Rooms'


class RoomTypeInline(admin.TabularInline):
    """Inline for room types within a property."""
    model = RoomType
    extra = 0
    fields = ['name', 'pricing_method', 'base_rate', 'room_index', 'number_of_rooms', 'sort_order']
    ordering = ['sort_order', 'name']
    show_change_link = True


class SeasonInline(admin.TabularInline):
    """Inline for seasons within a property."""
    model = Season
    extra = 0
    fields = ['name', 'start_date', 'end_date', 'season_index', 'expected_occupancy']
    ordering = ['start_date']
    show_change_link = True


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    """Admin for individual property management."""
    list_display = [
        'name', 'organization', 'code', 'location', 
        'room_types_display', 'seasons_display', 'total_rooms',
        'is_active'
    ]
    list_filter = ['organization', 'is_active']
    search_fields = ['name', 'code', 'location']
    prepopulated_fields = {'code': ('name',)}
    ordering = ['organization', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('organization', 'name', 'code', 'is_active')
        }),
        ('Location', {
            'fields': ('location',),
        }),
        ('Pricing Configuration', {
            'fields': ('reference_base_rate',),
            'description': 'Reference rate used for room index calculations (typically your Standard Room rate)'
        }),
        ('Display Settings', {
            'fields': ('currency_symbol',),
        }),
    )
    
    inlines = [RoomTypeInline, SeasonInline]
    
    def room_types_display(self, obj):
        """Display count of room types."""
        count = obj.room_types.count()
        if count > 0:
            url = reverse('admin:pricing_roomtype_changelist') + f'?hotel__id__exact={obj.id}'
            return format_html('<a href="{}">{} types</a>', url, count)
        return '0'
    room_types_display.short_description = 'Room Types'
    
    def seasons_display(self, obj):
        """Display count of seasons."""
        count = obj.seasons.count()
        if count > 0:
            url = reverse('admin:pricing_season_changelist') + f'?hotel__id__exact={obj.id}'
            return format_html('<a href="{}">{} seasons</a>', url, count)
        return '0'
    seasons_display.short_description = 'Seasons'


# =============================================================================
# SEASON ADMIN (Property-Specific)
# =============================================================================

class SeasonModifierDiscountInline(admin.TabularInline):
    """Inline for managing all modifier discounts for this season."""
    model = SeasonModifierOverride
    extra = 0
    fields = ['modifier', 'discount_percent', 'is_customized', 'base_discount_display', 'notes']
    readonly_fields = ['modifier', 'is_customized', 'base_discount_display']
    ordering = ['modifier__channel', 'modifier__sort_order']
    verbose_name = "Modifier Discount"
    verbose_name_plural = "Rate Modifier Discounts for This Season"
    
    def base_discount_display(self, obj):
        """Show the modifier's base discount for comparison."""
        if obj.modifier_id:
            return f"{obj.modifier.discount_percent}% (base)"
        return "—"
    base_discount_display.short_description = "Base Discount"
    
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'hotel', 'start_date', 'end_date', 
        'season_index', 'expected_occupancy', 'customized_modifiers_count'
    ]
    list_editable = ['season_index', 'expected_occupancy']
    list_filter = ['hotel', 'hotel__organization']
    search_fields = ['name', 'hotel__name']
    ordering = ['hotel', 'start_date']
    
    fieldsets = (
        (None, {
            'fields': ('hotel', 'name')
        }),
        ('Date Range', {
            'fields': ('start_date', 'end_date')
        }),
        ('Pricing & Forecast', {
            'fields': ('season_index', 'expected_occupancy'),
            'description': 'Season index affects pricing. Expected occupancy is used for RevPAR calculations.'
        }),
    )
    
    inlines = [SeasonModifierDiscountInline]
    
    def customized_modifiers_count(self, obj):
        """Show count of customized modifier discounts."""
        total = obj.modifier_discounts.count()
        customized = obj.modifier_discounts.filter(is_customized=True).count()
        if customized > 0:
            return f"✓ {customized}/{total} customized"
        return f"{total} modifiers (all default)"
    customized_modifiers_count.short_description = "Modifier Discounts"


# =============================================================================
# ROOM TYPE ADMIN (Property-Specific)
# =============================================================================

@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'hotel', 'pricing_method', 'number_of_rooms',
        'base_rate', 'room_index', 'room_adjustment', 
        'sort_order', 'effective_rate_display'
    ]
    list_editable = ['pricing_method', 'number_of_rooms', 'base_rate', 'room_index', 'room_adjustment', 'sort_order']
    list_filter = ['hotel', 'hotel__organization', 'pricing_method']
    search_fields = ['name', 'hotel__name']
    ordering = ['hotel', 'sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('hotel', 'name', 'number_of_rooms', 'sort_order')
        }),
        ('Pricing Configuration', {
            'fields': ('pricing_method', 'base_rate', 'room_index', 'room_adjustment'),
            'description': '''
                <strong>Pricing Methods:</strong><br>
                • <strong>Direct Base Rate:</strong> Use base_rate as-is<br>
                • <strong>Index Multiplier:</strong> Property.reference_base_rate × room_index<br>
                • <strong>Fixed Adjustment:</strong> Property.reference_base_rate + room_adjustment
            '''
        }),
    )
    
    def effective_rate_display(self, obj):
        """Show the calculated effective rate."""
        rate = obj.get_effective_base_rate()
        return f"${rate:.2f}"
    effective_rate_display.short_description = 'Effective Rate'


# =============================================================================
# SHARED MODELS: RATE PLAN, CHANNEL, RATE MODIFIER
# =============================================================================

@admin.register(RatePlan)
class RatePlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'meal_supplement', 'sort_order', 'reservation_count']
    list_editable = ['meal_supplement', 'sort_order']
    ordering = ['sort_order', 'name']
    
    def reservation_count(self, obj):
        """Show count of reservations using this rate plan."""
        count = obj.reservations.count()
        if count > 0:
            url = reverse('admin:pricing_reservation_changelist') + f'?rate_plan__id__exact={obj.id}'
            return format_html('<a href="{}">{} reservations</a>', url, count)
        return '0'
    reservation_count.short_description = 'Reservations'


class RateModifierInline(admin.TabularInline):
    """Inline for rate modifiers within a channel."""
    model = RateModifier
    extra = 0
    fields = ['name', 'modifier_type', 'discount_percent', 'active', 'sort_order']
    ordering = ['sort_order', 'name']


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'base_discount_percent', 'commission_percent',
        'distribution_share_percent', 'modifiers_count', 'sort_order'
    ]
    list_editable = ['base_discount_percent', 'commission_percent', 'distribution_share_percent', 'sort_order']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'sort_order')
        }),
        ('Pricing', {
            'fields': ('base_discount_percent', 'commission_percent'),
            'description': 'Base discount from BAR and commission taken by the channel'
        }),
        ('Distribution', {
            'fields': ('distribution_share_percent',),
            'description': 'Expected percentage of bookings from this channel (all channels should sum to 100%)'
        }),
    )
    
    inlines = [RateModifierInline]
    
    def modifiers_count(self, obj):
        """Show count of rate modifiers."""
        count = obj.rate_modifiers.count()
        active = obj.rate_modifiers.filter(active=True).count()
        return f"{active}/{count} active"
    modifiers_count.short_description = 'Modifiers'


@admin.register(RateModifier)
class RateModifierAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'channel', 'modifier_type', 'discount_percent',
        'total_discount_display', 'active', 'sort_order'
    ]
    list_editable = ['discount_percent', 'active', 'sort_order']
    list_filter = ['channel', 'modifier_type', 'active']
    search_fields = ['name', 'channel__name']
    ordering = ['channel', 'sort_order', 'name']
    
    def total_discount_display(self, obj):
        """Show total discount from BAR including channel base."""
        total = obj.total_discount_from_bar()
        return f"{total}%"
    total_discount_display.short_description = 'Total from BAR'


@admin.register(SeasonModifierOverride)
class SeasonModifierOverrideAdmin(admin.ModelAdmin):
    list_display = [
        'modifier', 'season', 'season_hotel', 'discount_percent',
        'is_customized', 'difference_display'
    ]
    list_editable = ['discount_percent']
    list_filter = ['is_customized', 'modifier__channel', 'season__hotel']
    search_fields = ['modifier__name', 'season__name']
    ordering = ['season__hotel', 'season', 'modifier__channel', 'modifier__sort_order']
    
    actions = ['reset_to_base', 'mark_as_customized']
    
    def season_hotel(self, obj):
        """Show the property for this season."""
        return obj.season.hotel.name if obj.season and obj.season.hotel else '—'
    season_hotel.short_description = 'Property'
    season_hotel.admin_order_field = 'season__hotel__name'
    
    def difference_display(self, obj):
        """Show difference from base discount."""
        if not obj.modifier:
            return '—'
        diff = obj.discount_percent - obj.modifier.discount_percent
        if diff > 0:
            return format_html('<span style="color:green;">+{}%</span>', diff)
        elif diff < 0:
            return format_html('<span style="color:red;">{}%</span>', diff)
        return "Same"
    difference_display.short_description = "vs Base"
    
    def reset_to_base(self, request, queryset):
        """Reset selected entries to base discount."""
        count = 0
        for obj in queryset:
            obj.reset_to_base()
            count += 1
        self.message_user(request, f"Reset {count} entries to base discount.")
    reset_to_base.short_description = "Reset to base discount"
    
    def mark_as_customized(self, request, queryset):
        """Mark selected entries as customized."""
        count = queryset.update(is_customized=True)
        self.message_user(request, f"Marked {count} entries as customized.")
    mark_as_customized.short_description = "Mark as customized"


# =============================================================================
# BOOKING SOURCE ADMIN (Shared)
# =============================================================================

@admin.register(BookingSource)
class BookingSourceAdmin(admin.ModelAdmin):
    """Admin for managing booking source mappings."""
    list_display = [
        'name', 'channel', 'is_direct',
        'import_values_display', 'user_mappings_display',
        'reservation_count', 'active', 'sort_order'
    ]
    list_editable = ['channel', 'is_direct', 'active', 'sort_order']
    list_filter = ['channel', 'is_direct', 'active']
    search_fields = ['name']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'channel', 'is_direct', 'active', 'sort_order')
        }),
        ('Import Mapping', {
            'fields': ('import_values', 'user_mappings'),
            'description': '''
                <strong>Import Values:</strong> List of source values to match from import files<br>
                <strong>User Mappings:</strong> User names that indicate this source when Source is empty
            '''
        }),
        ('Commission Override', {
            'fields': ('commission_override',),
            'classes': ('collapse',),
        }),
    )
    
    def import_values_display(self, obj):
        """Display import values as comma-separated."""
        if obj.import_values:
            values = obj.import_values[:3]
            suffix = '...' if len(obj.import_values) > 3 else ''
            return ', '.join(values) + suffix
        return '—'
    import_values_display.short_description = 'Import Values'
    
    def user_mappings_display(self, obj):
        """Display user mappings as comma-separated."""
        if obj.user_mappings:
            return ', '.join(obj.user_mappings)
        return '—'
    user_mappings_display.short_description = 'User Mappings'
    
    def reservation_count(self, obj):
        """Show count of reservations from this source."""
        count = obj.reservations.count()
        if count > 0:
            url = reverse('admin:pricing_reservation_changelist') + f'?booking_source__id__exact={obj.id}'
            return format_html('<a href="{}">{}</a>', url, count)
        return '0'
    reservation_count.short_description = 'Reservations'


# =============================================================================
# GUEST ADMIN (Shared - Organization Level)
# =============================================================================

@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    """Admin for guest records with booking history."""
    list_display = [
        'name', 'country', 'booking_count', 'total_nights',
        'total_revenue_display', 'average_booking_value_display',
        'first_booking_date', 'last_booking_date', 'is_repeat_display'
    ]
    list_filter = ['country', ('booking_count', admin.EmptyFieldListFilter)]
    search_fields = ['name', 'email', 'country']
    ordering = ['-last_booking_date', 'name']
    readonly_fields = [
        'booking_count', 'total_nights', 'total_revenue',
        'first_booking_date', 'last_booking_date',
        'average_booking_value_display', 'created_at', 'updated_at'
    ]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'email', 'phone', 'country')
        }),
        ('Booking Statistics (Auto-calculated)', {
            'fields': (
                'booking_count', 'total_nights', 'total_revenue',
                'average_booking_value_display',
                'first_booking_date', 'last_booking_date'
            ),
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    actions = ['recalculate_stats']
    
    def total_revenue_display(self, obj):
        """Format total revenue with currency."""
        return f"${obj.total_revenue:,.2f}"
    total_revenue_display.short_description = 'Total Revenue'
    total_revenue_display.admin_order_field = 'total_revenue'
    
    def average_booking_value_display(self, obj):
        """Format average booking value."""
        return f"${obj.average_booking_value:,.2f}"
    average_booking_value_display.short_description = 'Avg Value'
    
    def is_repeat_display(self, obj):
        """Show repeat guest indicator."""
        if obj.is_repeat_guest:
            return format_html('<span style="color:green;">✓ Repeat</span>')
        return format_html('<span style="color:gray;">New</span>')
    is_repeat_display.short_description = 'Repeat'
    
    def recalculate_stats(self, request, queryset):
        """Recalculate statistics for selected guests."""
        count = 0
        for guest in queryset:
            guest.update_stats()
            count += 1
        self.message_user(request, f'Recalculated stats for {count} guests.')
    recalculate_stats.short_description = 'Recalculate statistics'


# =============================================================================
# FILE IMPORT ADMIN (Property-Specific)
# =============================================================================

@admin.register(FileImport)
class FileImportAdmin(admin.ModelAdmin):
    """Admin for file imports with upload functionality."""
    list_display = [
        'filename', 'hotel', 'status_display',
        'rows_total', 'rows_created', 'rows_updated', 'rows_skipped',
        'success_rate_display', 'date_range_display', 'duration_display', 'created_at'
    ]
    list_filter = ['status', 'hotel', 'hotel__organization', 'created_at']
    search_fields = ['filename', 'hotel__name']
    ordering = ['-created_at']
    readonly_fields = [
        'filename', 'file_hash', 'status', 'rows_total', 'rows_processed',
        'rows_created', 'rows_updated', 'rows_skipped', 'errors_display',
        'date_range_start', 'date_range_end', 'started_at', 'completed_at',
        'created_at', 'updated_at', 'duration_display', 'success_rate_display'
    ]
    
    fieldsets = (
        (None, {
            'fields': ('hotel', 'filename', 'status', 'imported_by')
        }),
        ('Statistics', {
            'fields': (
                ('rows_total', 'rows_processed'),
                ('rows_created', 'rows_updated', 'rows_skipped'),
                'success_rate_display',
            )
        }),
        ('Date Range', {
            'fields': ('date_range_start', 'date_range_end'),
        }),
        ('Timing', {
            'fields': ('started_at', 'completed_at', 'duration_display'),
        }),
        ('Errors', {
            'fields': ('errors_display',),
            'classes': ('collapse',),
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('Technical', {
            'fields': ('file_hash', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def has_add_permission(self, request):
        return True
    
    def add_view(self, request, form_url='', extra_context=None):
        """Redirect add to upload page."""
        return redirect(reverse('admin:pricing_fileimport_upload'))
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('upload/', self.admin_site.admin_view(self.upload_view), name='pricing_fileimport_upload'),
        ]
        return custom_urls + urls
    
    def upload_view(self, request):
        """Handle file upload for reservation import."""
        from .services import ReservationImportService
        
        if request.method == 'POST' and request.FILES.get('file'):
            uploaded_file = request.FILES['file']
            hotel_id = request.POST.get('hotel')
            
            # Get the property
            hotel = None
            if hotel_id:
                try:
                    hotel = Property.objects.get(pk=hotel_id)
                except Property.DoesNotExist:
                    messages.error(request, "Invalid property selected.")
                    return redirect(reverse('admin:pricing_fileimport_changelist'))
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_file.name) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            
            try:
                # Create FileImport record
                file_import = FileImport.objects.create(
                    hotel=hotel,
                    filename=uploaded_file.name,
                    status='pending',
                    imported_by=request.user.username if request.user else '',
                )
                
                # Run import
                service = ReservationImportService()
                result = service.import_file(tmp_path, file_import, hotel=hotel)
                
                if result['success']:
                    messages.success(
                        request,
                        f"Successfully imported {uploaded_file.name}: "
                        f"{result['rows_created']} created, {result['rows_updated']} updated, "
                        f"{result['rows_skipped']} skipped"
                    )
                else:
                    messages.warning(
                        request,
                        f"Import completed with issues: {len(result['errors'])} errors"
                    )
                
                return redirect(reverse('admin:pricing_fileimport_change', args=[file_import.id]))
                
            except Exception as e:
                messages.error(request, f"Import failed: {str(e)}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
            return redirect(reverse('admin:pricing_fileimport_changelist'))
        
        # Show upload form with property selector
        properties = Property.objects.filter(is_active=True).select_related('organization')
        context = {
            'title': 'Import Reservations',
            'opts': self.model._meta,
            'properties': properties,
        }
        return render(request, 'pricing/upload.html', context)
    
    def changelist_view(self, request, extra_context=None):
        """Add upload button to changelist."""
        extra_context = extra_context or {}
        extra_context['show_upload_button'] = True
        return super().changelist_view(request, extra_context=extra_context)
    
    def status_display(self, obj):
        """Display status with color coding."""
        colors = {
            'pending': 'gray',
            'processing': 'blue',
            'completed': 'green',
            'completed_with_errors': 'orange',
            'failed': 'red',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color:{};">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def success_rate_display(self, obj):
        """Display success rate."""
        rate = obj.success_rate
        if rate >= 90:
            color = 'green'
        elif rate >= 70:
            color = 'orange'
        else:
            color = 'red'
        return format_html('<span style="color:{};">{}%</span>', color, rate)
    success_rate_display.short_description = 'Success Rate'
    
    def date_range_display(self, obj):
        """Display date range of imported data."""
        if obj.date_range_start and obj.date_range_end:
            return f"{obj.date_range_start} → {obj.date_range_end}"
        return '—'
    date_range_display.short_description = 'Date Range'
    
    def duration_display(self, obj):
        """Display import duration."""
        seconds = obj.duration_seconds
        if seconds is not None:
            if seconds < 60:
                return f"{seconds:.1f}s"
            return f"{seconds/60:.1f}m"
        return '—'
    duration_display.short_description = 'Duration'
    
    def errors_display(self, obj):
        """Display errors in readable format."""
        if not obj.errors:
            return 'No errors'
        
        html = '<div style="max-height:300px; overflow:auto;">'
        for error in obj.errors[:50]:  # Limit to first 50 errors
            html += f'<p><strong>Row {error.get("row", "?")}:</strong> {error.get("message", "Unknown error")}</p>'
        if len(obj.errors) > 50:
            html += f'<p><em>... and {len(obj.errors) - 50} more errors</em></p>'
        html += '</div>'
        return format_html(html)
    errors_display.short_description = 'Errors'


# =============================================================================
# RESERVATION ADMIN (Property-Specific)
# =============================================================================

class LinkedRoomInline(admin.TabularInline):
    """Inline for linked rooms in multi-room bookings."""
    model = Reservation
    fk_name = 'parent_reservation'
    extra = 0
    max_num = 10
    fields = [
        'original_confirmation_no', 'room_sequence', 'room_type',
        'arrival_date', 'nights', 'total_amount', 'status'
    ]
    readonly_fields = fields
    can_delete = False
    verbose_name = "Linked Room"
    verbose_name_plural = "Linked Rooms"
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    """Admin for reservation records with comprehensive filtering."""
    list_display = [
        'confirmation_display', 'hotel',
        'arrival_date', 'departure_date', 'nights',
        'guest_display', 'room_type_display', 'channel_display',
        'total_amount_display', 'lead_time_display',
        'status_display', 'multi_room_display'
    ]
    list_filter = [
        'hotel', 'hotel__organization',
        'status', 'channel', 'booking_source', 'room_type', 'rate_plan',
        'is_multi_room',
        ('arrival_date', admin.DateFieldListFilter),
        ('booking_date', admin.DateFieldListFilter),
    ]
    search_fields = [
        'confirmation_no', 'original_confirmation_no',
        'guest__name', 'guest__email', 'hotel__name'
    ]
    date_hierarchy = 'arrival_date'
    ordering = ['-booking_date', '-arrival_date']
    
    readonly_fields = [
        'confirmation_no', 'original_confirmation_no', 'lead_time_days',
        'adr', 'channel', 'is_multi_room', 'parent_reservation',
        'room_sequence', 'file_import', 'raw_data_display',
        'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Property & Confirmation', {
            'fields': (
                'hotel',
                ('confirmation_no', 'original_confirmation_no'),
                'status',
            )
        }),
        ('Dates', {
            'fields': (
                ('booking_date', 'arrival_date', 'departure_date'),
                ('nights', 'lead_time_days'),
                'cancellation_date',
            )
        }),
        ('Guest', {
            'fields': ('guest', ('adults', 'children')),
        }),
        ('Room & Rate', {
            'fields': (
                ('room_type', 'room_type_name'),
                ('rate_plan', 'rate_plan_name'),
            )
        }),
        ('Channel', {
            'fields': (('booking_source', 'channel'),)
        }),
        ('Revenue', {
            'fields': (('total_amount', 'adr'),)
        }),
        ('Multi-Room', {
            'fields': ('is_multi_room', ('parent_reservation', 'room_sequence')),
            'classes': ('collapse',),
        }),
        ('Import Info', {
            'fields': ('file_import', 'raw_data_display'),
            'classes': ('collapse',),
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    inlines = [LinkedRoomInline]
    
    actions = ['export_selected', 'recalculate_stats']
    
    def confirmation_display(self, obj):
        """Display confirmation with link to detail."""
        return obj.original_confirmation_no or obj.confirmation_no
    confirmation_display.short_description = 'Confirmation'
    confirmation_display.admin_order_field = 'confirmation_no'
    
    def guest_display(self, obj):
        """Display guest name with link."""
        if obj.guest:
            url = reverse('admin:pricing_guest_change', args=[obj.guest.id])
            return format_html('<a href="{}">{}</a>', url, obj.guest.name)
        return '—'
    guest_display.short_description = 'Guest'
    
    def room_type_display(self, obj):
        """Display room type."""
        if obj.room_type:
            return obj.room_type.name
        return obj.room_type_name or '—'
    room_type_display.short_description = 'Room'
    
    def channel_display(self, obj):
        """Display channel."""
        if obj.channel:
            return obj.channel.name
        return '—'
    channel_display.short_description = 'Channel'
    
    def total_amount_display(self, obj):
        """Display total amount with currency."""
        return f"${obj.total_amount:,.2f}"
    total_amount_display.short_description = 'Total'
    total_amount_display.admin_order_field = 'total_amount'
    
    def lead_time_display(self, obj):
        """Display lead time in days."""
        return f"{obj.lead_time_days}d"
    lead_time_display.short_description = 'Lead'
    lead_time_display.admin_order_field = 'lead_time_days'
    
    def status_display(self, obj):
        """Display status with color coding."""
        colors = {
            'confirmed': 'blue',
            'cancelled': 'red',
            'checked_in': 'green',
            'checked_out': 'gray',
            'no_show': 'orange',
        }
        color = colors.get(obj.status, 'gray')
        return format_html('<span style="color:{};">{}</span>', color, obj.get_status_display())
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def multi_room_display(self, obj):
        """Display multi-room indicator."""
        if obj.is_multi_room:
            count = obj.linked_room_count
            return format_html('<span style="color:purple;">🔗 {}</span>', count)
        return ''
    multi_room_display.short_description = 'Rooms'
    
    def raw_data_display(self, obj):
        """Display raw data in readable format."""
        if not obj.raw_data:
            return '—'
        
        html = '<table style="font-size:11px;">'
        for key, value in obj.raw_data.items():
            html += f'<tr><td><strong>{key}:</strong></td><td>{value}</td></tr>'
        html += '</table>'
        return format_html(html)
    raw_data_display.short_description = 'Raw Data'
    
    def export_selected(self, request, queryset):
        """Export selected reservations to CSV."""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="reservations.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Property', 'Confirmation', 'Booking Date', 'Arrival', 'Departure', 'Nights',
            'Guest', 'Country', 'Room Type', 'Rate Plan', 'Channel', 'Source',
            'Total', 'ADR', 'Lead Time', 'Status'
        ])
        
        for res in queryset.select_related('hotel', 'guest', 'room_type', 'rate_plan', 'channel', 'booking_source'):
            writer.writerow([
                res.hotel.name if res.hotel else '',
                res.original_confirmation_no or res.confirmation_no,
                res.booking_date,
                res.arrival_date,
                res.departure_date,
                res.nights,
                res.guest.name if res.guest else '',
                res.guest.country if res.guest else '',
                res.room_type.name if res.room_type else res.room_type_name,
                res.rate_plan.name if res.rate_plan else res.rate_plan_name,
                res.channel.name if res.channel else '',
                res.booking_source.name if res.booking_source else '',
                res.total_amount,
                res.adr,
                res.lead_time_days,
                res.status,
            ])
        
        return response
    export_selected.short_description = 'Export selected to CSV'
    
    def recalculate_stats(self, request, queryset):
        """Recalculate ADR and lead time for selected reservations."""
        count = 0
        for res in queryset:
            res.save()  # Triggers auto-calculation
            count += 1
        self.message_user(request, f'Recalculated stats for {count} reservations.')
    recalculate_stats.short_description = 'Recalculate ADR & lead time'


# =============================================================================
# PICKUP ANALYSIS ADMIN (Property-Specific)
# =============================================================================

@admin.register(DailyPickupSnapshot)
class DailyPickupSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'hotel', 'snapshot_date', 'arrival_date', 'days_out',
        'otb_room_nights', 'otb_revenue_display', 'otb_reservations'
    ]
    list_filter = ['hotel', 'hotel__organization', 'snapshot_date']
    search_fields = ['hotel__name']
    date_hierarchy = 'snapshot_date'
    ordering = ['-snapshot_date', 'arrival_date']
    
    def otb_revenue_display(self, obj):
        return f"${obj.otb_revenue:,.2f}"
    otb_revenue_display.short_description = 'OTB Revenue'


@admin.register(MonthlyPickupSnapshot)
class MonthlyPickupSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'hotel', 'snapshot_date', 'target_month', 'days_out',
        'otb_room_nights', 'otb_occupancy_percent', 'otb_revenue_display'
    ]
    list_filter = ['hotel', 'hotel__organization', 'snapshot_date']
    search_fields = ['hotel__name']
    date_hierarchy = 'snapshot_date'
    ordering = ['-snapshot_date', 'target_month']
    
    def otb_revenue_display(self, obj):
        return f"${obj.otb_revenue:,.2f}"
    otb_revenue_display.short_description = 'OTB Revenue'


@admin.register(PickupCurve)
class PickupCurveAdmin(admin.ModelAdmin):
    list_display = [
        'hotel', 'season_type', 'season', 'days_out',
        'cumulative_percent', 'sample_size', 'curve_version'
    ]
    list_filter = ['hotel', 'hotel__organization', 'season_type']
    search_fields = ['hotel__name']
    ordering = ['hotel', 'season_type', '-days_out']


@admin.register(OccupancyForecast)
class OccupancyForecastAdmin(admin.ModelAdmin):
    list_display = [
        'hotel', 'target_month', 'forecast_date', 'days_out',
        'otb_occupancy_percent', 'pickup_forecast_occupancy',
        'scenario_occupancy', 'variance_percent', 'confidence_level'
    ]
    list_filter = ['hotel', 'hotel__organization', 'confidence_level', 'forecast_date']
    search_fields = ['hotel__name']
    date_hierarchy = 'forecast_date'
    ordering = ['hotel', 'target_month', '-forecast_date']
    
    
    
class DateRateOverridePeriodInline(admin.TabularInline):
    """Inline for managing date periods within an override."""
    model = DateRateOverridePeriod
    extra = 1
    min_num = 1
    fields = ['start_date', 'end_date', 'date_count_display']
    readonly_fields = ['date_count_display']
    
    def date_count_display(self, obj):
        """Show number of days in period."""
        if obj.pk and obj.start_date and obj.end_date:
            days = obj.get_date_count()
            return f"{days} day{'s' if days != 1 else ''}"
        return "-"
    date_count_display.short_description = "Days"


@admin.register(DateRateOverride)
class DateRateOverrideAdmin(admin.ModelAdmin):
    """Admin for Date Rate Overrides."""
    
    list_display = [
        'name',
        'hotel',
        'adjustment_display',
        'priority_display',
        'periods_display',
        'active_display',
        'updated_at',
    ]
    
    list_filter = [
        'active',
        'override_type',
        'hotel',
        'priority',
    ]
    
    search_fields = ['name', 'notes']
    
    ordering = ['-priority', 'name']
    
    inlines = [DateRateOverridePeriodInline]
    
    fieldsets = (
        (None, {
            'fields': ('hotel', 'name', 'active')
        }),
        ('Adjustment', {
            'fields': ('override_type', 'adjustment', 'priority'),
            'description': 'Define how rates are adjusted. Higher priority overrides win when multiple apply.'
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
    )
    
    def adjustment_display(self, obj):
        """Display adjustment with color coding."""
        sign = '+' if obj.adjustment >= 0 else ''
        
        if obj.override_type == 'amount':
            text = f"{sign}${obj.adjustment}"
        else:
            text = f"{sign}{obj.adjustment}%"
        
        if obj.adjustment > 0:
            color = '#22c55e'  # Green for increase
        elif obj.adjustment < 0:
            color = '#ef4444'  # Red for decrease
        else:
            color = '#6b7280'  # Gray for zero
        
        return format_html(
            '<span style="color: {}; font-weight: 600;">{}</span>',
            color, text
        )
    adjustment_display.short_description = 'Adjustment'
    adjustment_display.admin_order_field = 'adjustment'
    
    def priority_display(self, obj):
        """Display priority with visual indicator."""
        if obj.priority >= 80:
            color = '#dc2626'  # Red for high
            label = 'HIGH'
        elif obj.priority >= 50:
            color = '#f59e0b'  # Amber for medium
            label = 'MED'
        else:
            color = '#6b7280'  # Gray for low
            label = 'LOW'
        
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px; font-weight: 600;">{}</span> '
            '<span style="color: #6b7280;">{}</span>',
            color, label, obj.priority
        )
    priority_display.short_description = 'Priority'
    priority_display.admin_order_field = 'priority'
    
    def periods_display(self, obj):
        """Display date periods summary."""
        periods = obj.periods.all()
        count = periods.count()
        
        if count == 0:
            return format_html(
                '<span style="color: #ef4444;">⚠ No dates set</span>'
            )
        
        # Get date range
        agg = periods.aggregate(
            min_date=Min('start_date'),
            max_date=Max('end_date')
        )
        
        if count == 1:
            period = periods.first()
            if period.start_date == period.end_date:
                text = period.start_date.strftime('%b %d, %Y')
            else:
                text = f"{period.start_date.strftime('%b %d')} - {period.end_date.strftime('%b %d, %Y')}"
        else:
            text = f"{count} periods ({agg['min_date'].strftime('%b %d')} - {agg['max_date'].strftime('%b %d')})"
        
        return format_html(
            '<span style="color: #3b82f6;">{}</span>',
            text
        )
    periods_display.short_description = 'Dates'
    
    def active_display(self, obj):
        """Display active status with icon."""
        if obj.active:
            return format_html(
                '<span style="color: #22c55e; font-size: 16px;">●</span> Active'
            )
        return format_html(
            '<span style="color: #9ca3af; font-size: 16px;">○</span> Inactive'
        )
    active_display.short_description = 'Status'
    active_display.admin_order_field = 'active'
    
    def get_queryset(self, request):
        """Optimize queryset with period counts."""
        qs = super().get_queryset(request)
        return qs.prefetch_related('periods').annotate(
            period_count=Count('periods')
        )
    
    actions = ['activate_overrides', 'deactivate_overrides']
    
    @admin.action(description='Activate selected overrides')
    def activate_overrides(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f'{updated} override(s) activated.')
    
    @admin.action(description='Deactivate selected overrides')
    def deactivate_overrides(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f'{updated} override(s) deactivated.')


@admin.register(DateRateOverridePeriod)
class DateRateOverridePeriodAdmin(admin.ModelAdmin):
    """
    Standalone admin for periods - usually managed via inline.
    Useful for bulk operations and reporting.
    """
    list_display = [
        'override',
        'start_date',
        'end_date',
        'date_count',
        'override_adjustment',
        'is_active',
    ]
    
    list_filter = [
        'override__active',
        'override__hotel',
        'start_date',
    ]
    
    search_fields = ['override__name']
    
    date_hierarchy = 'start_date'
    
    ordering = ['start_date']
    
    def date_count(self, obj):
        """Display number of days."""
        days = obj.get_date_count()
        return f"{days} day{'s' if days != 1 else ''}"
    date_count.short_description = 'Duration'
    
    def override_adjustment(self, obj):
        """Display parent override's adjustment."""
        return obj.override.get_adjustment_display()
    override_adjustment.short_description = 'Adjustment'
    
    def is_active(self, obj):
        """Display parent override's active status."""
        return obj.override.active
    is_active.boolean = True
    is_active.short_description = 'Active'