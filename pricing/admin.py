"""
Pricing admin configuration.
"""

from django.contrib import admin
from .models import Property, Season, RoomType, RatePlan, Channel, RateModifier, SeasonModifierOverride, BookingSource, Guest, Reservation, FileImport


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    """Property settings - singleton."""
    
    def has_add_permission(self, request):
        # Only allow one instance
        return not Property.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion
        return False
    
    fieldsets = (
        ('Property Information', {
            'fields': ('name',)
        }),
        ('Pricing Configuration', {
            'fields': ('reference_base_rate',),
            'description': 'Reference rate used for room index calculations (typically your Standard Room rate)'
        }),
        ('Display Settings', {
            'fields': ('currency_symbol',)
        }),
    )


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'season_index', 'expected_occupancy', 'customized_modifiers_count']
    list_editable = ['season_index', 'expected_occupancy']
    ordering = ['start_date']
    
    fieldsets = (
        (None, {
            'fields': ('name',)
        }),
        ('Date Range', {
            'fields': ('start_date', 'end_date')
        }),
        ('Pricing & Forecast', {
            'fields': ('season_index', 'expected_occupancy'),
            'description': 'Season index affects pricing. Expected occupancy is used for RevPAR calculations.'
        }),
    )
    
    def customized_modifiers_count(self, obj):
        """Show count of customized modifier discounts."""
        total = obj.modifier_discounts.count()
        customized = obj.modifier_discounts.filter(is_customized=True).count()
        if customized > 0:
            return f"✓ {customized}/{total} customized"
        return f"{total} modifiers (all default)"
    customized_modifiers_count.short_description = "Modifier Discounts"


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
        # Don't allow manual adding - auto-populated by signals
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion - these should always exist
        return False


# Add inline to Season admin
SeasonAdmin.inlines = [SeasonModifierDiscountInline]


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'pricing_method', 'number_of_rooms', 'base_rate', 'room_index', 'room_adjustment', 'sort_order', 'effective_rate_display']
    list_editable = ['pricing_method', 'number_of_rooms', 'base_rate', 'room_index', 'room_adjustment', 'sort_order']
    list_filter = ['pricing_method']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'number_of_rooms', 'sort_order')
        }),
        ('Pricing Configuration', {
            'fields': ('pricing_method', 'base_rate', 'room_index', 'room_adjustment'),
            'description': '''
                <strong>Pricing Methods:</strong><br>
                • <strong>Direct Base Rate:</strong> Use base_rate as-is<br>
                • <strong>Index Multiplier:</strong> Property.reference_base_rate × room_index (e.g., $65 × 2.0 = $130)<br>
                • <strong>Fixed Adjustment:</strong> Property.reference_base_rate + room_adjustment (e.g., $65 + $100 = $165)
            '''
        }),
    )
    
    def effective_rate_display(self, obj):
        """Show the calculated effective rate."""
        rate = obj.get_effective_base_rate()
        return f"${rate:.2f}"
    effective_rate_display.short_description = "Effective Rate"


@admin.register(RatePlan)
class RatePlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'meal_supplement', 'sort_order']
    list_editable = ['meal_supplement', 'sort_order']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'sort_order')
        }),
        ('Meal Pricing', {
            'fields': ('meal_supplement',),
            'description': 'Meal supplement cost per person in USD'
        }),
    )


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ['name', 'base_discount_percent', 'commission_percent', 'sort_order']
    list_editable = ['base_discount_percent', 'commission_percent', 'sort_order']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'sort_order')
        }),
        ('Discount & Commission', {
            'fields': ('base_discount_percent', 'commission_percent'),
            'description': 'Base discount from BAR and commission percentage the channel takes'
        }),
    )


@admin.register(RateModifier)
class RateModifierAdmin(admin.ModelAdmin):
    list_display = ['name', 'channel', 'modifier_type', 'discount_percent', 'active', 'sort_order', 'has_overrides']
    list_editable = ['discount_percent', 'active', 'sort_order']
    list_filter = ['channel', 'modifier_type', 'active']
    search_fields = ['name', 'description']
    ordering = ['channel', 'sort_order', 'name']
    
    fieldsets = (
        (None, {
            'fields': ('channel', 'name', 'modifier_type', 'sort_order')
        }),
        ('Discount', {
            'fields': ('discount_percent',),
            'description': 'Base discount percentage. Can be overridden per season using Season Overrides below.'
        }),
        ('Settings', {
            'fields': ('active', 'description'),
        }),
    )
    
    def has_overrides(self, obj):
        """Show if this modifier has season-specific customizations."""
        count = obj.season_discounts.filter(is_customized=True).count()
        total = obj.season_discounts.count()
        if count > 0:
            return f"✓ {count}/{total} customized"
        return f"{total} seasons (all default)"
    has_overrides.short_description = "Season Discounts"


