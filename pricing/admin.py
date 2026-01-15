"""
Pricing admin configuration.
"""

from django.contrib import admin
from .models import Property, Season, RoomType, RatePlan, Channel, RateModifier, SeasonModifierOverride


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