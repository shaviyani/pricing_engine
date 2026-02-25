"""
Versions admin configuration - PricingMatrixVersion, BookingWindowConfig,
DynamicPricingRule, DynamicPricingBand, EventUplift, DynamicPricingSuggestion.
"""

from django.contrib import admin

from pricing.models import (
    PricingMatrixVersion, BookingWindowConfig, BookingWindowBand,
    DynamicPricingRule, DynamicPricingBand, DynamicPricingMultiplier,
    EventUplift, DynamicPricingSuggestion,
)


# =============================================================================
# PRICING VERSION & DYNAMIC PRICING ADMIN
# =============================================================================

class PricingMatrixVersionAdmin(admin.ModelAdmin):
    list_display = ['version_number', 'name', 'status', 'hotel', 'published_at', 'created_at']
    list_filter = ['status', 'hotel']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-version_number']


class BookingWindowBandInline(admin.TabularInline):
    model = BookingWindowBand
    extra = 0


class BookingWindowConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'hotel', 'is_default']
    inlines = [BookingWindowBandInline]


class DynamicPricingMultiplierInline(admin.TabularInline):
    model = DynamicPricingMultiplier
    extra = 0


class DynamicPricingBandInline(admin.TabularInline):
    model = DynamicPricingBand
    extra = 0


class DynamicPricingRuleAdmin(admin.ModelAdmin):
    list_display = ['season', 'hotel', 'is_active', 'version']
    list_filter = ['hotel', 'is_active']


class DynamicPricingBandAdmin(admin.ModelAdmin):
    list_display = ['rule', 'min_occupancy', 'max_occupancy', 'rationale']
    inlines = [DynamicPricingMultiplierInline]


class EventUpliftAdmin(admin.ModelAdmin):
    list_display = ['name', 'hotel', 'uplift_percent', 'start_date', 'end_date', 'is_active']
    list_filter = ['hotel', 'is_active']


admin.site.register(PricingMatrixVersion, PricingMatrixVersionAdmin)
admin.site.register(BookingWindowConfig, BookingWindowConfigAdmin)
admin.site.register(DynamicPricingRule, DynamicPricingRuleAdmin)
admin.site.register(DynamicPricingBand, DynamicPricingBandAdmin)
admin.site.register(EventUplift, EventUpliftAdmin)


class DynamicPricingSuggestionAdmin(admin.ModelAdmin):
    list_display = ['season_type', 'occupancy_band_label', 'window_band_label',
                    'current_multiplier', 'suggested_multiplier', 'direction',
                    'confidence', 'sample_size', 'status', 'generated_at']
    list_filter = ['hotel', 'status', 'confidence', 'season_type', 'direction']
    readonly_fields = ['generated_at', 'reviewed_at']
    ordering = ['-generated_at']


admin.site.register(DynamicPricingSuggestion, DynamicPricingSuggestionAdmin)
