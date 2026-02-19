from django.contrib import admin
from .models import MarketArrivalData, MarketEvent, PlatformFileImport, PlatformImportTemplate


@admin.register(MarketArrivalData)
class MarketArrivalDataAdmin(admin.ModelAdmin):
    list_display = ['country_code', 'report_period', 'origin_country', 'arrivals', 'market_share_pct', 'yoy_change_pct']
    list_filter = ['country_code', 'report_period']
    search_fields = ['origin_country']
    ordering = ['-report_period', '-arrivals']


@admin.register(MarketEvent)
class MarketEventAdmin(admin.ModelAdmin):
    list_display = ['name', 'country_code', 'event_type', 'start_date', 'end_date', 'impact_level', 'demand_uplift_pct', 'recurring', 'is_active']
    list_filter = ['country_code', 'event_type', 'impact_level', 'is_active']
    search_fields = ['name']
    ordering = ['start_date']


@admin.register(PlatformFileImport)
class PlatformFileImportAdmin(admin.ModelAdmin):
    list_display = ['filename', 'import_type', 'country_code', 'status', 'rows_total', 'rows_created', 'rows_updated', 'created_at']
    list_filter = ['import_type', 'status', 'country_code']
    ordering = ['-created_at']


@admin.register(PlatformImportTemplate)
class PlatformImportTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'import_type', 'use_count', 'last_used_at', 'is_active']
    list_filter = ['import_type', 'is_active']
