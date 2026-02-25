"""
Forecasts admin configuration - DailyPickupSnapshot, MonthlyPickupSnapshot,
PickupCurve, OccupancyForecast.
"""

from django.contrib import admin

from pricing.models import (
    DailyPickupSnapshot, MonthlyPickupSnapshot, PickupCurve, OccupancyForecast,
)


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
