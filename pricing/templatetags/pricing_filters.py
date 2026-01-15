"""
Custom template filters for pricing app.
"""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Get item from dictionary by key.
    
    Usage in template:
        {{ matrix|get_item:room.id|get_item:rate_plan.id|get_item:channel.id }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def multiply(value, arg):
    """
    Multiply two values.
    
    Usage in template:
        {{ value|multiply:arg }}
    """
    try:
        return int(value) * int(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def add_filter(value, arg):
    """
    Add two values (alternative to built-in add).
    
    Usage in template:
        {{ value|add_filter:arg }}
    """
    try:
        return int(value) + int(arg)
    except (ValueError, TypeError):
        return 0
