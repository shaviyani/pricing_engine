"""
Modifiers admin configuration - PropertyModifier, ModifierRule.
Also includes bulk action helpers for creating season/channel modifiers.
"""

from django.contrib import admin
from django.utils.html import format_html

from pricing.models import (
    ModifierRule, PropertyModifier,
)


# =============================================================================
# PROPERTY MODIFIER ADMIN (Property Level)
# =============================================================================

class ModifierRuleInline(admin.TabularInline):
    """Inline for modifier rules."""
    model = ModifierRule
    extra = 0

    fields = ['rule_type', 'is_active', 'error_message']

    # Note: ManyToMany fields need to be handled separately
    # Show basic info here, edit in separate form


@admin.register(PropertyModifier)
class PropertyModifierAdmin(admin.ModelAdmin):
    """Admin for property-level modifiers."""

    list_display = [
        'name',
        'hotel',
        'modifier_type_badge',
        'applies_to_badge',
        'value_display',
        'adjustment_display',
        'linked_entity',
        'stack_order',
        'is_active',
    ]

    list_filter = [
        'hotel',
        'modifier_type',
        'applies_to',
        'is_active',
    ]

    search_fields = ['name', 'code', 'description']

    ordering = ['hotel', 'stack_order']

    raw_id_fields = ['hotel', 'version', 'season', 'room_type', 'channel']

    fieldsets = (
        (None, {
            'fields': ('hotel', 'version', 'name', 'code', 'description')
        }),
        ('Configuration', {
            'fields': ('modifier_type', 'applies_to', 'value', 'stack_order')
        }),
        ('Linked Entity', {
            'fields': ('season', 'room_type', 'channel'),
            'description': 'Link to specific entity based on "Applies To" setting',
        }),
        ('Length of Stay Settings', {
            'fields': ('min_nights', 'max_nights'),
            'classes': ('collapse',),
        }),
        ('Booking Window Settings', {
            'fields': ('min_advance_days', 'max_advance_days'),
            'classes': ('collapse',),
        }),
        ('Date Range (for Promos)', {
            'fields': ('valid_from', 'valid_until'),
            'classes': ('collapse',),
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

    inlines = [ModifierRuleInline]

    prepopulated_fields = {'code': ('name',)}

    def modifier_type_badge(self, obj):
        colors = {
            'index': '#3b82f6',
            'discount': '#22c55e',
            'surcharge': '#f59e0b',
        }
        color = colors.get(obj.modifier_type, '#6b7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_modifier_type_display()
        )
    modifier_type_badge.short_description = 'Type'

    def applies_to_badge(self, obj):
        return format_html(
            '<span style="background: #e5e7eb; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            obj.get_applies_to_display()
        )
    applies_to_badge.short_description = 'Applies To'

    def value_display(self, obj):
        return obj.get_value_display()
    value_display.short_description = 'Value'

    def adjustment_display(self, obj):
        adj = obj.get_adjustment_percent()
        if adj >= 0:
            color = '#22c55e' if obj.modifier_type == 'surcharge' else '#3b82f6'
            return format_html(
                '<span style="color: {};">+{:.1f}%</span>',
                color, adj
            )
        else:
            return format_html(
                '<span style="color: #22c55e;">{:.1f}%</span>',
                adj
            )
    adjustment_display.short_description = 'Adjustment'

    def linked_entity(self, obj):
        if obj.season:
            return format_html('Season: <strong>{}</strong>', obj.season.name)
        elif obj.room_type:
            return format_html('Room: <strong>{}</strong>', obj.room_type.name)
        elif obj.channel:
            return format_html('Channel: <strong>{}</strong>', obj.channel.name)
        return '-'
    linked_entity.short_description = 'Linked To'


# =============================================================================
# MODIFIER RULE ADMIN
# =============================================================================

@admin.register(ModifierRule)
class ModifierRuleAdmin(admin.ModelAdmin):
    """Admin for modifier rules."""

    list_display = [
        'modifier',
        'rule_type_badge',
        'rule_summary',
        'is_active',
    ]

    list_filter = [
        'modifier__hotel',
        'rule_type',
        'is_active',
    ]

    search_fields = ['modifier__name', 'error_message']

    autocomplete_fields = ['modifier']

    filter_horizontal = ['channels', 'room_types', 'seasons', 'other_modifiers']

    fieldsets = (
        (None, {
            'fields': ('modifier', 'rule_type', 'is_active')
        }),
        ('Rule Configuration', {
            'fields': ('channels', 'room_types', 'seasons', 'other_modifiers'),
            'description': 'Select entities based on rule type',
        }),
        ('Custom Message', {
            'fields': ('error_message',),
            'classes': ('collapse',),
        }),
    )

    def rule_type_badge(self, obj):
        return format_html(
            '<span style="background: #f3f4f6; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            obj.get_rule_type_display()
        )
    rule_type_badge.short_description = 'Rule Type'

    def rule_summary(self, obj):
        """Show a summary of what the rule does."""
        if obj.rule_type in ['channel_only', 'exclude_channel']:
            channels = list(obj.channels.values_list('name', flat=True))
            if channels:
                action = 'Only' if obj.rule_type == 'channel_only' else 'Exclude'
                return f"{action}: {', '.join(channels)}"

        elif obj.rule_type in ['room_type_only', 'exclude_room_type']:
            rooms = list(obj.room_types.values_list('name', flat=True))
            if rooms:
                action = 'Only' if obj.rule_type == 'room_type_only' else 'Exclude'
                return f"{action}: {', '.join(rooms)}"

        elif obj.rule_type in ['season_only', 'exclude_season']:
            seasons = list(obj.seasons.values_list('name', flat=True))
            if seasons:
                action = 'Only' if obj.rule_type == 'season_only' else 'Exclude'
                return f"{action}: {', '.join(seasons)}"

        elif obj.rule_type in ['not_with', 'requires']:
            modifiers = list(obj.other_modifiers.values_list('name', flat=True))
            if modifiers:
                action = 'Not with' if obj.rule_type == 'not_with' else 'Requires'
                return f"{action}: {', '.join(modifiers)}"

        return '-'
    rule_summary.short_description = 'Summary'


# =============================================================================
# UPDATE PROPERTY ADMIN (add new fields)
# =============================================================================

"""
Add these fields to your existing PropertyAdmin fieldsets:

    ('Tax & Service Charge', {
        'fields': (
            ('service_charge_percent', 'tax_percent'),
            'tax_on_service_charge',
        ),
    }),
    ('Rate Warnings', {
        'fields': ('min_rate_warning', 'max_discount_warning'),
        'classes': ('collapse',),
    }),
"""


# =============================================================================
# QUICK ADD ACTIONS
# =============================================================================

def create_season_modifiers(modeladmin, request, queryset):
    """
    Bulk action to create PropertyModifier for each season.
    """
    from pricing.models import PropertyModifier, Season

    created = 0
    for hotel in queryset:
        for season in Season.objects.filter(hotel=hotel):
            code = f"season-{season.id}"
            _, is_new = PropertyModifier.objects.get_or_create(
                hotel=hotel,
                code=code,
                defaults={
                    'name': season.name,
                    'modifier_type': 'index',
                    'applies_to': 'season',
                    'value': season.season_index,
                    'stack_order': 10,
                    'season': season,
                }
            )
            if is_new:
                created += 1

    modeladmin.message_user(request, f"Created {created} season modifiers.")

create_season_modifiers.short_description = "Create season modifiers for selected properties"


def create_channel_modifiers(modeladmin, request, queryset):
    """
    Bulk action to create PropertyModifier for each channel.
    """
    from pricing.models import PropertyModifier, Channel

    created = 0
    for hotel in queryset:
        for channel in Channel.objects.all():
            code = f"channel-{channel.id}"
            _, is_new = PropertyModifier.objects.get_or_create(
                hotel=hotel,
                code=code,
                defaults={
                    'name': f"{channel.name}",
                    'modifier_type': 'discount',
                    'applies_to': 'channel',
                    'value': channel.base_discount_percent,
                    'stack_order': 30,
                    'channel': channel,
                }
            )
            if is_new:
                created += 1

    modeladmin.message_user(request, f"Created {created} channel modifiers.")

create_channel_modifiers.short_description = "Create channel modifiers for selected properties"
