"""
Admin configuration for Competitive Set & Market Position.
"""

from django.contrib import admin
from pricing.models import CompetitiveSet, MarketPosition


@admin.register(CompetitiveSet)
class CompetitiveSetAdmin(admin.ModelAdmin):
    list_display = ['competitor_name', 'hotel', 'bb_rate', 'hb_rate', 'fb_rate',
                    'rating', 'total_rooms', 'position', 'surveyed_date', 'is_active']
    list_filter = ['hotel', 'position', 'is_active']
    list_editable = ['bb_rate', 'hb_rate', 'fb_rate', 'rating', 'is_active']
    search_fields = ['competitor_name']
    ordering = ['hotel', '-bb_rate']


@admin.register(MarketPosition)
class MarketPositionAdmin(admin.ModelAdmin):
    list_display = ['hotel', 'strategy', 'bb_floor', 'bb_ceiling',
                    'market_avg_bb', 'market_median_bb', 'competitor_count',
                    'last_survey_date']
    readonly_fields = ['market_avg_bb', 'market_median_bb', 'market_min_bb',
                       'market_max_bb', 'competitor_count']
