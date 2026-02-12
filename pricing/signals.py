"""
Signal handlers for auto-populating season modifier discounts
and room type season modifiers.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Season, RateModifier, SeasonModifierOverride, RoomType, RoomTypeSeasonModifier


@receiver(post_save, sender=Season)
def create_season_modifier_entries(sender, instance, created, **kwargs):
    """
    When a season is created, automatically create discount entries for all modifiers
    and room type season modifier entries for all room types.
    """
    if created:
        modifiers = RateModifier.objects.filter(active=True)
        for modifier in modifiers:
            SeasonModifierOverride.objects.get_or_create(
                modifier=modifier,
                season=instance,
                defaults={'discount_percent': modifier.discount_percent}
            )
        
        # Auto-create RoomTypeSeasonModifier entries (default 1.00)
        room_types = RoomType.objects.filter(hotel=instance.hotel)
        for room_type in room_types:
            RoomTypeSeasonModifier.objects.get_or_create(
                room_type=room_type,
                season=instance,
                defaults={'modifier': 1}
            )


@receiver(post_save, sender=RoomType)
def create_room_type_season_modifier_entries(sender, instance, created, **kwargs):
    """
    When a room type is created, auto-create season modifier entries
    for all existing seasons of that property.
    """
    if created:
        seasons = Season.objects.filter(hotel=instance.hotel)
        for season in seasons:
            RoomTypeSeasonModifier.objects.get_or_create(
                room_type=instance,
                season=season,
                defaults={'modifier': 1}
            )


@receiver(post_save, sender=RateModifier)
def create_modifier_season_entries(sender, instance, created, **kwargs):
    """
    When a modifier is created, automatically create discount entries for all seasons.
    When a modifier is updated, sync non-customized season entries.
    """
    seasons = Season.objects.all()
    
    if created:
        # New modifier - create entries for all seasons
        for season in seasons:
            SeasonModifierOverride.objects.get_or_create(
                modifier=instance,
                season=season,
                defaults={'discount_percent': instance.discount_percent}
            )
    else:
        # Existing modifier - update non-customized entries if discount changed
        for season_discount in instance.season_discounts.filter(is_customized=False):
            if season_discount.discount_percent != instance.discount_percent:
                season_discount.discount_percent = instance.discount_percent
                season_discount.save()
