"""
Analytics admin configuration - BookingSource, Guest, ImportTemplate, FileImport, Reservation.
"""

from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.html import format_html
import tempfile
import os

from pricing.models import (
    Property, BookingSource, Guest, ImportTemplate, FileImport, Reservation,
)


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
# IMPORT TEMPLATES & FILE IMPORT (Property-Specific)
# =============================================================================

@admin.register(ImportTemplate)
class ImportTemplateAdmin(admin.ModelAdmin):
    """Admin for import templates."""
    list_display = ['name', 'import_type', 'hotel', 'organization', 'is_default', 'use_count', 'last_used_at', 'is_active']
    list_filter = ['import_type', 'is_active', 'hotel', 'organization']
    search_fields = ['name']
    readonly_fields = ['use_count', 'last_used_at', 'created_at', 'updated_at']


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
        from pricing.services import ReservationImportService

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
