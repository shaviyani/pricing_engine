"""Admin configuration for revenue management models."""

from django.contrib import admin
from django.utils.html import format_html

from pricing.models import MarketSegment, GroupAllotment, MonthlyBudget, LengthOfStayTier


@admin.register(MarketSegment)
class MarketSegmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'hotel', 'segment_type', 'rate_sensitivity', 'is_active', 'sort_order']
    list_filter = ['hotel', 'segment_type', 'rate_sensitivity', 'is_active']
    search_fields = ['name', 'code']
    prepopulated_fields = {'code': ('name',)}
    raw_id_fields = ['hotel', 'primary_channel']


@admin.register(GroupAllotment)
class GroupAllotmentAdmin(admin.ModelAdmin):
    list_display = [
        'group_name', 'hotel', 'arrival_date', 'departure_date',
        'rooms_blocked', 'rooms_picked_up', 'pickup_display', 'status',
    ]
    list_filter = ['hotel', 'status', 'arrival_date']
    search_fields = ['group_name', 'group_code', 'contact_name']
    raw_id_fields = ['hotel', 'rate_plan', 'segment', 'agent']
    date_hierarchy = 'arrival_date'

    def pickup_display(self, obj):
        pct = obj.pickup_percent
        color = '#22c55e' if pct >= 80 else '#f59e0b' if pct >= 50 else '#ef4444'
        return format_html(
            '<span style="color:{};">{:.0f}%</span> ({}/{})',
            color, pct, obj.rooms_picked_up, obj.rooms_blocked
        )
    pickup_display.short_description = 'Pickup'


@admin.register(MonthlyBudget)
class MonthlyBudgetAdmin(admin.ModelAdmin):
    list_display = ['hotel', 'year', 'month', 'revenue_target', 'occupancy_target', 'adr_target']
    list_filter = ['hotel', 'year']
    ordering = ['hotel', '-year', '-month']
    raw_id_fields = ['hotel']


@admin.register(LengthOfStayTier)
class LengthOfStayTierAdmin(admin.ModelAdmin):
    list_display = ['name', 'hotel', 'min_nights', 'max_nights', 'adjustment_type', 'adjustment_percent', 'is_active']
    list_filter = ['hotel', 'adjustment_type', 'is_active']
    raw_id_fields = ['hotel', 'version', 'room_type', 'season']
