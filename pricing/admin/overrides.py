"""
Overrides admin configuration - DateRateOverride, DateRateOverridePeriod.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Min, Max

from pricing.models import DateRateOverride, DateRateOverridePeriod


# =============================================================================
# DATE RATE OVERRIDE ADMIN
# =============================================================================

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
