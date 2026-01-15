"""
Signal handlers for auto-populating season modifier discounts.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Season, RateModifier, SeasonModifierOverride


@receiver(post_save, sender=Season)
def create_season_modifier_entries(sender, instance, created, **kwargs):
    """
    When a season is created, automatically create discount entries for all modifiers.
    """
    if created:
        modifiers = RateModifier.objects.filter(active=True)
        for modifier in modifiers:
            SeasonModifierOverride.objects.get_or_create(
                modifier=modifier,
                season=instance,
                defaults={'discount_percent': modifier.discount_percent}
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