class SeasonModifierOverrideInline(admin.TabularInline):
    """Inline for managing season discounts on RateModifier detail page."""
    model = SeasonModifierOverride
    extra = 0
    fields = ['season', 'discount_percent', 'is_customized', 'notes']
    readonly_fields = ['is_customized']
    verbose_name = "Season-Specific Discount"
    verbose_name_plural = "Season Discounts (Auto-populated for all seasons)"
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion - these should always exist
        return False


# Add inline to RateModifier admin
RateModifierAdmin.inlines = [SeasonModifierOverrideInline]


@admin.register(SeasonModifierOverride)
class SeasonModifierOverrideAdmin(admin.ModelAdmin):
    list_display = ['season', 'modifier', 'discount_percent', 'is_customized', 'base_discount_display', 'difference_display']
    list_editable = ['discount_percent']
    list_filter = ['season', 'modifier__channel', 'is_customized']
    ordering = ['season', 'modifier__channel', 'modifier__sort_order']
    search_fields = ['modifier__name', 'season__name']
    
    fieldsets = (
        (None, {
            'fields': ('modifier', 'season')
        }),
        ('Discount', {
            'fields': ('discount_percent', 'is_customized', 'notes'),
            'description': '''
                <strong>Auto-Populated System:</strong><br>
                • Defaults to modifier's base discount<br>
                • When you edit, automatically marks as "customized"<br>
                • Customized entries won't auto-update when modifier base changes<br>
                • Use "Reset to Base" action to revert to default
            '''
        }),
    )
    
    readonly_fields = ['is_customized']
    
    actions = ['reset_to_base', 'mark_as_customized']
    
    def base_discount_display(self, obj):
        """Show the modifier's base discount."""
        return f"{obj.modifier.discount_percent}%"
    base_discount_display.short_description = "Base Discount"
    
    def difference_display(self, obj):
        """Show difference from base."""
        diff = obj.discount_percent - obj.modifier.discount_percent
        if diff > 0:
            return f"+{diff}% (more discount)"
        elif diff < 0:
            return f"{diff}% (less discount)"
        return "Same as base"
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
    
    
    
