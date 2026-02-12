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
    
    
@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a variable key.
    
    Usage in template:
        {{ mydict|get_item:key_variable }}
    
    Example:
        {% with rate=room_data.summary_rates|get_item:season.id %}
            {{ rate }}
        {% endwith %}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def get_nested(dictionary, keys):
    '''
    Get nested value from dictionary using dot notation or multiple arguments.
    
    Usage in template:
        {{ matrix|get_nested:channel.id:season.id:'room_rate' }}
    '''
    if dictionary is None:
        return None
    
    # Handle multiple keys passed as separate arguments
    if isinstance(keys, str) and ':' in keys:
        keys = keys.split(':')
    elif not isinstance(keys, (list, tuple)):
        keys = [keys]
    
    result = dictionary
    for key in keys:
        if result is None:
            return None
        try:
            # Try integer key first
            result = result.get(int(key), result.get(key))
        except (ValueError, TypeError):
            result = result.get(key)
    
    return result