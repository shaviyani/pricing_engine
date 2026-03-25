"""
Pricing admin configuration - Season, RoomType, RatePlan, Channel, RateModifier,
SeasonModifierOverride, RoomTypeSeasonModifier.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from pricing.models import (
    Season, RoomType, RatePlan, Channel, RateModifier,
    SeasonModifierOverride, RoomTypeSeasonModifier,
)


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
        'sort_order', 'effective_rate_display', 'premium_display', 'target_occupancy'
    ]
    list_editable = ['pricing_method', 'number_of_rooms', 'base_rate', 'room_index', 'room_adjustment', 'sort_order', 'target_occupancy']
    list_filter = ['hotel', 'hotel__organization', 'pricing_method']
    search_fields = ['name', 'hotel__name']
    ordering = ['hotel', 'sort_order', 'name']

    fieldsets = (
        (None, {
            'fields': ('hotel', 'name', 'number_of_rooms', 'sort_order', 'description', 'target_occupancy')
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

    def premium_display(self, obj):
        """Show premium % vs reference rate."""
        prem = obj.get_premium_percent()
        if prem > 0:
            return f"+{prem:.0f}%"
        return "Base"
    premium_display.short_description = 'Premium %'


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
    """Inline for rate modifiers within a channel (read-only, legacy)."""
    model = RateModifier
    extra = 0
    fields = ['name', 'modifier_type', 'discount_percent', 'active', 'sort_order']
    ordering = ['sort_order', 'name']

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
    list_filter = ['channel', 'modifier_type', 'active']
    search_fields = ['name', 'channel__name']
    ordering = ['channel', 'sort_order', 'name']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

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
    list_filter = ['is_customized', 'modifier__channel', 'season__hotel']
    search_fields = ['modifier__name', 'season__name']
    ordering = ['season__hotel', 'season', 'modifier__channel', 'modifier__sort_order']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

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


@admin.register(RoomTypeSeasonModifier)
class RoomTypeSeasonModifierAdmin(admin.ModelAdmin):
    """Admin for room type season modifiers."""
    list_display = ['room_type', 'season', 'modifier', 'effective_index_display', 'notes']
    list_editable = ['modifier', 'notes']
    list_filter = ['room_type__hotel', 'season', 'room_type']
    ordering = ['room_type__hotel', 'season__start_date', 'room_type__sort_order']

    def effective_index_display(self, obj):
        """Show the effective index (season_index x modifier)."""
        eff = obj.get_effective_index()
        return f"×{eff}"
    effective_index_display.short_description = "Effective Index"
