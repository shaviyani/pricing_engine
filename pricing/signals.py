"""
Signal handlers for auto-populating season modifier discounts
and room type season modifiers.

VERSION-AWARE: Only creates entries for records in the same version.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Season, RateModifier, SeasonModifierOverride, RoomType, RoomTypeSeasonModifier


@receiver(post_save, sender=Season)
def create_season_modifier_entries(sender, instance, created, **kwargs):
    """
    When a season is created, auto-create entries for same-version modifiers and room types.
    Also auto-creates dynamic pricing rules with default multipliers.
    """
    if created:
        # Only link to modifiers in the same version (or unversioned)
        mod_filter = {'active': True}
        if instance.version_id:
            mod_filter['version'] = instance.version
        else:
            mod_filter['version__isnull'] = True
            
        modifiers = RateModifier.objects.filter(**mod_filter)
        for modifier in modifiers:
            SeasonModifierOverride.objects.get_or_create(
                modifier=modifier, season=instance,
                defaults={'discount_percent': modifier.discount_percent}
            )
        
        # Only link to room types in the same version
        rt_filter = {'hotel': instance.hotel}
        if instance.version_id:
            rt_filter['version'] = instance.version
        else:
            rt_filter['version__isnull'] = True
            
        room_types = RoomType.objects.filter(**rt_filter)
        for room_type in room_types:
            RoomTypeSeasonModifier.objects.get_or_create(
                room_type=room_type, season=instance,
                defaults={'modifier': 1}
            )
        
        # Auto-create dynamic pricing rules with defaults for this season type
        _auto_create_dynamic_pricing(instance)
    
    else:
        # Season updated — check if season_type changed and rebuild DP rules if needed
        _auto_create_dynamic_pricing(instance)


def _auto_create_dynamic_pricing(season):
    """Create or update dynamic pricing rules for a season."""
    try:
        from pricing.services.version_service import DynamicPricingService
        svc = DynamicPricingService(season.hotel)
        svc.seed_single_season(season)
    except Exception:
        # Don't break season save if DP seeding fails
        pass


@receiver(post_save, sender=RoomType)
def create_room_type_season_modifier_entries(sender, instance, created, **kwargs):
    """
    When a room type is created, auto-create season modifier entries
    for same-version seasons.
    """
    if created:
        s_filter = {'hotel': instance.hotel}
        if instance.version_id:
            s_filter['version'] = instance.version
        else:
            s_filter['version__isnull'] = True
            
        seasons = Season.objects.filter(**s_filter)
        for season in seasons:
            RoomTypeSeasonModifier.objects.get_or_create(
                room_type=instance, season=season,
                defaults={'modifier': 1}
            )


@receiver(post_save, sender=RateModifier)
def create_modifier_season_entries(sender, instance, created, **kwargs):
    """
    When a modifier is created, auto-create discount entries for same-version seasons.
    When updated, sync non-customized entries.
    """
    s_filter = {}
    if instance.version_id:
        s_filter['version'] = instance.version
    else:
        s_filter['version__isnull'] = True
    
    seasons = Season.objects.filter(**s_filter)
    
    if created:
        for season in seasons:
            SeasonModifierOverride.objects.get_or_create(
                modifier=instance, season=season,
                defaults={'discount_percent': instance.discount_percent}
            )
    else:
        for season_discount in instance.season_discounts.filter(is_customized=False):
            if season_discount.discount_percent != instance.discount_percent:
                season_discount.discount_percent = instance.discount_percent
                season_discount.save()
