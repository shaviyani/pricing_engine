"""
Core admin configuration - Organization & Property.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from pricing.models import Organization, Property, RoomType, Season, UserOrganizationRole


# =============================================================================
# ORGANIZATION & PROPERTY ADMIN
# =============================================================================

class UserOrganizationRoleInline(admin.TabularInline):
    """Inline for user roles within an organization."""
    model = UserOrganizationRole
    extra = 1
    fields = ['user', 'role', 'is_active']
    autocomplete_fields = ['user']


class PropertyInline(admin.TabularInline):
    """Inline for properties within an organization."""
    model = Property
    extra = 0
    fields = ['name', 'code', 'location', 'total_rooms', 'is_active']
    readonly_fields = ['total_rooms']
    show_change_link = True


@admin.register(UserOrganizationRole)
class UserOrganizationRoleAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'role', 'is_active', 'created_at']
    list_filter = ['organization', 'role', 'is_active']
    search_fields = ['user__username', 'user__email', 'organization__name']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin for hotel chain/organization management."""
    list_display = ['name', 'code', 'property_count_display', 'total_rooms_display', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    prepopulated_fields = {'code': ('name',)}
    ordering = ['name']

    fieldsets = (
        (None, {
            'fields': ('name', 'code', 'is_active')
        }),
        ('Currency Settings', {
            'fields': ('default_currency', 'currency_symbol'),
        }),
    )

    inlines = [UserOrganizationRoleInline, PropertyInline]

    def property_count_display(self, obj):
        """Display count of active properties."""
        count = obj.property_count
        if count > 0:
            url = reverse('admin:pricing_property_changelist') + f'?organization__id__exact={obj.id}'
            return format_html('<a href="{}">{} properties</a>', url, count)
        return '0'
    property_count_display.short_description = 'Properties'

    def total_rooms_display(self, obj):
        """Display total rooms across all properties."""
        return obj.total_rooms
    total_rooms_display.short_description = 'Total Rooms'


class RoomTypeInline(admin.TabularInline):
    """Inline for room types within a property."""
    model = RoomType
    extra = 0
    fields = ['name', 'pricing_method', 'base_rate', 'room_index', 'number_of_rooms', 'sort_order']
    ordering = ['sort_order', 'name']
    show_change_link = True


class SeasonInline(admin.TabularInline):
    """Inline for seasons within a property."""
    model = Season
    extra = 0
    fields = ['name', 'start_date', 'end_date', 'season_index', 'expected_occupancy']
    ordering = ['start_date']
    show_change_link = True


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    """Admin for individual property management."""
    list_display = [
        'name', 'organization', 'code', 'location',
        'room_types_display', 'seasons_display', 'total_rooms',
        'is_active'
    ]
    list_filter = ['organization', 'is_active']
    search_fields = ['name', 'code', 'location']
    prepopulated_fields = {'code': ('name',)}
    ordering = ['organization', 'name']

    fieldsets = (
        (None, {
            'fields': ('organization', 'name', 'code', 'is_active')
        }),
        ('Location', {
            'fields': ('location',),
        }),
        ('Pricing Configuration', {
            'fields': ('reference_base_rate',),
            'description': 'Reference rate used for room index calculations (typically your Standard Room rate)'
        }),
        ('Display Settings', {
            'fields': ('currency_symbol',),
        }),
    )

    inlines = [RoomTypeInline, SeasonInline]

    def room_types_display(self, obj):
        """Display count of room types."""
        count = obj.room_types.count()
        if count > 0:
            url = reverse('admin:pricing_roomtype_changelist') + f'?hotel__id__exact={obj.id}'
            return format_html('<a href="{}">{} types</a>', url, count)
        return '0'
    room_types_display.short_description = 'Room Types'

    def seasons_display(self, obj):
        """Display count of seasons."""
        count = obj.seasons.count()
        if count > 0:
            url = reverse('admin:pricing_season_changelist') + f'?hotel__id__exact={obj.id}'
            return format_html('<a href="{}">{} seasons</a>', url, count)
        return '0'
    seasons_display.short_description = 'Seasons'