"""
Admin configuration for Reservation Import and Analysis.

Add this to your existing pricing/admin.py file.

Features:
- FileImport admin with file upload action
- Reservation admin with filters and search
- BookingSource admin with channel mapping
- Guest admin with booking history
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


# =============================================================================
# BOOKING SOURCE ADMIN
# =============================================================================

@admin.register(BookingSource)
class BookingSourceAdmin(admin.ModelAdmin):
    """
    Admin for managing booking source mappings.
    
    Maps import source values (e.g., "Booking.com") to channels.
    """
    list_display = [
        'name', 
        'channel', 
        'is_direct', 
        'import_values_display',
        'user_mappings_display',
        'reservation_count',
        'active',
        'sort_order'
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
                <strong>Import Values:</strong> List of source values to match from import files 
                (e.g., ["Booking.com", "booking.com"])<br>
                <strong>User Mappings:</strong> User names that indicate this source when Source column is empty 
                (e.g., ["Reekko", "Maais"] for direct bookings)
            '''
        }),
        ('Commission Override', {
            'fields': ('commission_override',),
            'classes': ('collapse',),
            'description': 'Override commission % if different from channel default'
        }),
    )
    
    def import_values_display(self, obj):
        """Display import values as comma-separated."""
        if obj.import_values:
            return ', '.join(obj.import_values[:3])
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
            return format_html('<a href="{}">{} reservations</a>', url, count)
        return '0'
    reservation_count.short_description = 'Reservations'


# =============================================================================
# GUEST ADMIN
# =============================================================================

@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    """
    Admin for guest records with booking history.
    """
    list_display = [
        'name',
        'country',
        'booking_count',
        'total_nights',
        'total_revenue_display',
        'average_booking_value_display',
        'first_booking_date',
        'last_booking_date',
        'is_repeat_display',
    ]
    list_filter = [
        'country',
        ('booking_count', admin.EmptyFieldListFilter),
    ]
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
    
    def total_revenue_display(self, obj):
        """Format total revenue with currency."""
        return f"${obj.total_revenue:,.2f}"
    total_revenue_display.short_description = 'Total Revenue'
    total_revenue_display.admin_order_field = 'total_revenue'
    
    def average_booking_value_display(self, obj):
        """Format average booking value."""
        return f"${obj.average_booking_value:,.2f}"
    average_booking_value_display.short_description = 'Avg Booking Value'
    
    def is_repeat_display(self, obj):
        """Show repeat guest indicator."""
        if obj.is_repeat_guest:
            return format_html('<span style="color: green;">✓ Repeat</span>')
        return format_html('<span style="color: gray;">New</span>')
    is_repeat_display.short_description = 'Repeat Guest'
    
    actions = ['recalculate_stats']
    
    def recalculate_stats(self, request, queryset):
        """Recalculate statistics for selected guests."""
        count = 0
        for guest in queryset:
            guest.update_stats()
            count += 1
        self.message_user(request, f'Recalculated stats for {count} guests.')
    recalculate_stats.short_description = 'Recalculate statistics'


# =============================================================================
# FILE IMPORT ADMIN
# =============================================================================

class FileImportAdminForm:
    """Custom form for file upload."""
    pass


@admin.register(FileImport)
class FileImportAdmin(admin.ModelAdmin):
    """
    Admin for file imports with upload functionality.
    """
    list_display = [
        'filename',
        'status_display',
        'rows_total',
        'rows_created',
        'rows_updated',
        'rows_skipped',
        'success_rate_display',
        'date_range_display',
        'duration_display',
        'created_at',
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['filename']
    ordering = ['-created_at']
    readonly_fields = [
        'filename', 'file_hash', 'status', 'rows_total', 'rows_processed',
        'rows_created', 'rows_updated', 'rows_skipped', 'errors_display',
        'date_range_start', 'date_range_end', 'started_at', 'completed_at',
        'created_at', 'updated_at', 'duration_display', 'success_rate_display'
    ]
    
    # Disable manual add - force use of upload
    def has_add_permission(self, request):
        return True  # We'll redirect to upload page
    
    def add_view(self, request, form_url='', extra_context=None):
        """Redirect add to upload page."""
        return redirect(reverse('admin:pricing_fileimport_upload'))
    
    fieldsets = (
        (None, {
            'fields': ('filename', 'status', 'imported_by')
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
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def success_rate_display(self, obj):
        """Display success rate with progress bar."""
        rate = obj.success_rate
        color = 'green' if rate >= 90 else 'orange' if rate >= 70 else 'red'
        return format_html(
            '<div style="width:100px; background:#eee; border-radius:3px;">'
            '<div style="width:{}%; background:{}; height:20px; border-radius:3px; text-align:center; color:white; line-height:20px;">'
            '{}%</div></div>',
            rate, color, rate
        )
    success_rate_display.short_description = 'Success Rate'
    
    def date_range_display(self, obj):
        """Display date range of imported data."""
        if obj.date_range_start and obj.date_range_end:
            return f"{obj.date_range_start} to {obj.date_range_end}"
        return '—'
    date_range_display.short_description = 'Date Range'
    
    def duration_display(self, obj):
        """Display import duration."""
        if obj.duration_seconds:
            if obj.duration_seconds < 60:
                return f"{obj.duration_seconds:.1f}s"
            return f"{obj.duration_seconds / 60:.1f}m"
        return '—'
    duration_display.short_description = 'Duration'
    
    def errors_display(self, obj):
        """Display errors in readable format."""
        from django.utils.safestring import mark_safe
        from django.utils.html import escape
        
        if not obj.errors:
            return 'No errors'
        
        error_items = []
        for error in obj.errors[:20]:  # Limit to first 20
            row = error.get('row', '?')
            msg = escape(str(error.get('message', str(error))))
            error_items.append('<li>Row {}: {}</li>'.format(row, msg))
        
        if len(obj.errors) > 20:
            error_items.append('<li>... and {} more errors</li>'.format(len(obj.errors) - 20))
        
        html = '<ul style="margin:0; padding-left:20px;">{}</ul>'.format(''.join(error_items))
        return mark_safe(html)
    errors_display.short_description = 'Errors'
    
    # Custom URLs for file upload
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('upload/', self.admin_site.admin_view(self.upload_view), name='pricing_fileimport_upload'),
        ]
        return custom_urls + urls
    
    def upload_view(self, request):
        """Handle file upload."""
        from pricing.services import ReservationImportService
        
        if request.method == 'POST' and request.FILES.get('file'):
            uploaded_file = request.FILES['file']
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_file.name) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            
            try:
                # Create FileImport record
                file_import = FileImport.objects.create(
                    filename=uploaded_file.name,
                    status='pending',
                    imported_by=request.user.username if request.user else '',
                )
                
                # Run import
                service = ReservationImportService()
                result = service.import_file(tmp_path, file_import)
                
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
                
                # Redirect to the file import detail page
                return redirect(
                    reverse('admin:pricing_fileimport_change', args=[file_import.id])
                )
                
            except Exception as e:
                messages.error(request, f"Import failed: {str(e)}")
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
            return redirect(reverse('admin:pricing_fileimport_changelist'))
        
        # Show upload form
        context = {
            'title': 'Import Reservations',
            'opts': self.model._meta,
        }
        return render(request, 'pricing/upload.html', context)
    
    def changelist_view(self, request, extra_context=None):
        """Add upload button to changelist."""
        extra_context = extra_context or {}
        extra_context['show_upload_button'] = True
        return super().changelist_view(request, extra_context=extra_context)


# =============================================================================
# RESERVATION ADMIN
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
    """
    Admin for reservation records with comprehensive filtering.
    """
    list_display = [
        'confirmation_display',
        'arrival_date',
        'departure_date',
        'nights',
        'guest_display',
        'room_type_display',
        'channel_display',
        'total_amount_display',
        'lead_time_display',
        'status_display',
        'multi_room_display',
    ]
    list_filter = [
        'status',
        'channel',
        'booking_source',
        'room_type',
        'rate_plan',
        'is_multi_room',
        ('arrival_date', admin.DateFieldListFilter),
        ('booking_date', admin.DateFieldListFilter),
    ]
    search_fields = [
        'confirmation_no',
        'original_confirmation_no',
        'guest__name',
        'guest__email',
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
        ('Confirmation', {
            'fields': (
                ('confirmation_no', 'original_confirmation_no'),
                'status',
            )
        }),
        ('Dates', {
            'fields': (
                ('booking_date', 'arrival_date', 'departure_date'),
                ('nights', 'lead_time_days'),
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
            'fields': (
                ('booking_source', 'channel'),
            )
        }),
        ('Revenue', {
            'fields': (
                ('total_amount', 'adr'),
            )
        }),
        ('Multi-Room', {
            'fields': (
                'is_multi_room',
                ('parent_reservation', 'room_sequence'),
            ),
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
    
    def confirmation_display(self, obj):
        """Display confirmation with link to detail."""
        conf = obj.original_confirmation_no or obj.confirmation_no
        return format_html('<strong>{}</strong>', conf)
    confirmation_display.short_description = 'Confirmation'
    confirmation_display.admin_order_field = 'confirmation_no'
    
    def guest_display(self, obj):
        """Display guest name with country."""
        if obj.guest:
            country = f" ({obj.guest.country})" if obj.guest.country else ""
            if obj.guest.is_repeat_guest:
                return format_html(
                    '{}{} <span style="color:green;">★</span>',
                    obj.guest.name, country
                )
            return f"{obj.guest.name}{country}"
        return '—'
    guest_display.short_description = 'Guest'
    
    def room_type_display(self, obj):
        """Display room type or original name."""
        if obj.room_type:
            return obj.room_type.name
        return obj.room_type_name or '—'
    room_type_display.short_description = 'Room Type'
    
    def channel_display(self, obj):
        """Display channel with color."""
        if obj.channel:
            return obj.channel.name
        if obj.booking_source:
            return format_html('<span style="color:gray;">{}</span>', obj.booking_source.name)
        return '—'
    channel_display.short_description = 'Channel'
    
    def total_amount_display(self, obj):
        """Display total amount formatted."""
        return f"${obj.total_amount:,.2f}"
    total_amount_display.short_description = 'Total'
    total_amount_display.admin_order_field = 'total_amount'
    
    def lead_time_display(self, obj):
        """Display lead time with bucket."""
        days = obj.lead_time_days
        bucket = obj.lead_time_bucket
        
        if days <= 7:
            color = 'red'
        elif days <= 30:
            color = 'orange'
        else:
            color = 'green'
        
        return format_html(
            '<span style="color:{};">{} days</span><br><small>{}</small>',
            color, days, bucket
        )
    lead_time_display.short_description = 'Lead Time'
    lead_time_display.admin_order_field = 'lead_time_days'
    
    def status_display(self, obj):
        """Display status with color."""
        colors = {
            'confirmed': 'blue',
            'cancelled': 'red',
            'checked_in': 'green',
            'checked_out': 'gray',
            'no_show': 'orange',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color:{};">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def multi_room_display(self, obj):
        """Display multi-room indicator."""
        if obj.is_multi_room:
            count = obj.linked_room_count
            return format_html(
                '<span style="color:purple;">🔗 {} rooms</span>',
                count
            )
        return ''
    multi_room_display.short_description = 'Multi-Room'
    
    def raw_data_display(self, obj):
        """Display raw data in readable format."""
        if not obj.raw_data:
            return '—'
        
        html = '<table style="font-size:11px;">'
        for key, value in obj.raw_data.items():
            html += f'<tr><td><strong>{key}:</strong></td><td>{value}</td></tr>'
        html += '</table>'
        return format_html(html)
    raw_data_display.short_description = 'Raw Import Data'
    
    actions = ['export_selected', 'recalculate_stats']
    
    def export_selected(self, request, queryset):
        """Export selected reservations to CSV."""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="reservations.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Confirmation', 'Booking Date', 'Arrival', 'Departure', 'Nights',
            'Guest', 'Country', 'Room Type', 'Rate Plan', 'Channel', 'Source',
            'Total', 'ADR', 'Lead Time', 'Status'
        ])
        
        for res in queryset:
            writer.writerow([
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